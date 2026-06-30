from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from openclaw.core.config import get_settings
from openclaw.db.repository import get_opportunity_by_external_id, upsert_opportunity
from openclaw.db.session import get_session
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.scrapers.base import OpportunityScraper, PlatformSession
from openclaw.services.filtering import FilteringRules
from openclaw.workflows.qualification import qualification_packet_to_dict, qualify_opportunity

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:
    PlaywrightTimeoutError = TimeoutError
    async_playwright = None

try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

if TYPE_CHECKING:
    from playwright.async_api import Page
else:
    Page = Any

LEHIBOU_BASE_URL = "https://www.lehibou.com"
DEFAULT_SEARCH_URL = "https://www.lehibou.com/recherche/annonces"
MISSION_LINK_SELECTOR = "a[href*='/annonce/']"
COOKIE_ACCEPT_SELECTOR = "button[data-cky-tag='accept-button']"

FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
}

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

DETAIL_STOP_TOKENS = (
    "s'inscrire",
    "se connecter",
    "nos nids",
    "politique des cookies",
    "conditions generales",
)


@dataclass(frozen=True, slots=True)
class ScrapedOpportunityRecord:
    url: str
    opportunity: Opportunity


class LeHibouScraper(OpportunityScraper):
    platform = "lehibou"
    session = PlatformSession(
        platform=platform,
        base_url=LEHIBOU_BASE_URL,
        login_required=False,
    )

    def __init__(
        self,
        *,
        search_url: str = DEFAULT_SEARCH_URL,
        user_data_dir: str | Path = "data/playwright/lehibou",
        headless: bool = False,
        slow_mo: int = 0,
        timeout_ms: int = 30_000,
    ) -> None:
        self.search_url = search_url
        self.user_data_dir = Path(user_data_dir)
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout_ms = timeout_ms

    async def fetch_new_opportunities(self) -> list[Opportunity]:
        records = await self.fetch_new_opportunity_records()
        return [record.opportunity for record in records]

    async def fetch_new_opportunity_records(self) -> list[ScrapedOpportunityRecord]:
        if async_playwright is None:
            raise RuntimeError(
                "Playwright is not installed. "
                "Run `make bootstrap` or `make playwright-install` first."
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
                    **_stealth_launch_args(),
                )
            except Exception as exc:
                raise _rewrite_launch_error(exc) from exc
            context.set_default_timeout(self.timeout_ms)

            try:
                list_page = context.pages[0] if context.pages else await context.new_page()
                await _apply_stealth(list_page)
                urls = await self._discover_mission_urls(list_page)
                detail_page = await context.new_page()
                await _apply_stealth(detail_page)

                records: list[ScrapedOpportunityRecord] = []
                for url in urls:
                    opportunity = await self._scrape_mission_detail(detail_page, url)
                    records.append(ScrapedOpportunityRecord(url=url, opportunity=opportunity))
                return records
            finally:
                await context.close()

    async def _discover_mission_urls(self, page: Page) -> list[str]:
        # LeHibou is a Vue/Nuxt SPA. Use domcontentloaded then explicitly wait for
        # mission cards — networkidle never fires because the SPA keeps polling analytics.
        await page.goto(self.search_url, wait_until="domcontentloaded")
        await _dismiss_cookie_banner(page)

        try:
            await page.locator(MISSION_LINK_SELECTOR).first.wait_for(
                state="attached",
                timeout=20_000,
            )
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(
                "LeHibou mission links were not found. "
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

            # Normalise to base URL without query params
            parsed = urlparse(href)
            if not parsed.path.startswith("/annonce/"):
                continue
            url = f"{LEHIBOU_BASE_URL}{parsed.path}"
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

        if not urls:
            raise RuntimeError(
                "LeHibou mission links were not extracted from the listing page. "
                "The listing markup likely changed."
            )

        return urls

    async def _scrape_mission_detail(self, page: Page, url: str) -> Opportunity:
        await page.goto(url, wait_until="domcontentloaded")
        await _dismiss_cookie_banner(page)
        # Detail pages have no h1 — wait for the metadata block which is always present
        await page.locator(".annonce-main-information__section").first.wait_for(
            state="attached", timeout=20_000
        )

        raw_text = await page.locator("body").inner_text()
        normalized_text = _normalize_text(raw_text)
        lines = _clean_lines(raw_text)

        title = _extract_title(lines) or _title_from_url(url)
        external_id = _extract_external_id(url)
        published_at = _extract_published_at(normalized_text)
        daily_rate_eur = _extract_daily_rate(normalized_text)
        remote_mode, remote_days = _extract_remote(normalized_text)
        location = _extract_location(normalized_text)
        keywords = _extract_keywords(normalized_text, lines)
        industry = _extract_industry(normalized_text)
        summary = _extract_summary(lines)

        return Opportunity(
            platform=self.platform,
            external_id=external_id,
            title=title,
            published_at=published_at,
            client=None,
            location=location,
            daily_rate_eur=daily_rate_eur,
            remote_mode=remote_mode,
            remote_days_per_week=remote_days,
            summary=summary,
            keywords=keywords,
            industry=industry,
        )


def _stealth_launch_args() -> dict:
    """Browser args that suppress the most common Playwright/automation detection signals."""
    return {
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
        "ignore_default_args": ["--enable-automation"],
    }


async def _apply_stealth(page: Page) -> None:
    if stealth_async is not None:
        await stealth_async(page)


async def _dismiss_cookie_banner(page: Page) -> None:
    button = page.locator(COOKIE_ACCEPT_SELECTOR).first
    try:
        await button.wait_for(state="visible", timeout=2_000)
    except PlaywrightTimeoutError:
        return
    await button.click()


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


def _extract_title(lines: list[str]) -> str | None:
    # The title is the line immediately before "Mission LeHibou" in the page text
    for i, line in enumerate(lines):
        if _normalize_text(line).startswith("mission lehibou") and i > 0:
            candidate = lines[i - 1].strip()
            if len(candidate) > 5:
                return candidate
    return None


def _extract_external_id(url: str) -> str:
    path = urlparse(url).path
    return Path(path).name or "lehibou-unknown"


def _extract_published_at(normalized_text: str) -> date | None:
    match = re.search(
        r"publi[ée]e?\s+le\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})",
        normalized_text,
    )
    if match is None:
        return None
    day, month_name, year = match.group(1), match.group(2), match.group(3)
    month = FRENCH_MONTHS.get(month_name)
    if month is None:
        return None
    try:
        return datetime(int(year), month, int(day)).date()
    except ValueError:
        return None


def _extract_daily_rate(normalized_text: str) -> int | None:
    # normalized_text is ASCII-only — € (U+20AC) is stripped, leaving "600 /jour"
    match = re.search(r"(\d{3,4})\s*(?:[€e])?\s*/\s*jour", normalized_text)
    if match:
        return int(match.group(1))
    return None


def _extract_remote(normalized_text: str) -> tuple[RemoteMode, int | None]:
    # Find the value after "teletravail" label in the metadata table
    match = re.search(r"teletravail\s+([^\n]+?)(?:\s+debut|\s+domaine|$)", normalized_text)
    value = match.group(1).strip() if match else ""

    if "100%" in value or "full remote" in value:
        return RemoteMode.REMOTE, 5
    if "non" == value or value.startswith("non "):
        return RemoteMode.ONSITE, None

    # "possible" or any percentage other than 100% → hybrid
    pct_match = re.search(r"(\d{1,2})%", value)
    if pct_match:
        pct = int(pct_match.group(1))
        # approximate: 50% ~ 2-3 days, we use floor(5 * pct / 100)
        days = max(1, round(5 * pct / 100))
        return RemoteMode.HYBRID, days

    return RemoteMode.HYBRID, None


def _extract_location(normalized_text: str) -> str | None:
    pattern = r"\blieu\b\s+([a-z][a-z\s\-]+?)(?:\s+teletravail|\s+debut|$)"
    match = re.search(pattern, normalized_text)
    if match:
        loc = match.group(1).strip().title()
        return loc if len(loc) < 60 else None
    return None


def _extract_keywords(normalized_text: str, lines: list[str]) -> tuple[str, ...]:
    # First pass: match against skill lines in the structured "Domaine" block
    in_domain_block = False
    skill_lines: list[str] = []
    for line in lines:
        nl = _normalize_text(line)
        if "domaine" in nl and "metier" in nl:
            in_domain_block = True
            continue
        if in_domain_block:
            if "description de la mission" in nl:
                break
            if line and len(line) < 80:
                skill_lines.append(nl)

    domain_blob = " ".join(skill_lines)
    full_blob = normalized_text

    keywords: list[str] = []
    for needle, label in KEYWORD_PATTERNS:
        if (needle in domain_blob or needle in full_blob) and label not in keywords:
            keywords.append(label)

    return tuple(keywords[:12])


def _extract_industry(normalized_text: str) -> str | None:
    for needles, label in INDUSTRY_PATTERNS:
        if any(needle in normalized_text for needle in needles):
            return label
    return None


def _extract_summary(lines: list[str]) -> str:
    in_description = False
    summary_lines: list[str] = []

    for line in lines:
        nl = _normalize_text(line)
        if "description de la mission" in nl:
            in_description = True
            continue
        if not in_description:
            continue
        if any(token in nl for token in DETAIL_STOP_TOKENS):
            break
        if len(line) < 20:
            continue
        summary_lines.append(line)
        if sum(len(item) for item in summary_lines) >= 900:
            break

    return " ".join(summary_lines)[:900]


def _title_from_url(url: str) -> str:
    slug = Path(urlparse(url).path).name
    return slug or "LeHibou mission"


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
        '  make lehibou-smoke ARGS="--headful"'
    )


