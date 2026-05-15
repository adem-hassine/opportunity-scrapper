from fastapi import APIRouter
from pydantic import BaseModel, Field

from openclaw.core.config import get_settings
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringRules
from openclaw.workflows.qualification import qualify_opportunity

router = APIRouter(prefix="/api/v1", tags=["qualification"])


class QualificationPreviewRequest(BaseModel):
    platform: str
    external_id: str = "preview"
    title: str
    client: str | None = None
    location: str | None = None
    daily_rate_eur: int | None = None
    remote_mode: RemoteMode = RemoteMode.HYBRID
    remote_days_per_week: int | None = None
    summary: str = ""
    keywords: list[str] = Field(default_factory=list)
    industry: str | None = None


@router.post("/qualification/preview")
async def qualification_preview(payload: QualificationPreviewRequest) -> dict[str, object]:
    settings = get_settings()
    opportunity = Opportunity(
        platform=payload.platform,
        external_id=payload.external_id,
        title=payload.title,
        client=payload.client,
        location=payload.location,
        daily_rate_eur=payload.daily_rate_eur,
        remote_mode=payload.remote_mode,
        remote_days_per_week=payload.remote_days_per_week,
        summary=payload.summary,
        keywords=tuple(payload.keywords),
        industry=payload.industry,
    )
    rules = FilteringRules(
        minimum_tjm=settings.minimum_tjm,
        remote_required=settings.remote_required,
        excluded_keywords=tuple(settings.excluded_keywords),
        required_keywords=tuple(settings.required_keywords),
        auto_reject_score_below=settings.auto_reject_score_below,
        alert_score_from=settings.alert_score_from,
    )
    packet = qualify_opportunity(opportunity, rules=rules)
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

