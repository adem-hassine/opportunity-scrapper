from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlparse

from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.scrapers.base import OpportunityScraper, PlatformSession

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:
    PlaywrightTimeoutError = TimeoutError
    async_playwright = None

if TYPE_CHECKING:
    from playwright.async_api import Page
else:
    Page = Any

FREEWORK_BASE_URL = "https://www.free-work.com"
DEFAULT_SEARCH_URL = "https://www.free-work.com/fr/tech-it/jobs/java"
MISSION_LINK_SELECTOR = "a[href*='/job-mission/']"

COOKIE_ACCEPT_SELECTORS = (
    "#didomi-notice-agree-button",
    "button:has-text('Accepter')",
    "button:has-text('Tout accepter')",
    "button:has-text('Accept all')",
)

KEYWORD_PATTERNS = (
    ("spring boot", "spring boot"),
    ("spring security", "spring security"),
    ("java 21", "java 21"),
    ("java 17", "java 17"),
    ("java 11", "java 11"),
    ("java 8", "java 8"),
    ("java", "java"),
    ("spring", "spring"),
    ("keycloak", "keycloak"),
    ("oauth2", "oauth2"),
    ("oauth 2", "oauth2"),
    ("openid connect", "openid connect"),
    ("sso", "sso"),
    ("saml", "saml"),
    ("iam", "iam"),
    ("kubernetes", "kubernetes"),
    ("docker", "docker"),
    ("aws", "aws"),
    ("azure", "azure"),
    ("gcp", "gcp"),
    ("kafka", "kafka"),
    ("postgresql", "postgresql"),
    ("postgres", "postgresql"),
    ("oracle", "oracle"),
    ("microservices", "microservices"),
    ("api rest", "api rest"),
    ("rest", "rest"),
    ("security", "security"),
)

INDUSTRY_PATTERNS = (
    (("bank", "banque", "finance", "paiement", "payment"), "banking"),
    (("insurance", "assurance"), "insurance"),
    (("security", "cyber", "iam", "identity"), "security"),
    (("retail", "e-commerce", "ecommerce"), "retail"),
)

TOP_METADATA_SKIP_TOKENS = (
    "freelance",
    "cdi",
    "postuler",
    "partager cette offre",
    "des que possible",
    "teletravail",
    "experience",
    "mois",
    "semaine",
    "jour",
    "reference de l offre",
    "publiee le",
    "publie le",
    "mission freelance",
)

SUMMARY_STOP_TOKENS = (
    "profil recherche",
    "environnement de travail",
    "postuler",
    "trouvez votre prochaine mission",
    "creer un compte",
    "se connecter",
)


@dataclass(frozen=True, slots=True)
class ScrapedOpportunityRecord:
    url: str
    opportunity: Opportunity


