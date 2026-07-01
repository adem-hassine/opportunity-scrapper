from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime

from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from openclaw.core.config import get_settings
from openclaw.db.repository import update_opportunity_status
from openclaw.db.session import get_session
from openclaw.models.domain import Opportunity, RemoteMode, SubmissionResult
from openclaw.models.storage import OpportunityRecord, ProposalDraftRecord, SubmissionRecord
from openclaw.scrapers.freework_submitter import FreeWorkSubmitter
from openclaw.services.filtering import FilteringRules
from openclaw.services.proposal_generator import generate_proposal
from openclaw.services.resume_selector import load_resume_variants
from openclaw.services.telegram import (
    TelegramAction,
    build_preview_message,
    preview_action_buttons,
)
from openclaw.workflows.qualification import qualify_opportunity

logger = logging.getLogger(__name__)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    settings = get_settings()
    sender_id = query.from_user.id if query.from_user else None

    try:
        if sender_id not in settings.telegram_allowed_user_ids:
            await query.answer("Unauthorized.")
            return

        raw = query.data
        action, db_id_str = raw.split(":", 1)
        opportunity_id = int(db_id_str)

        if action == TelegramAction.QUICK_APPLY:
            await _handle_quick_apply(query, opportunity_id)
        elif action == TelegramAction.REVIEW:
            await _handle_review(query, opportunity_id)
        elif action == TelegramAction.REJECT:
            await _handle_reject(query, opportunity_id)
        elif action == TelegramAction.SEND:
            await _handle_send(query, opportunity_id)
        elif action == TelegramAction.REGENERATE:
            await _handle_regenerate(query, opportunity_id)
        elif action == TelegramAction.REJECT_PREVIEW:
            await _handle_reject_preview(query, opportunity_id)
        else:
            await query.answer("Unknown action.")
            return

    except Exception:
        logger.exception("Error handling callback %r", query.data)
        await query.answer("An error occurred.")
    finally:
        try:
            await query.answer()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Alert-level handlers
# ---------------------------------------------------------------------------

async def _handle_quick_apply(query, opportunity_id: int) -> None:
    """Generate proposal silently and submit immediately — no preview."""
    with get_session() as session:
        update_opportunity_status(session, opportunity_id, "approved")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("⚡ Génération et envoi en cours...")

    settings = get_settings()
    with get_session() as session:
        rec = session.scalars(
            select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
        ).one()
        opp = _record_to_opportunity(rec)
        mission_url = rec.payload.get("source_url")
        platform = rec.platform

    if platform != "free-work":
        await query.message.reply_text(
            f"❌ Soumission automatique non supportée pour '{platform}'. "
            "Seul Free-Work est supporté pour l'instant."
        )
        return

    rules = FilteringRules.from_settings(settings)
    resumes = load_resume_variants(settings.resume_dir)
    packet = qualify_opportunity(opp, rules=rules, resumes=resumes)

    loop = asyncio.get_running_loop()
    draft_text = await loop.run_in_executor(
        None, generate_proposal, opp, packet.resume_match, packet.memory_query, settings
    )

    draft_id: int | None = None
    with get_session() as session:
        draft = ProposalDraftRecord(
            opportunity_id=opportunity_id,
            resume_key=packet.resume_match.key if packet.resume_match else None,
            tone=packet.memory_query.preferred_tone if packet.memory_query else "consultative",
            status="drafted",
            prompt_snapshot={
                "resume_key": packet.resume_match.key if packet.resume_match else None
            },
            proposal_text=draft_text,
        )
        session.add(draft)
        session.flush()
        draft_id = draft.id

    resume_file = _resolve_resume_file(packet.resume_match.key if packet.resume_match else None)
    result = await _submit(mission_url, draft_text, resume_file, settings)
    await _reply_submission_result(query, opp.title, result, draft_text)
    await _persist_submission(opportunity_id, draft_id, mission_url, result)


