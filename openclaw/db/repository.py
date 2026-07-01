from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from openclaw.models.domain import Opportunity
from openclaw.models.storage import OpportunityRecord
from openclaw.services.filtering import FilteringResult


def upsert_opportunity(
    session: Session,
    opportunity: Opportunity,
    filtering_result: FilteringResult,
) -> OpportunityRecord:
    """Insert or update an opportunity by (platform, external_id).

    On INSERT: status is set to "new".
    On UPDATE: status is NOT changed; payload is refreshed.
    """
    stmt = select(OpportunityRecord).where(
        OpportunityRecord.platform == opportunity.platform,
        OpportunityRecord.external_id == opportunity.external_id,
    )
    record = session.scalars(stmt).first()

    payload: dict[str, object] = {
        "title": opportunity.title,
        "platform": opportunity.platform,
        "external_id": opportunity.external_id,
        "published_at": opportunity.published_at.isoformat() if opportunity.published_at else None,
        "client": opportunity.client,
        "location": opportunity.location,
        "daily_rate_eur": opportunity.daily_rate_eur,
        "duration_months": opportunity.duration_months,
        "required_experience_years": opportunity.required_experience_years,
        "remote_mode": opportunity.remote_mode.value,
        "keywords": list(opportunity.keywords),
        "industry": opportunity.industry,
        "route": filtering_result.route.value,
        "reasons": filtering_result.reasons,
        "matched_keywords": list(filtering_result.matched_keywords),
        "signals": filtering_result.matched_signals,
        "source_url": opportunity.source_url,
    }

    if record is None:
        record = OpportunityRecord(
            platform=opportunity.platform,
            external_id=opportunity.external_id,
            title=opportunity.title,
            status="new",
            daily_rate_eur=opportunity.daily_rate_eur,
            location=opportunity.location,
            remote_mode=opportunity.remote_mode.value,
            industry=opportunity.industry,
            summary=opportunity.summary,
            payload=payload,
        )
        session.add(record)
    else:
        record.title = opportunity.title
        record.daily_rate_eur = opportunity.daily_rate_eur
        record.location = opportunity.location
        record.remote_mode = opportunity.remote_mode.value
        record.industry = opportunity.industry
        record.summary = opportunity.summary
        record.payload = payload

    session.flush()
    return record


def get_opportunity_by_external_id(
    session: Session,
    platform: str,
    external_id: str,
) -> OpportunityRecord | None:
    """Return the stored record for (platform, external_id), or None."""
    stmt = select(OpportunityRecord).where(
        OpportunityRecord.platform == platform,
        OpportunityRecord.external_id == external_id,
    )
    return session.scalars(stmt).first()


def update_opportunity_status(
    session: Session,
    opportunity_id: int,
    status: str,
) -> None:
    """Change the status of an existing opportunity row."""
    stmt = select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
    record = session.scalars(stmt).one()
    record.status = status
    session.flush()
