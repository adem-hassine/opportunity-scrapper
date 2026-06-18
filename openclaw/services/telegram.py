from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringResult
from openclaw.services.resume_selector import ResumeMatch

PREVIEW_SEPARATOR = "──────────────────────"
PREVIEW_MAX_CHARS = 800


class TelegramAction(StrEnum):
    QUICK_APPLY = "quick_apply"
    REVIEW = "review"
    REJECT = "reject"
    SEND = "send"
    REGENERATE = "regenerate"
    REJECT_PREVIEW = "reject_preview"


@dataclass(frozen=True, slots=True)
class TelegramButton:
    label: str
    callback_data: str


def build_opportunity_alert(
    opportunity: Opportunity,
    filtering_result: FilteringResult,
    resume_match: ResumeMatch | None = None,
) -> str:
    lines = [
        "NEW OPPORTUNITY",
        "",
        f"Platform: {opportunity.platform}",
        f"TJM: {_rate_label(opportunity.daily_rate_eur)}",
        f"Remote: {_remote_label(opportunity)}",
        f"Client: {opportunity.client or 'Unknown'}",
        f"Industry: {opportunity.industry or 'Unknown'}",
        "",
        "Stack:",
    ]
    if opportunity.keywords:
        lines.extend(f"- {keyword}" for keyword in opportunity.keywords)
    else:
        lines.append("- No keyword list yet")
    lines.extend(
        [
            "",
            f"Score: {filtering_result.score}/100",
            f"Route: {filtering_result.route.value}",
        ]
    )
    if resume_match is not None:
        lines.append(f"Suggested CV: {resume_match.label}")
    if filtering_result.reasons:
        lines.append("")
        lines.append("Notes:")
        lines.extend(f"- {reason}" for reason in filtering_result.reasons)
    return "\n".join(lines)


def build_preview_message(
    opportunity: Opportunity,
    resume_match: ResumeMatch | None,
    draft_text: str,
) -> str:
    """Build the single combined CV + proposal preview message."""
    client_part = f" — {opportunity.client}" if opportunity.client else ""
    header = f"📋 {opportunity.title}{client_part}"

    if resume_match:
        keywords_line = (
            f"Matched: {', '.join(resume_match.matched_keywords)}"
            if resume_match.matched_keywords
            else resume_match.rationale
        )
        cv_section = f"📄 CV : {resume_match.label}\n{keywords_line}"
    else:
        cv_section = "📄 CV : Java Backend (fallback)"

    total = len(draft_text)
    if total > PREVIEW_MAX_CHARS:
        preview = draft_text[:PREVIEW_MAX_CHARS] + f"…\n({total} chars total)"
    else:
        preview = draft_text

    return "\n".join([
        header,
        "",
        cv_section,
        "",
        PREVIEW_SEPARATOR,
        preview,
        PREVIEW_SEPARATOR,
    ])


def default_decision_buttons(
    opportunity_id: str,
    *,
    rejected: bool = False,
) -> tuple[TelegramButton, ...]:
    if rejected:
        return tuple()
    return (
        TelegramButton(
            "⚡ Quick Apply",
            encode_callback(opportunity_id, TelegramAction.QUICK_APPLY),
        ),
        TelegramButton(
            "📝 Review & Apply",
            encode_callback(opportunity_id, TelegramAction.REVIEW),
        ),
        TelegramButton(
            "✗ Reject",
            encode_callback(opportunity_id, TelegramAction.REJECT),
        ),
    )


def preview_action_buttons(opportunity_id: str) -> tuple[TelegramButton, ...]:
    """Buttons shown below the combined CV + proposal preview."""
    return (
        TelegramButton(
            "✅ Envoyer",
            encode_callback(opportunity_id, TelegramAction.SEND),
        ),
        TelegramButton(
            "🔄 Regénérer",
            encode_callback(opportunity_id, TelegramAction.REGENERATE),
        ),
        TelegramButton(
            "✗ Rejeter",
            encode_callback(opportunity_id, TelegramAction.REJECT_PREVIEW),
        ),
    )


def encode_callback(opportunity_id: str, action: TelegramAction) -> str:
    return f"{action.value}:{opportunity_id}"


def _rate_label(daily_rate_eur: int | None) -> str:
    return f"{daily_rate_eur} EUR" if daily_rate_eur is not None else "Unknown"


def _remote_label(opportunity: Opportunity) -> str:
    if opportunity.remote_mode == RemoteMode.REMOTE:
        return "Fully remote"
    if opportunity.remote_mode == RemoteMode.ONSITE:
        return "Onsite"
    if opportunity.remote_days_per_week is not None:
        return f"Hybrid ({opportunity.remote_days_per_week} remote day(s) per week)"
    return "Hybrid"