async def _handle_review(query, opportunity_id: int) -> None:
    """Generate proposal and show single combined CV + proposal preview."""
    with get_session() as session:
        update_opportunity_status(session, opportunity_id, "drafting")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("📝 Génération en cours...")

    settings = get_settings()
    with get_session() as session:
        rec = session.scalars(
            select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
        ).one()
        opp = _record_to_opportunity(rec)

    rules = FilteringRules.from_settings(settings)
    resumes = load_resume_variants(settings.resume_dir)
    packet = qualify_opportunity(opp, rules=rules, resumes=resumes)

    loop = asyncio.get_running_loop()
    draft_text = await loop.run_in_executor(
        None, generate_proposal, opp, packet.resume_match, packet.memory_query, settings
    )

    with get_session() as session:
        session.add(ProposalDraftRecord(
            opportunity_id=opportunity_id,
            resume_key=packet.resume_match.key if packet.resume_match else None,
            tone=packet.memory_query.preferred_tone if packet.memory_query else "consultative",
            status="drafted",
            prompt_snapshot={
                "resume_key": packet.resume_match.key if packet.resume_match else None
            },
            proposal_text=draft_text,
        ))
        update_opportunity_status(session, opportunity_id, "drafted")

    preview_text = build_preview_message(opp, packet.resume_match, draft_text)
    markup = _preview_markup(opportunity_id)
    await query.message.reply_text(preview_text, reply_markup=markup)


async def _handle_reject(query, opportunity_id: int) -> None:
    with get_session() as session:
        update_opportunity_status(session, opportunity_id, "rejected")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✗ Rejeté.")


# ---------------------------------------------------------------------------
# Preview-level handlers
# ---------------------------------------------------------------------------

async def _handle_send(query, opportunity_id: int) -> None:
    """Submit using the stored draft proposal."""
    settings = get_settings()

    with get_session() as session:
        rec = session.scalars(
            select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
        ).one()
        mission_url = rec.payload.get("source_url")
        platform = rec.platform
        opp_title = rec.title

        draft = session.scalars(
            select(ProposalDraftRecord)
            .where(ProposalDraftRecord.opportunity_id == opportunity_id)
            .order_by(ProposalDraftRecord.id.desc())
        ).first()

    if draft is None:
        await query.message.reply_text(
            "❌ Aucun brouillon trouvé. Utilisez '📝 Review & Apply' d'abord."
        )
        return

    if platform != "free-work":
        await query.message.reply_text(
            f"❌ Soumission automatique non supportée pour '{platform}'. "
            "Seul Free-Work est supporté pour l'instant."
        )
        return

    with get_session() as session:
        update_opportunity_status(session, opportunity_id, "approved")

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("📤 Envoi de la candidature en cours...")

    resume_file = _resolve_resume_file(draft.resume_key)
    result = await _submit(mission_url, draft.proposal_text, resume_file, settings)
    await _reply_submission_result(query, opp_title, result, draft.proposal_text)
    await _persist_submission(opportunity_id, draft.id, mission_url, result)


async def _handle_regenerate(query, opportunity_id: int) -> None:
    """Regenerate proposal and update the preview message in-place."""
    # Clear buttons immediately and show progress in the same message
    await query.edit_message_text("🔄 Regénération en cours...")

    settings = get_settings()
    with get_session() as session:
        rec = session.scalars(
            select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
        ).one()
        opp = _record_to_opportunity(rec)

    rules = FilteringRules.from_settings(settings)
    resumes = load_resume_variants(settings.resume_dir)
    packet = qualify_opportunity(opp, rules=rules, resumes=resumes)

    loop = asyncio.get_running_loop()
    draft_text = await loop.run_in_executor(
        None, generate_proposal, opp, packet.resume_match, packet.memory_query, settings
    )

    with get_session() as session:
        session.add(ProposalDraftRecord(
            opportunity_id=opportunity_id,
            resume_key=packet.resume_match.key if packet.resume_match else None,
            tone=packet.memory_query.preferred_tone if packet.memory_query else "consultative",
            status="drafted",
            prompt_snapshot={
                "resume_key": packet.resume_match.key if packet.resume_match else None
            },
            proposal_text=draft_text,
        ))

    preview_text = build_preview_message(opp, packet.resume_match, draft_text)
    markup = _preview_markup(opportunity_id)
    await query.edit_message_text(preview_text, reply_markup=markup)


