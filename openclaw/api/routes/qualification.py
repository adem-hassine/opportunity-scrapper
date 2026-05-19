from fastapi import APIRouter
from pydantic import BaseModel, Field

from openclaw.core.config import get_settings
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringRules
from openclaw.workflows.qualification import qualification_packet_to_dict, qualify_opportunity

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
    rules = FilteringRules.from_settings(settings)
    packet = qualify_opportunity(opportunity, rules=rules)
    return qualification_packet_to_dict(packet)
