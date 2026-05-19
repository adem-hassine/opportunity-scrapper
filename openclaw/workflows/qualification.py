from __future__ import annotations

from dataclasses import dataclass

from openclaw.models.domain import Opportunity, ResumeVariant
from openclaw.services.filtering import FilteringResult, FilteringRules, score_opportunity
from openclaw.services.proposal_memory import ProposalMemoryQuery, build_memory_query
from openclaw.services.resume_selector import (
    DEFAULT_RESUME_VARIANTS,
    ResumeMatch,
    select_best_resume,
)
from openclaw.services.telegram import (
    TelegramButton,
    build_opportunity_alert,
    default_decision_buttons,
)


@dataclass(slots=True)
class QualificationPacket:
    filtering_result: FilteringResult
    resume_match: ResumeMatch | None
    memory_query: ProposalMemoryQuery | None
    telegram_message: str
    telegram_buttons: tuple[TelegramButton, ...]


def qualify_opportunity(
    opportunity: Opportunity,
    *,
    rules: FilteringRules,
    resumes: tuple[ResumeVariant, ...] = DEFAULT_RESUME_VARIANTS,
) -> QualificationPacket:
    filtering_result = score_opportunity(opportunity, rules)
    resume_match: ResumeMatch | None = None
    memory_query: ProposalMemoryQuery | None = None

    if not filtering_result.rejected:
        resume_match = select_best_resume(opportunity, resumes=resumes)
        memory_query = build_memory_query(opportunity, resume_match)

    return QualificationPacket(
        filtering_result=filtering_result,
        resume_match=resume_match,
        memory_query=memory_query,
        telegram_message=build_opportunity_alert(opportunity, filtering_result, resume_match),
        telegram_buttons=default_decision_buttons(
            opportunity.external_id,
            rejected=filtering_result.rejected,
        ),
    )


def qualification_packet_to_dict(packet: QualificationPacket) -> dict[str, object]:
    resume = None
    if packet.resume_match is not None:
        resume = {
            "key": packet.resume_match.key,
            "label": packet.resume_match.label,
            "score": packet.resume_match.score,
            "matched_keywords": list(packet.resume_match.matched_keywords),
            "rationale": packet.resume_match.rationale,
        }

    memory_query = None
    if packet.memory_query is not None:
        memory_query = {
            "client_type": packet.memory_query.client_type,
            "industry": packet.memory_query.industry,
            "stack_keywords": list(packet.memory_query.stack_keywords),
            "resume_key": packet.memory_query.resume_key,
            "preferred_tone": packet.memory_query.preferred_tone,
        }

    return {
        "score": packet.filtering_result.score,
        "route": packet.filtering_result.route.value,
        "rejected": packet.filtering_result.rejected,
        "reasons": packet.filtering_result.reasons,
        "matched_keywords": list(packet.filtering_result.matched_keywords),
        "signals": packet.filtering_result.matched_signals,
        "resume": resume,
        "memory_query": memory_query,
        "telegram": {
            "message": packet.telegram_message,
            "buttons": [
                {"label": button.label, "callback_data": button.callback_data}
                for button in packet.telegram_buttons
            ],
        },
    }
