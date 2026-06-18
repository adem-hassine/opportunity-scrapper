from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openclaw.models.domain import SubmissionResult

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

logger = logging.getLogger(__name__)

FREEWORK_BASE_URL = "https://www.free-work.com"

# Postuler button on the mission detail page sidebar
POSTULER_BUTTON_SELECTOR = (
    "button.btn--secondary:has-text('Postuler'),"
    " button.btn--primary:has-text('Postuler')"
)

# After clicking Postuler, Free-Work reveals an inline application form on the same page.
# The form contains a message textarea and a "Je postule" submit button.
APPLICATION_FORM_SELECTOR = "#job-application-message"
MESSAGE_COMPOSER_SELECTORS = (
    "#job-application-message",
    "textarea[name='job-application-message']",
    "textarea",
)
SUBMIT_BUTTON_SELECTORS = (
    "button.btn--primary:has-text('Je postule')",
    "button[type='submit']:has-text('Je postule')",
    "button[type='submit'].btn--primary",
    "button[type='submit']",
)

# Profile-incomplete gate: when Postuler redirects to onboarding
PROFILE_INCOMPLETE_URL_PATTERNS = ("/onboarding", "/register", "/login", "/inscription")

COOKIE_ACCEPT_SELECTORS = (
    "#didomi-notice-agree-button",
    "button:has-text('Tout accepter')",
    "button:has-text('Accepter')",
)


@dataclass(frozen=True, slots=True)
class SubmissionContext:
    mission_url: str
    proposal_text: str
    resume_file_path: str | None
    dry_run: bool = False