async def _handle_reject_preview(query, opportunity_id: int) -> None:
    with get_session() as session:
        update_opportunity_status(session, opportunity_id, "rejected")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text("✗ Rejeté.")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _preview_markup(opportunity_id: int) -> InlineKeyboardMarkup:
    buttons = preview_action_buttons(str(opportunity_id))
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(btn.label, callback_data=btn.callback_data)
        for btn in buttons
    ]])


async def _submit(
    mission_url: str | None,
    proposal_text: str,
    resume_file: str | None,
    settings,
) -> SubmissionResult:
    if not mission_url:
        return SubmissionResult(
            success=False,
            platform="free-work",
            mission_url="",
            error="Mission URL not found in DB payload. Re-scrape to populate source_url.",
        )

    submitter = FreeWorkSubmitter(
        user_data_dir=settings.playwright_storage_dir + "/freework",
        headless=False,
    )
    return await submitter.submit_application(mission_url, proposal_text, resume_file)


async def _reply_submission_result(
    query,
    opp_title: str,
    result: SubmissionResult,
    proposal_text: str,
) -> None:
    if result.success and result.error is None:
        snippet = proposal_text[:150] + "…" if len(proposal_text) > 150 else proposal_text
        await query.message.reply_text(
            f"✅ Candidature envoyée — {opp_title}\n"
            f"📋 \"{snippet}\""
        )
    else:
        await query.message.reply_text(
            f"❌ Échec — {opp_title}\n"
            f"{result.error}\n"
            "Statut conservé à 'approved' — retappez ✅ Envoyer pour réessayer."
        )


async def _persist_submission(
    opportunity_id: int,
    draft_id: int | None,
    mission_url: str | None,
    result: SubmissionResult,
) -> None:
    if result.success and result.error is None:
        status = "submitted"
    else:
        status = "approved"  # keep retryable

    with get_session() as session:
        update_opportunity_status(session, opportunity_id, status)
        session.add(SubmissionRecord(
            opportunity_id=opportunity_id,
            proposal_draft_id=draft_id,
            platform=result.platform,
            mission_url=result.mission_url or mission_url or "",
            confirmation_url=result.confirmation_url,
            success=result.success and result.error is None,
            error_message=result.error if not (result.success and result.error is None) else None,
            submitted_at=result.submitted_at or datetime.now(tz=UTC),
        ))


def _resolve_resume_file(resume_key: str | None) -> str | None:
    if resume_key is None:
        return None
    settings = get_settings()
    for variant in load_resume_variants(settings.resume_dir):
        if variant.key == resume_key:
            return variant.file_path
    return None


def _record_to_opportunity(rec: OpportunityRecord) -> Opportunity:
    p = rec.payload
    return Opportunity(
        platform=p["platform"],
        external_id=p["external_id"],
        title=p["title"],
        published_at=date.fromisoformat(p["published_at"]) if p.get("published_at") else None,
        client=p.get("client"),
        location=p.get("location"),
        daily_rate_eur=p.get("daily_rate_eur"),
        duration_months=p.get("duration_months"),
        required_experience_years=p.get("required_experience_years"),
        remote_mode=RemoteMode(p.get("remote_mode", "hybrid")),
        summary=rec.summary,
        keywords=tuple(p.get("keywords", [])),
        industry=p.get("industry"),
        source_url=p.get("source_url"),
    )
