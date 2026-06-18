from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from openclaw.core.config import Settings, get_settings
from openclaw.db.repository import get_opportunity_by_external_id, upsert_opportunity
from openclaw.db.session import get_session
from openclaw.models.storage import OpportunityRecord
from openclaw.scrapers.freework import ScrapedOpportunityRecord
from openclaw.scrapers.registry import get_scrapers
from openclaw.services.filtering import FilteringRules, QualificationRoute
from openclaw.services.telegram import default_decision_buttons
from openclaw.workflows.qualification import QualificationPacket, qualify_opportunity

logger = logging.getLogger(__name__)


async def monitor_loop(settings: Settings) -> None:
    rules = FilteringRules.from_settings(settings)
    logger.info(
        "Monitor started. Interval: %ds. Platforms: %s",
        settings.monitor_interval_seconds,
        settings.platform_targets,
    )

    while True:
        logger.info("--- Scrape cycle starting ---")
        for platform in settings.platform_targets:
            try:
                await _scrape_platform(platform, settings, rules)
            except NotImplementedError:
                logger.warning("No scraper registered for platform %r — skipping.", platform)
            except Exception:
                logger.exception("Error scraping platform %r — continuing.", platform)

        logger.info("--- Cycle done. Sleeping %ds ---", settings.monitor_interval_seconds)
        await asyncio.sleep(settings.monitor_interval_seconds)


async def _scrape_platform(
    platform: str, settings: Settings, rules: FilteringRules
) -> None:
    scrapers = get_scrapers(platform, settings)
    seen_ids: set[str] = set()

    for scraper in scrapers:
        records: list[ScrapedOpportunityRecord] = await scraper.fetch_new_opportunity_records()
        for record in records:
            ext_id = record.opportunity.external_id
            if ext_id in seen_ids:
                continue
            seen_ids.add(ext_id)
            await _process_record(record, settings, rules)


async def _process_record(
    record: ScrapedOpportunityRecord,
    settings: Settings,
    rules: FilteringRules,
) -> None:
    opp = record.opportunity
    packet = qualify_opportunity(opp, rules=rules)

    with get_session() as session:
        existing = get_opportunity_by_external_id(session, opp.platform, opp.external_id)
        if existing is not None and existing.status != "new":
            return  # already acted on — don't reset or re-alert
        db_record = upsert_opportunity(session, opp, packet.filtering_result)
        is_new = existing is None
        db_id = db_record.id

    if is_new and packet.filtering_result.route == QualificationRoute.ALERT:
        packet.telegram_buttons = default_decision_buttons(str(db_id))
        await _send_alert(settings, db_id, opp.platform, opp.external_id, packet)
    else:
        logger.debug(
            "Skipped alert: [%s] %s route=%s is_new=%s",
            opp.platform,
            opp.external_id,
            packet.filtering_result.route.value,
            is_new,
        )


async def _send_alert(
    settings: Settings,
    db_id: int,
    platform: str,
    external_id: str,
    packet: QualificationPacket,
) -> None:
    try:
        with get_session() as session:
            rec = session.scalars(
                select(OpportunityRecord).where(OpportunityRecord.id == db_id)
            ).one()
            # Import here to avoid circular import at module level
            from openclaw.bot.sender import _send  # noqa: PLC0415
            await _send(settings, rec, packet)
        logger.info(
            "Alert sent: [%s] %s (score=%d)",
            platform,
            external_id,
            packet.filtering_result.score,
        )
    except Exception:
        logger.exception("Failed to send Telegram alert for %s/%s", platform, external_id)


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    settings = get_settings()
    asyncio.run(monitor_loop(settings))


if __name__ == "__main__":
    main()