class FreeWorkSubmitter:
    """
    Submits a freelance application on Free-Work via Playwright automation.

    Free-Work application flow (for users with a complete profile):
    1. Navigate to the mission detail page
    2. Click "Postuler" → an inline application form appears on the page
    3. Fill the MESSAGE textarea (#job-application-message) with the proposal text
    4. Click "Je postule" to submit

    The CV stored in the profile (CV partagé) is attached automatically — no upload needed.

    PREREQUISITE: Complete your Free-Work profile once via `make freework-onboarding`
    (upload CV + fill personal/professional info). Then `make freework-login` to save session.
    """

    platform = "free-work"

    def __init__(
        self,
        *,
        user_data_dir: str | Path = "data/playwright/freework",
        headless: bool = True,
        slow_mo: int = 0,
        timeout_ms: int = 30_000,
        dry_run: bool = False,
    ) -> None:
        self.user_data_dir = Path(user_data_dir)
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout_ms = timeout_ms
        self.dry_run = dry_run

    async def submit_application(
        self,
        mission_url: str,
        proposal_text: str,
        resume_file_path: str | None = None,
    ) -> SubmissionResult:
        if async_playwright is None:
            return SubmissionResult(
                success=False,
                platform=self.platform,
                mission_url=mission_url,
                error="Playwright is not installed. Run `make bootstrap` first.",
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
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                    ignore_default_args=["--enable-automation"],
                )
            except Exception as exc:
                return SubmissionResult(
                    success=False,
                    platform=self.platform,
                    mission_url=mission_url,
                    error=f"Browser launch failed: {exc}",
                )

            context.set_default_timeout(self.timeout_ms)
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                return await self._do_submit(
                    page,
                    SubmissionContext(
                        mission_url=mission_url,
                        proposal_text=proposal_text,
                        resume_file_path=resume_file_path,
                        dry_run=self.dry_run,
                    ),
                )
            finally:
                await context.close()

    async def _do_submit(self, page: Page, ctx: SubmissionContext) -> SubmissionResult:
        try:
            await page.goto(ctx.mission_url, wait_until="domcontentloaded")
        except Exception as exc:
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error=f"Navigation failed: {exc}",
            )

        await _dismiss_cookie_banner(page)

        # Check login state
        current_url = page.url
        if any(p in current_url for p in PROFILE_INCOMPLETE_URL_PATTERNS):
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error=(
                    "Not logged in — redirected to login/register page. "
                    "Run `make freework-login` to save the session."
                ),
            )

        # Click Postuler button
        try:
            postuler = page.locator(POSTULER_BUTTON_SELECTOR).first
            await postuler.wait_for(state="visible", timeout=10_000)
            await postuler.click()
        except PlaywrightTimeoutError:
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error="'Postuler' button not found — mission may be closed or selector changed.",
            )

        # Wait for post-click settling
        await page.wait_for_timeout(2_000)

        # Detect redirect to profile-incomplete / login page
        post_click_url = page.url
        if any(p in post_click_url for p in PROFILE_INCOMPLETE_URL_PATTERNS):
            if "/onboarding" in post_click_url:
                return SubmissionResult(
                    success=False, platform=self.platform, mission_url=ctx.mission_url,
                    error=(
                        "Free-Work profile is incomplete — clicking Postuler redirected to "
                        f"{post_click_url}. "
                        "Please complete your profile at https://www.free-work.com/fr/onboarding "
                        "(upload your CV, fill personal/professional info) then retry."
                    ),
                )
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error=(
                    "Not logged in — Free-Work redirected to login after clicking Postuler. "
                    "Run `make freework-login` to log in and save the session."
                ),
            )

        # After clicking Postuler, Free-Work reveals an inline application form on the page.
        # Wait for the message textarea to appear.
        composer_locator = None
        for selector in MESSAGE_COMPOSER_SELECTORS:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=8_000)
                composer_locator = locator
                logger.info("[freework] Application form found (selector: %s)", selector)
                break
            except PlaywrightTimeoutError:
                continue

        if composer_locator is None:
            import json as _json
            elements_info = await _dump_interactive_elements(page)
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error=(
                    f"Application form not found after clicking Postuler. "
                    f"Page URL: {page.url!r}\n"
                    f"Interactive elements:\n"
                    f"{_json.dumps(elements_info, ensure_ascii=False, indent=2)}"
                ),
            )

        # Fill the message textarea — Vue requires click + fill for reactivity
        await composer_locator.click()
        await composer_locator.fill(ctx.proposal_text)
        logger.info("[freework] Proposal filled (%d chars)", len(ctx.proposal_text))

        # CV is already attached from the Free-Work profile — no upload needed.
        if ctx.resume_file_path:
            logger.info("[freework] CV upload skipped — profile CV is used automatically.")

        if ctx.dry_run:
            logger.info("[freework] DRY RUN — form filled but not submitted")
            return SubmissionResult(
                success=True,
                platform=self.platform,
                mission_url=ctx.mission_url,
                confirmation_url=None,
                error="dry_run=True — submission skipped",
            )

        # Click "Je postule" submit button
        submit_locator = None
        for selector in SUBMIT_BUTTON_SELECTORS:
            locator = page.locator(selector).first
            try:
                await locator.wait_for(state="visible", timeout=5_000)
                submit_locator = locator
                break
            except PlaywrightTimeoutError:
                continue

        if submit_locator is None:
            return SubmissionResult(
                success=False, platform=self.platform, mission_url=ctx.mission_url,
                error="Submit button ('Je postule') not found — page structure may have changed.",
            )

        await submit_locator.click()

        # Wait for post-submit confirmation (URL change or success message)
        try:
            await page.wait_for_timeout(3_000)
        except Exception:
            pass

        confirmation_url = page.url if page.url != ctx.mission_url else None
        logger.info("[freework] Submission complete. URL: %s", page.url)

        return SubmissionResult(
            success=True,
            platform=self.platform,
            mission_url=ctx.mission_url,
            confirmation_url=confirmation_url,
            submitted_at=datetime.now(tz=UTC),
        )


async def _dump_interactive_elements(page: Page) -> list[dict]:
    return await page.evaluate("""() => {
        const els = [...document.querySelectorAll(
            'input, textarea, button, [contenteditable], [role="dialog"], [role="textbox"], form'
        )];
        return els.slice(0, 40).map(el => ({
            tag: el.tagName,
            type: el.type || '',
            name: el.name || '',
            placeholder: el.placeholder || '',
            contenteditable: el.getAttribute('contenteditable') || '',
            className: el.className?.toString().slice(0, 80) || '',
            visible: el.offsetParent !== null,
            text: el.innerText?.slice(0, 60) || '',
        }));
    }""")