def _record_to_dict(record: ScrapedOpportunityRecord) -> dict[str, object]:
    opportunity = record.opportunity
    return {
        "url": record.url,
        "platform": opportunity.platform,
        "external_id": opportunity.external_id,
        "title": opportunity.title,
        "published_at": opportunity.published_at.isoformat() if opportunity.published_at else None,
        "client": opportunity.client,
        "location": opportunity.location,
        "daily_rate_eur": opportunity.daily_rate_eur,
        "duration_months": opportunity.duration_months,
        "required_experience_years": opportunity.required_experience_years,
        "remote_mode": opportunity.remote_mode.value,
        "remote_days_per_week": opportunity.remote_days_per_week,
        "summary": opportunity.summary,
        "keywords": list(opportunity.keywords),
        "industry": opportunity.industry,
    }


def _qualify_records(
    records: list[ScrapedOpportunityRecord],
    *,
    rules: FilteringRules,
    include_rejected: bool = False,
) -> list[dict[str, object]]:
    qualified_records: list[dict[str, object]] = []
    for record in records:
        packet = qualify_opportunity(record.opportunity, rules=rules)
        if packet.filtering_result.rejected and not include_rejected:
            continue
        payload = _record_to_dict(record)
        payload.update(qualification_packet_to_dict(packet))
        qualified_records.append(payload)
    return qualified_records