class FreeWorkScraper(OpportunityScraper):
    platform = "free-work"
    session = PlatformSession(
        platform=platform,
        base_url=FREEWORK_BASE_URL,
        login_required=False,
    )

    def __init__(
        self,
        *,
        search_url: str = DEFAULT_SEARCH_URL,
        user_data_dir: str | Path = "data/playwright/freework",
        headless: bool = True,
        slow_mo: int = 0,
        timeout_ms: int = 30_000,
    ) -> None:
        self.search_url = search_url
        self.user_data_dir = Path(user_data_dir)
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout_ms = timeout_ms

    async def fetch_new_opportunities(self, limit: int = 5) -> list[Opportunity]:
        records = await self.fetch_new_opportunity_records(limit=limit)
        return [record.opportunity for record in records]

    async def fetch_new_opportunity_records(self, limit: int = 5) -> list[ScrapedOpportunityRecord]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. Run `make bootstrap` or `make playwright-install` first."
            )

        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as playwright:
            try:
                context = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.user_data_dir),
                    headless=self.headless,
                    slow_mo=self.slow_mo,
                    locale="fr-FR",
                    viewport={"width": 1440, "height": 1200},
                )
            except Exception as exc:
                raise _rewrite_launch_error(exc) from exc
            context.set_default_timeout(self.timeout_ms)

            try:
                list_page = context.pages[0] if context.pages else await context.new_page()
                urls = await self._discover_mission_urls(list_page, limit=limit)
                detail_page = await context.new_page()

                records: list[ScrapedOpportunityRecord] = []
                for url in urls:
                    opportunity = await self._scrape_mission_detail(detail_page, url)
                    records.append(ScrapedOpportunityRecord(url=url, opportunity=opportunity))
                return records
            finally:
                await context.close()

    async def _discover_mission_urls(self, page: Page, *, limit: int) -> list[str]:
        await page.goto(self.search_url, wait_until="domcontentloaded")
        await _dismiss_cookie_banner(page)

        try:
            await page.locator(MISSION_LINK_SELECTOR).first.wait_for(
                state="attached",
                timeout=10_000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "Free-Work mission links were not found. "
                "Run with --headful to inspect the page or update the selectors."
            ) from exc

        link_locator = page.locator(MISSION_LINK_SELECTOR)
        link_count = await link_locator.count()
        urls: list[str] = []
        seen: set[str] = set()

        for index in range(link_count):
            href = await link_locator.nth(index).get_attribute("href")
            if not href:
                continue

            url = urljoin(FREEWORK_BASE_URL, href)
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)
            if len(urls) >= limit:
                break

        if not urls:
            raise RuntimeError(
                "Free-Work mission links were not extracted from the listing page. "
                "The listing markup likely changed."
            )

        return urls

    async def _scrape_mission_detail(self, page: Page, url: str) -> Opportunity:
        await page.goto(url, wait_until="domcontentloaded")
        await _dismiss_cookie_banner(page)
        await page.locator("h1").first.wait_for(state="visible", timeout=10_000)

        title = (await _safe_text(page.locator("h1").first)) or _title_from_url(url)
        raw_text = await page.locator("body").inner_text()
        lines = _clean_lines(raw_text)
        normalized_text = _normalize_text(raw_text)

        location, client = _extract_top_metadata(lines, title)
        remote_mode = _extract_remote_mode(normalized_text)
        remote_days = _extract_remote_days(normalized_text)

        if remote_mode == RemoteMode.REMOTE and remote_days is None:
            remote_days = 5

        return Opportunity(
            platform=self.platform,
            external_id=_extract_external_id(url, normalized_text),
            title=title,
            client=client,
            location=location,
            daily_rate_eur=_extract_daily_rate(raw_text),
            remote_mode=remote_mode,
            remote_days_per_week=remote_days,
            summary=_extract_summary(lines, title),
            keywords=_extract_keywords(normalized_text),
            industry=_extract_industry(normalized_text),
        )


async def _dismiss_cookie_banner(page: Page) -> None:
    for selector in COOKIE_ACCEPT_SELECTORS:
        button = page.locator(selector).first
        try:
            await button.wait_for(state="visible", timeout=1_000)
        except PlaywrightTimeoutError:
            continue

        await button.click()
        return


async def _safe_text(locator) -> str | None:
    text = await locator.text_content()
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _clean_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _normalize_text(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).lower().strip()


def _extract_top_metadata(lines: list[str], title: str) -> tuple[str | None, str | None]:
    start_index = 0
    title_lower = title.lower()

    for index, line in enumerate(lines):
        if title_lower in line.lower():
            start_index = index
            break

    candidates: list[str] = []
    keyword_labels = {label for _, label in KEYWORD_PATTERNS}
    for line in lines[start_index + 1 : start_index + 12]:
        normalized_line = _normalize_text(line)
        if not normalized_line:
            continue
        if any(token in normalized_line for token in TOP_METADATA_SKIP_TOKENS):
            continue
        if len(line) > 80:
            continue
        if line.isupper():
            continue
        if normalized_line in keyword_labels:
            continue
        candidates.append(line)

    location = candidates[0] if candidates else None
    client = candidates[1] if len(candidates) > 1 else None
    return location, client


def _extract_daily_rate(text: str) -> int | None:
    range_match = re.search(
        r"(\d{2,4})\s*(?:-|a|\u00e0|to)\s*(\d{2,4})\s*(?:\u20ac|eur)\s*(?:/|\u2044)\s*j",
        text.lower(),
    )
    if range_match:
        return int(range_match.group(1))

    single_match = re.search(
        r"(\d{2,4})\s*(?:\u20ac|eur)\s*(?:/|\u2044)\s*j",
        text.lower(),
    )
    if single_match:
        return int(single_match.group(1))

    return None


def _extract_remote_mode(normalized_text: str) -> RemoteMode:
    if any(token in normalized_text for token in ("100% remote", "full remote")):
        return RemoteMode.REMOTE
    if "teletravail partiel" in normalized_text or re.search(
        r"\b[1-5]\s+jours?\s+remote\b",
        normalized_text,
    ):
        return RemoteMode.HYBRID
    if any(token in normalized_text for token in ("onsite", "sur site", "presentiel")):
        return RemoteMode.ONSITE
    return RemoteMode.HYBRID