async def _dismiss_cookie_banner(page: Page) -> None:
    for selector in COOKIE_ACCEPT_SELECTORS:
        button = page.locator(selector).first
        try:
            await button.wait_for(state="visible", timeout=1_000)
            await button.click()
            return
        except PlaywrightTimeoutError:
            continue


async def _run_login(user_data_dir: str, slow_mo: int) -> None:
    """Open Free-Work login page with stealth args so Google OAuth works."""
    if async_playwright is None:
        print("Playwright is not installed. Run `make bootstrap` first.", file=sys.stderr)
        return

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    print("Opening Free-Work login in browser. Log in with Google, then press Enter here.")
    print(f"Profile will be saved to: {user_data_dir}")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            slow_mo=slow_mo,
            locale="fr-FR",
            viewport={"width": 1440, "height": 1200},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.free-work.com/fr/login", wait_until="domcontentloaded")
        input("→ Log in to Free-Work (use Google), then press Enter to save the session: ")
        await context.close()
    print("Session saved. You can now run `make freework-submit-test`.")


async def _run_onboarding(user_data_dir: str, slow_mo: int) -> None:
    """Open Free-Work onboarding so the user can complete their profile (required for Postuler)."""
    if async_playwright is None:
        print("Playwright is not installed. Run `make bootstrap` first.", file=sys.stderr)
        return

    Path(user_data_dir).mkdir(parents=True, exist_ok=True)
    print("Opening Free-Work profile onboarding in browser.")
    print("Complete all steps (upload CV, personal info, professional info, etc.)")
    print("then press Enter here when done.")

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            slow_mo=slow_mo,
            locale="fr-FR",
            viewport={"width": 1440, "height": 1200},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
            ignore_default_args=["--enable-automation"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://www.free-work.com/fr/onboarding", wait_until="domcontentloaded")
        input("→ Complete your Free-Work profile (upload CV + fill info), then press Enter: ")
        await context.close()
    print("Profile setup complete. You can now use Postuler automation.")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Submit a Free-Work application via Playwright (inbox messaging flow).",
    )
    parser.add_argument(
        "--mission-url",
        required=False,
        default=None,
        help="Full URL of the Free-Work mission detail page.",
    )
    parser.add_argument(
        "--proposal-text",
        default="[Test proposal — dry run]",
        help="Proposal message to send to the recruiter.",
    )
    parser.add_argument(
        "--resume-file",
        default=None,
        help="Path to PDF/DOCX CV file (not uploaded — Free-Work uses the profile CV).",
    )
    parser.add_argument(
        "--user-data-dir",
        default="data/playwright/freework",
        help="Playwright persistent profile directory.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show browser window.",
    )
    parser.add_argument(
        "--slow-mo",
        type=int,
        default=500,
        help="Milliseconds between browser actions (default 500 for visibility).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose message but do NOT click Send.",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open browser at Free-Work login page to save session (one-time setup).",
    )
    parser.add_argument(
        "--onboarding",
        action="store_true",
        help="Open Free-Work profile onboarding so you can complete your profile.",
    )
    return parser


async def _run_cli() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args()

    if args.login:
        await _run_login(args.user_data_dir, args.slow_mo)
        return 0

    if args.onboarding:
        await _run_onboarding(args.user_data_dir, args.slow_mo)
        return 0

    if not args.mission_url:
        print("--mission-url is required (unless using --login or --onboarding)", file=sys.stderr)
        return 1

    submitter = FreeWorkSubmitter(
        user_data_dir=args.user_data_dir,
        headless=not args.headful,
        slow_mo=args.slow_mo,
        dry_run=args.dry_run,
    )

    result = await submitter.submit_application(
        mission_url=args.mission_url,
        proposal_text=args.proposal_text,
        resume_file_path=args.resume_file,
    )

    if result.success:
        print(f"✅ {'DRY RUN — ' if result.error else ''}Submission successful")
        if result.confirmation_url:
            print(f"   Confirmation URL: {result.confirmation_url}")
        if result.error:
            print(f"   Note: {result.error}")
        return 0
    else:
        print(f"❌ Submission failed: {result.error}", file=sys.stderr)
        return 1


def main() -> None:
    raise SystemExit(asyncio.run(_run_cli()))


if __name__ == "__main__":
    main()