def _filter_records_from_date(
    records: list[ScrapedOpportunityRecord],
    *,
    from_date: date | None,
) -> list[ScrapedOpportunityRecord]:
    if from_date is None:
        return records
    return [
        record
        for record in records
        if (
            record.opportunity.published_at is not None
            and record.opportunity.published_at >= from_date
        )
    ]


def _parse_from_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid --from-date value {value!r}. Expected YYYY-MM-DD."
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Playwright scraper against LeHibou mission pages.",
    )
    parser.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_URL,
        help="LeHibou listing URL (default: %(default)s).",
    )
    parser.add_argument(
        "--user-data-dir",
        default="data/playwright/lehibou",
        help="Directory used by Playwright to persist LeHibou cookies and local storage.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Launch Chromium with a visible window for troubleshooting.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=0,
        help="Delay in milliseconds between browser actions.",
    )
    parser.add_argument(
        "--from-date",
        type=_parse_from_date,
        help="Only keep missions published on or after this ISO date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--include-rejected",
        action="store_true",
        help="Include missions rejected by the job criteria in the JSON output.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help=(
            "Open the browser and pause so you can solve the Cloudflare challenge manually. "
            "The clearance cookie is saved to the persistent profile so future runs are headless. "
            "Implies --headful."
        ),
    )
    return parser


async def _run_setup(*, search_url: str, user_data_dir: str) -> int:
    """Open the search page in a visible browser and wait for the user to pass the challenge."""
    if async_playwright is None:
        raise RuntimeError("Playwright is not installed. Run `make bootstrap` first.")

    profile = Path(user_data_dir)
    profile.mkdir(parents=True, exist_ok=True)

    print(f"Opening {search_url} ...")
    print("Solve the Cloudflare challenge in the browser window, then press Enter here to save and exit.")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=False,
            locale="fr-FR",
            viewport={"width": 1440, "height": 1200},
            **_stealth_launch_args(),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await _apply_stealth(page)
        await page.goto(search_url, wait_until="domcontentloaded")

        # Block here until the user presses Enter
        await asyncio.get_event_loop().run_in_executor(None, input)

        await context.close()

    print("Profile saved. You can now run without --setup.")
    return 0


async def _run_cli() -> int:
    args = _build_parser().parse_args()
    settings = get_settings()

    if args.setup:
        return await _run_setup(
            search_url=args.search_url,
            user_data_dir=args.user_data_dir,
        )

    if LeHibouScraper.platform not in settings.platform_targets:
        print("[]")
        return 0

    scraper = LeHibouScraper(
        search_url=args.search_url,
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        slow_mo=args.slow_mo,
    )
    records = await scraper.fetch_new_opportunity_records()
    records = _filter_records_from_date(records, from_date=args.from_date)
    rules = FilteringRules.from_settings(settings)

    for record in records:
        packet = qualify_opportunity(record.opportunity, rules=rules)
        with get_session() as session:
            existing = get_opportunity_by_external_id(
                session, record.opportunity.platform, record.opportunity.external_id
            )
            if existing is not None and existing.status != "new":
                continue
            upsert_opportunity(session, record.opportunity, packet.filtering_result)

    qualified_records = _qualify_records(
        records,
        rules=rules,
        include_rejected=args.include_rejected,
    )
    print(json.dumps(qualified_records, indent=2, ensure_ascii=False))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_run_cli()))


if __name__ == "__main__":
    main()
