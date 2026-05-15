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