def _extract_remote_days(normalized_text: str) -> int | None:
    match = re.search(r"\b([1-5])\s+jours?\s+remote\b", normalized_text)
    if match:
        return int(match.group(1))

    match = re.search(r"\b([1-5])\s+jours?\s+de\s+teletravail\b", normalized_text)
    if match:
        return int(match.group(1))

    if "100% remote" in normalized_text or "full remote" in normalized_text:
        return 5

    return None


def _extract_keywords(normalized_text: str) -> tuple[str, ...]:
    keywords: list[str] = []
    for needle, label in KEYWORD_PATTERNS:
        if needle in normalized_text and label not in keywords:
            keywords.append(label)
    return tuple(keywords[:12])


def _extract_industry(normalized_text: str) -> str | None:
    for needles, label in INDUSTRY_PATTERNS:
        if any(needle in normalized_text for needle in needles):
            return label
    return None


def _extract_summary(lines: list[str], title: str) -> str:
    start_index = 0
    title_lower = title.lower()

    for index, line in enumerate(lines):
        if title_lower in line.lower():
            start_index = index
            break

    summary_lines: list[str] = []
    for line in lines[start_index + 1 :]:
        normalized_line = _normalize_text(line)
        if any(token in normalized_line for token in SUMMARY_STOP_TOKENS) and summary_lines:
            break
        if any(token in normalized_line for token in TOP_METADATA_SKIP_TOKENS):
            continue
        if len(line) < 30:
            continue
        summary_lines.append(line)
        if sum(len(item) for item in summary_lines) >= 900:
            break

    return " ".join(summary_lines)[:900]


def _extract_external_id(url: str, normalized_text: str) -> str:
    reference_text = normalized_text.replace("'", " ")
    reference_match = re.search(r"reference de l offre\s*:\s*([a-z0-9-]+)", reference_text)
    if reference_match:
        return reference_match.group(1)

    slug = Path(urlparse(url).path).name
    return slug or "free-work-unknown"


def _title_from_url(url: str) -> str:
    slug = Path(urlparse(url).path).name
    if not slug:
        return "Free-Work mission"
    return slug.replace("-", " ").strip().title()


def _rewrite_launch_error(exc: Exception) -> Exception:
    message = str(exc)
    if "Executable doesn't exist" not in message and "playwright install" not in message:
        return exc

    return RuntimeError(
        "Playwright Chromium is not installed for the current Python interpreter.\n"
        f"Interpreter: {sys.executable}\n"
        "Install it with:\n"
        f"  {sys.executable} -m playwright install chromium\n"
        "Or use the repo-managed flow:\n"
        "  make bootstrap\n"
        '  make freework-smoke ARGS="--headful --limit 5"'
    )


def _record_to_dict(record: ScrapedOpportunityRecord) -> dict[str, object]:
    opportunity = record.opportunity
    return {
        "url": record.url,
        "platform": opportunity.platform,
        "external_id": opportunity.external_id,
        "title": opportunity.title,
        "client": opportunity.client,
        "location": opportunity.location,
        "daily_rate_eur": opportunity.daily_rate_eur,
        "remote_mode": opportunity.remote_mode.value,
        "remote_days_per_week": opportunity.remote_days_per_week,
        "summary": opportunity.summary,
        "keywords": list(opportunity.keywords),
        "industry": opportunity.industry,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small Playwright smoke scraper against Free-Work mission pages.",
    )
    parser.add_argument("--limit", type=int, default=3, help="Number of mission pages to inspect.")
    parser.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_URL,
        help="Free-Work listing URL to scan for mission links.",
    )
    parser.add_argument(
        "--user-data-dir",
        default="data/playwright/freework",
        help="Directory used by Playwright to persist Free-Work cookies and local storage.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Launch Chromium with a visible window for cookie/login troubleshooting.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Delay in milliseconds between browser actions.",
    )
    return parser


async def _run_cli() -> int:
    args = _build_parser().parse_args()
    scraper = FreeWorkScraper(
        search_url=args.search_url,
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        slow_mo=args.slow_mo,
    )
    records = await scraper.fetch_new_opportunity_records(limit=args.limit)
    print(json.dumps([_record_to_dict(record) for record in records], indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run_cli()))


if __name__ == "__main__":
    main()
