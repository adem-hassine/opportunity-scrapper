"""Send a test Telegram alert for a DB opportunity. Usage: python scripts/send_test_alert.py [id]"""
import sys
from datetime import date

from sqlalchemy import select

from openclaw.bot.sender import send_alert_for_opportunity
from openclaw.core.config import get_settings
from openclaw.db.session import get_session
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.models.storage import OpportunityRecord
from openclaw.services.filtering import FilteringRules
from openclaw.workflows.qualification import qualify_opportunity

opportunity_id = int(sys.argv[1]) if len(sys.argv) > 1 else 17

settings = get_settings()
rules = FilteringRules.from_settings(settings)

with get_session() as session:
    record = session.scalars(
        select(OpportunityRecord).where(OpportunityRecord.id == opportunity_id)
    ).one()
    p = record.payload

    opp = Opportunity(
        platform=p["platform"],
        external_id=p["external_id"],
        title=p["title"],
        published_at=date.fromisoformat(p["published_at"]) if p.get("published_at") else None,
        client=p.get("client"),
        location=p.get("location"),
        daily_rate_eur=p.get("daily_rate_eur"),
        remote_mode=RemoteMode(p.get("remote_mode", "hybrid")),
        summary=record.summary,
        keywords=tuple(p.get("keywords", [])),
        industry=p.get("industry"),
    )
    record_id = record.id

packet = qualify_opportunity(opp, rules=rules)

with get_session() as session:
    rec = session.scalars(
        select(OpportunityRecord).where(OpportunityRecord.id == record_id)
    ).one()
    send_alert_for_opportunity(settings, rec, packet)

print(f"Alert sent for opportunity id={opportunity_id}. Check Telegram.")
