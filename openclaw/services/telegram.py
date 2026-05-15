from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringResult
from openclaw.services.resume_selector import ResumeMatch


class TelegramAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DRAFT = "draft"


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


def default_decision_buttons(
    opportunity_id: str,
    *,
    rejected: bool = False,
) -> tuple[TelegramButton, ...]:
    if rejected:
        return tuple()
    return (
        TelegramButton("Approve", encode_callback(opportunity_id, TelegramAction.APPROVE)),
        TelegramButton("Reject", encode_callback(opportunity_id, TelegramAction.REJECT)),
        TelegramButton("Draft Proposal", encode_callback(opportunity_id, TelegramAction.DRAFT)),
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

