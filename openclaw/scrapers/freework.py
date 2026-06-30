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
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse

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

if TYPE_CHECKING:
    from playwright.async_api import Page
else:
    Page = Any

FREEWORK_BASE_URL = "https://www.free-work.com"
FREEWORK_SEARCH_LOCATION = "fr~~~"
DEFAULT_SEARCH_URL = (
    f"{FREEWORK_BASE_URL}/fr/tech-it/jobs?locations={FREEWORK_SEARCH_LOCATION}&query=java"
)
MISSION_LINK_SELECTOR = "h2 a[href*='/job-mission/']"

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
        employment_types: list[str] | tuple[str, ...] = ("freelance",),
        minimum_tjm: int = 650,
        unspecified_tjm: bool = True,
        minimum_duration_months: int = 0,
        minimum_year_salary: int = 90_000,
        allowed_remote_modes: list[RemoteMode] | tuple[RemoteMode, ...] = (
            RemoteMode.REMOTE,
            RemoteMode.HYBRID,
        ),
    ) -> None:
        self.search_url = search_url
        self.user_data_dir = Path(user_data_dir)
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout_ms = timeout_ms
        self.employment_types = _normalize_employment_types(employment_types)
        self.minimum_tjm = minimum_tjm
        self.unspecified_tjm = unspecified_tjm
        self.minimum_duration_months = minimum_duration_months
        self.minimum_year_salary = minimum_year_salary
        self.allowed_remote_modes = _normalize_allowed_remote_modes(allowed_remote_modes)

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
                )
            except Exception as exc:
                raise _rewrite_launch_error(exc) from exc
            context.set_default_timeout(self.timeout_ms)

            try:
                list_page = await context.new_page()
                card_experience_map: dict[str, int | None] = {}
                urls = await self._discover_mission_urls(list_page, card_experience_map=card_experience_map)
                if not urls:
                    return []

                detail_page = await context.new_page()

                records: list[ScrapedOpportunityRecord] = []
                for url in urls:
                    opportunity = await self._scrape_mission_detail(detail_page, url, card_experience_map=card_experience_map)
                    if opportunity.remote_mode not in self.allowed_remote_modes:
                        continue
                    records.append(ScrapedOpportunityRecord(url=url, opportunity=opportunity))
                return records
            finally:
                await context.close()

    async def _discover_mission_urls(
        self,
        page: Page,
        *,
        card_experience_map: dict[str, int | None] | None = None,
    ) -> list[str]:
        await page.goto(self.search_url, wait_until="domcontentloaded")
        if _is_blank_page_url(page.url):
            return []

        await _dismiss_cookie_banner(page)
        if not await self._wait_for_mission_links(page):
            if await _page_indicates_no_results(page):
                return []
            raise RuntimeError(
                "Free-Work mission links were not found. "
                "Run with --headful to inspect the page or update the selectors."
            )

        urls: list[str] = []
        seen: set[str] = set()
        await self._collect_mission_urls(page, urls=urls, seen=seen, card_experience_map=card_experience_map)

        page_count = await _extract_last_pagination_page(page)
        page_url = page.url
        for page_number in range(2, page_count + 1):
            await page.goto(_url_with_page(page_url, page_number), wait_until="domcontentloaded")
            if not await self._wait_for_mission_links(page):
                continue
            await self._collect_mission_urls(page, urls=urls, seen=seen, card_experience_map=card_experience_map)

        if not urls:
            if await _page_indicates_no_results(page):
                return []
            raise RuntimeError(
                "Free-Work mission links were not extracted from the listing page. "
                "The listing markup likely changed."
            )

        return urls

    async def _wait_for_mission_links(self, page: Page) -> bool:
        try:
            await page.locator(MISSION_LINK_SELECTOR).first.wait_for(
                state="attached",
                timeout=10_000,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    async def _collect_mission_urls(
        self,
        page: Page,
        *,
        urls: list[str],
        seen: set[str],
        card_experience_map: dict[str, int | None] | None = None,
    ) -> None:
        link_locator = page.locator(MISSION_LINK_SELECTOR)
        link_count = await link_locator.count()

        for index in range(link_count):
            link = link_locator.nth(index)
            card = await _card_for_mission_link(link)
            if not await _card_matches_listing_criteria(
                card,
                employment_types=self.employment_types,
                minimum_tjm=self.minimum_tjm,
                unspecified_tjm=self.unspecified_tjm,
                minimum_duration_months=self.minimum_duration_months,
                minimum_year_salary=self.minimum_year_salary,
                allowed_remote_modes=self.allowed_remote_modes,
            ):
                continue

            href = await link.get_attribute("href")
            if not href:
                continue

            url = urljoin(FREEWORK_BASE_URL, href)
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

            if card_experience_map is not None:
                card_text = await card.inner_text()
                card_experience_map[url] = _extract_card_required_experience_years(card_text)

    async def _scrape_mission_detail(
        self,
        page: Page,
        url: str,
        *,
        card_experience_map: dict[str, int | None] | None = None,
    ) -> Opportunity:
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
        published_at = _extract_published_at(normalized_text)

        if remote_mode == RemoteMode.REMOTE and remote_days is None:
            remote_days = 5

        # Try to extract experience from detail page first, fall back to card value
        required_experience_years = _extract_required_experience_years(raw_text)
        if required_experience_years is None and card_experience_map is not None:
            required_experience_years = card_experience_map.get(url)

        return Opportunity(
            platform=self.platform,
            external_id=_extract_external_id(url, normalized_text),
            title=title,
            published_at=published_at,
            client=client,
            location=location,
            daily_rate_eur=_extract_daily_rate(raw_text),
            duration_months=_extract_duration_months(raw_text),
            required_experience_years=required_experience_years,
            remote_mode=remote_mode,
            remote_days_per_week=remote_days,
            summary=_extract_summary(lines, title),
            keywords=_extract_keywords(normalized_text),
            industry=_extract_industry(normalized_text),
            source_url=url,
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


def _is_blank_page_url(url: str) -> bool:
    return url == "about:blank"


async def _page_indicates_no_results(page: Page) -> bool:
    if _is_blank_page_url(page.url):
        return True

    try:
        body_text = await page.locator("body").inner_text(timeout=1_000)
    except Exception:
        return False

    return _listing_body_indicates_no_results(body_text)


def _listing_body_indicates_no_results(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False

    no_result_markers = (
        "aucune offre",
        "aucun resultat",
        "aucune mission",
        "0 offre",
        "0 mission",
        "no result",
        "no jobs",
    )
    return any(marker in normalized for marker in no_result_markers)


async def _card_for_mission_link(link):
    full_card = link.locator(
        "xpath=ancestor::div[contains(@class, 'mb-4') and contains(@class, 'relative')][1]"
    )
    if await full_card.count():
        return full_card.first

    inner_card = link.locator("xpath=ancestor::div[contains(@class, 'p-4')][1]")
    if await inner_card.count():
        return inner_card.first

    return link


async def _card_matches_listing_criteria(
    card,
    *,
    employment_types: tuple[str, ...],
    minimum_tjm: int,
    unspecified_tjm: bool,
    minimum_duration_months: int,
    minimum_year_salary: int,
    allowed_remote_modes: tuple[RemoteMode, ...],
) -> bool:
    return _card_text_matches_listing_criteria(
        await card.inner_text(),
        employment_types=employment_types,
        minimum_tjm=minimum_tjm,
        unspecified_tjm=unspecified_tjm,
        minimum_duration_months=minimum_duration_months,
        minimum_year_salary=minimum_year_salary,
        allowed_remote_modes=allowed_remote_modes,
    )


def _card_text_matches_listing_criteria(
    text: str,
    *,
    employment_types: tuple[str, ...],
    minimum_tjm: int,
    unspecified_tjm: bool,
    minimum_duration_months: int,
    minimum_year_salary: int,
    allowed_remote_modes: tuple[RemoteMode, ...] = (RemoteMode.REMOTE, RemoteMode.HYBRID),
) -> bool:
    allowed_employment_types = set(employment_types)
    card_employment_types = _extract_card_employment_types(text)
    if not card_employment_types.intersection(allowed_employment_types):
        return False

    card_remote_mode = _extract_remote_mode(_normalize_text(text))
    if card_remote_mode not in allowed_remote_modes:
        return False

    if "freelance" in allowed_employment_types and "freelance" in card_employment_types:
        duration_months = _extract_card_duration_months(text)
        if minimum_duration_months > 0 and (
            duration_months is None or duration_months < minimum_duration_months
        ):
            return False

        daily_rate = _extract_card_daily_rate(text)
        if daily_rate is None:
            return unspecified_tjm
        if daily_rate is not None and daily_rate >= minimum_tjm:
            return True

    salaried_types = {"cdi", "cdd"}
    if allowed_employment_types.intersection(salaried_types) and card_employment_types.intersection(
        salaried_types
    ):
        annual_salary = _extract_card_annual_salary(text)
        if annual_salary is not None and annual_salary >= minimum_year_salary:
            return True

    return False


def _normalize_employment_types(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        item = _normalize_text(value).replace("-", " ").strip()
        if item in {"freelance", "contractor", "mission"}:
            normalized.append("freelance")
        elif item in {"cdi", "permanent"}:
            normalized.append("cdi")
        elif item in {"cdd", "fixed term", "fixed term contract"}:
            normalized.append("cdd")
    return tuple(dict.fromkeys(normalized)) or ("freelance",)


def _normalize_allowed_remote_modes(
    values: list[RemoteMode] | tuple[RemoteMode, ...],
) -> tuple[RemoteMode, ...]:
    return tuple(dict.fromkeys(values)) or (RemoteMode.REMOTE, RemoteMode.HYBRID)


def _extract_card_employment_types(text: str) -> set[str]:
    normalized = _normalize_text(text)
    found: set[str] = set()
    if re.search(r"\bfreelance\b", normalized):
        found.add("freelance")
    if re.search(r"\bcdi\b", normalized):
        found.add("cdi")
    if re.search(r"\bcdd\b", normalized):
        found.add("cdd")
    return found


def _extract_card_daily_rate(text: str) -> int | None:
    normalized = _normalize_card_pay_text(text)
    match = re.search(
        r"\b(\d{2,4})(?:\s*[-–]\s*(\d{2,4}))?\s*(?:€|eur|euro)\s*(?:/|par)?\s*j",
        normalized,
    )
    if not match:
        return None
    return int(match.group(1))


def _extract_card_annual_salary(text: str) -> int | None:
    normalized = _normalize_card_pay_text(text)
    match = re.search(
        r"\b(\d{2,3})\s*k(?:\s*[-–]\s*(\d{2,3})\s*k?)?\s*(?:€|eur|euro)?\s*(?:/|par)?\s*an",
        normalized,
    )
    if not match:
        return None
    return int(match.group(1)) * 1000


def _extract_card_duration_months(text: str) -> int | None:
    normalized = _normalize_card_pay_text(text)
    month_match = re.search(r"\b(\d{1,2})\s*mois\b", normalized)
    if month_match:
        return int(month_match.group(1))

    year_match = re.search(r"\b(\d{1,2})\s*ans?\b", normalized)
    if year_match:
        return int(year_match.group(1)) * 12

    return None


def _extract_card_required_experience_years(text: str) -> int | None:
    """Extract required experience years from a listing card's inner text."""
    raw_normalized = _normalize_card_pay_text(text)
    # Pattern for "X à Y ans d'expérience" (range) – take the lower bound
    range_match = re.search(
        r"(\d{1,2})\s*[àa]\s*\d{1,2}\s*ans?\s*d['’]?exp[eé]rience",
        raw_normalized,
        re.IGNORECASE,
    )
    if range_match:
        return int(range_match.group(1))

    # Pattern for "X ans d'expérience" (single value)
    single_match = re.search(
        r"(\d{1,2})\s*ans?\s*d['’]?exp[eé]rience",
        raw_normalized,
        re.IGNORECASE,
    )
    if single_match:
        return int(single_match.group(1))

    # Fallback to ASCII-normalized text for other patterns
    normalized = _normalize_text(raw_normalized)
    match = re.search(
        r"(?:>|>=|plus de|minimum|min\.?|au moins)?\s*(\d{1,2})\s*ans?.{0,8}experience",
        normalized,
    )
    if match:
        return int(match.group(1))

    match = re.search(
        r"experience\s*:?\s*(?:>|>=|plus de|minimum|min\.?|au moins)?\s*(\d{1,2})\s*ans?",
        normalized,
    )
    if match:
        return int(match.group(1))

    return None


def _extract_duration_months(text: str) -> int | None:
    return _extract_card_duration_months(text)


def _extract_required_experience_years(text: str) -> int | None:
    # Try to match on the raw text first (before ASCII normalization)
    # to preserve accented characters and the "à" range separator.
    raw_normalized = _normalize_card_pay_text(text)
    # Pattern for "X à Y ans d'expérience" (range) – take the lower bound
    range_match = re.search(
        r"(\d{1,2})\s*[àa]\s*\d{1,2}\s*ans?\s*d['’]?exp[eé]rience",
        raw_normalized,
        re.IGNORECASE,
    )
    if range_match:
        return int(range_match.group(1))

    # Pattern for "X ans d'expérience" (single value)
    single_match = re.search(
        r"(\d{1,2})\s*ans?\s*d['’]?exp[eé]rience",
        raw_normalized,
        re.IGNORECASE,
    )
    if single_match:
        return int(single_match.group(1))

    # Fallback to ASCII-normalized text for other patterns
    normalized = _normalize_text(raw_normalized)
    match = re.search(
        r"(?:>|>=|plus de|minimum|min\.?|au moins)?\s*(\d{1,2})\s*ans?.{0,8}experience",
        normalized,
    )
    if match:
        return int(match.group(1))

    match = re.search(
        r"experience\s*:?\s*(?:>|>=|plus de|minimum|min\.?|au moins)?\s*(\d{1,2})\s*ans?",
        normalized,
    )
    if match:
        return int(match.group(1))

    return None


def _normalize_card_pay_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\xa0", " ").replace("⁄", "/").replace("’", "'")
    return re.sub(r"\s+", " ", normalized).lower().strip()


async def _extract_last_pagination_page(page: Page) -> int:
    page_buttons = page.locator("button[data-page]")
    button_count = await page_buttons.count()
    page_numbers: list[int] = []

    for index in range(button_count):
        value = await page_buttons.nth(index).get_attribute("data-page")
        if value is None or not value.isdigit():
            continue
        page_numbers.append(int(value))

    return max(page_numbers, default=1)


def _url_with_page(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "page"
    ]
    query_items.append(("page", str(page_number)))
    return urlunparse(parsed._replace(query=urlencode(query_items)))


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


def _extract_published_at(normalized_text: str) -> date | None:
    match = re.search(r"publiee?\s+le\s+(\d{2}/\d{2}/\d{4})", normalized_text)
    if match is None:
        return None

    try:
        return datetime.strptime(match.group(1), "%d/%m/%Y").date()
    except ValueError:
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
        '  make freework-smoke ARGS="--headful --from-date 2026-05-01"'
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


def _keyword_to_search_url(keyword: str) -> str | None:
    normalized_terms = _normalize_search_terms([keyword])
    if not normalized_terms:
        return None
    return _search_terms_to_url(normalized_terms)


def _normalize_search_terms(keywords: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        for raw_term in keyword.split(","):
            normalized_term = _normalize_text(raw_term)
            normalized_term = re.sub(r"\s+", " ", normalized_term).strip()
            if not normalized_term or normalized_term in seen:
                continue
            seen.add(normalized_term)
            terms.append(normalized_term)
    return terms


def _search_terms_to_url(terms: list[str]) -> str:
    query_items = [
        ("locations", FREEWORK_SEARCH_LOCATION),
        ("query", " ".join(terms)),
    ]
    return f"{FREEWORK_BASE_URL}/fr/tech-it/jobs?{urlencode(query_items, quote_via=quote)}"


def _build_search_urls(
    *,
    required_keywords: list[str],
    search_url: str | None = None,
) -> list[str]:
    if search_url:
        return [search_url]

    urls: list[str] = []
    seen: set[str] = set()
    for keyword in required_keywords:
        terms = _normalize_search_terms([keyword])
        if not terms:
            continue
        generated_url = _search_terms_to_url(terms)
        if generated_url in seen:
            continue
        seen.add(generated_url)
        urls.append(generated_url)

    if not urls:
        return [DEFAULT_SEARCH_URL]
    return urls


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
        description="Run a small Playwright smoke scraper against Free-Work mission pages.",
    )
    parser.add_argument(
        "--search-url",
        help=(
            "Optional Free-Work listing URL override. "
            "By default the scraper iterates job_criteria required_keywords."
        ),
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
    return parser


async def _run_cli() -> int:
    args = _build_parser().parse_args()
    settings = get_settings()
    if FreeWorkScraper.platform not in settings.platform_targets:
        print("[]")
        return 0

    search_urls = _build_search_urls(
        required_keywords=settings.required_keywords,
        search_url=args.search_url,
    )
    records: list[ScrapedOpportunityRecord] = []
    seen_urls: set[str] = set()
    for search_url in search_urls:
        scraper = FreeWorkScraper(
            search_url=search_url,
            user_data_dir=args.user_data_dir,
            headless=not args.headful,
            slow_mo=args.slow_mo,
        )
        for record in await scraper.fetch_new_opportunity_records():
            if record.url in seen_urls:
                continue
            seen_urls.add(record.url)
            records.append(record)

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
