from __future__ import annotations

from openclaw.core.config import Settings
from openclaw.scrapers.base import OpportunityScraper
from openclaw.scrapers.freework import FreeWorkScraper, _build_search_urls
from openclaw.scrapers.lehibou import LeHibouScraper


def get_scrapers(platform: str, settings: Settings) -> list[OpportunityScraper]:
    """Return configured scraper instances for the given platform."""
    if platform == "free-work":
        search_urls = _build_search_urls(required_keywords=settings.required_keywords)
        return [
            FreeWorkScraper(
                search_url=url,
                headless=False,
                employment_types=settings.employment_type,
                minimum_tjm=settings.minimum_tjm,
                unspecified_tjm=settings.unspecified_tjm,
                minimum_duration_months=settings.minimum_duration_months,
                minimum_year_salary=settings.minimum_year_salary,
                allowed_remote_modes=settings.allowed_remote_modes,
                publication_date=settings.publication_date,
            )
            for url in search_urls
        ]
    if platform == "lehibou":
        # LeHibou uses Cloudflare Turnstile — headless mode is blocked.
        # The cf_clearance cookie (saved by `make lehibou-setup`) is only valid
        # for the same TLS fingerprint, which differs between headless and headful.
        # Running headful is required on this desktop deployment.
        return [LeHibouScraper(headless=False)]
    raise NotImplementedError(f"No scraper registered for platform: {platform!r}")
