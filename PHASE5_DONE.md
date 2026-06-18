# Phase 5 — LeHibou Scraper: Implementation Summary

## What was implemented

Phase 5 adds LeHibou as the second monitored platform alongside Free-Work. The scraper targets
`https://www.lehibou.com/recherche/annonces` — a **public, login-free** mission board. It follows
the same Playwright persistent-context pattern as the Free-Work scraper: one listing page per run,
then one detail page per mission link discovered.

Malt is deferred (see below) — its mission board requires an authenticated freelancer account.

---

## Files created

| File | Purpose |
|------|---------|
| `openclaw/scrapers/lehibou.py` | `LeHibouScraper` class + CLI entrypoint |

## Files modified

| File | Change |
|------|--------|
| `openclaw/scrapers/registry.py` | Added `"lehibou"` branch + fixed return type to `list[OpportunityScraper]` |
| `Makefile` | Added `lehibou-smoke` target |

---

## How the scraper works

1. **Listing page** (`/recherche/annonces`): Playwright navigates to the listing, dismisses the
   cookie banner (`button[data-cky-tag='accept-button']`), waits for mission links
   (`a[href*='/annonce/']`) and collects all unique `/annonce/{uuid}` URLs (10 per page).
   No keyword pre-filter is applied — the LeHibou SPA processes URL params client-side only, so
   `?keywords=java` returns the same 10 results as the unfiltered listing. Our own
   `KEYWORD_PATTERNS` + scoring engine handles relevance filtering downstream.

2. **Detail page** (`/annonce/{uuid}`): For each URL, the scraper extracts:
   - `title` — `h1` text
   - `external_id` — UUID from the URL path (stable, globally unique)
   - `published_at` — French long date ("12 juin 2026") parsed via `FRENCH_MONTHS` lookup
   - `daily_rate_eur` — regex on `(\d{3,4})\s*€\s*/\s*jour`
   - `remote_mode` / `remote_days_per_week` — parsed from the "Télétravail" metadata field:
     `"100%"` → REMOTE (5 days), `"Non"` → ONSITE, `"Possible"` or `"X%"` → HYBRID
   - `location` — extracted from the "Lieu" metadata label
   - `keywords` — matched against `KEYWORD_PATTERNS` (java, spring, keycloak, iam, sso, etc.)
     first in the structured "Domaine, métier et expertises requises" block, then in the full body
   - `industry` — matched against `INDUSTRY_PATTERNS` (banking, insurance, security, retail)
   - `summary` — free text between "Description de la mission" and footer stop tokens
   - `client` — `None` (not exposed on LeHibou detail pages)

3. **Persistence**: Same flow as Free-Work — each record is qualified, then upserted into the DB
   via `upsert_opportunity()`. Records already in DB with `status != "new"` are skipped.

---

## First-time setup (Cloudflare clearance)

LeHibou uses Cloudflare Turnstile bot detection on `/recherche/annonces`. A fresh Playwright
profile triggers the challenge. Run setup once to solve it manually and save the clearance cookie:

```bash
rm -rf data/playwright/lehibou   # clear any tainted profile
make lehibou-setup               # opens browser at the search page
# → solve the Cloudflare checkbox if it appears, then press Enter in the terminal
```

After setup the persistent profile at `data/playwright/lehibou/` holds the `cf_clearance` cookie
and subsequent runs (headless or headful) go straight through.

## How to run

```bash
# One-time session setup (solve Cloudflare challenge manually)
make lehibou-setup

# Normal run (headless after setup)
make lehibou-smoke

# With visible browser
make lehibou-smoke ARGS="--headful"

# Filter to missions published on or after a date
make lehibou-smoke ARGS="--from-date 2026-06-01"

# Include rejected missions in output
make lehibou-smoke ARGS="--include-rejected"
```

The monitor loop (`make monitor`) now picks up LeHibou automatically — the registry maps
`"lehibou"` to `LeHibouScraper()` and the monitor iterates all `settings.platform_targets`.

Expected monitor log lines:
```
INFO  [lehibou] Scraping https://www.lehibou.com/recherche/annonces
INFO  [lehibou] Discovered 10 mission links
INFO  Alert sent: [lehibou] some-uuid (score=80)
```

---

## Key parsing decisions

| Decision | Rationale |
|---|---|
| Scrape unfiltered listing | URL params are SPA client-side only — server returns same 10 results regardless of `?keywords=` |
| One page per run | Mirrors Free-Work; 15-min monitor interval ensures freshness without over-scraping |
| French long date format | LeHibou uses "12 juin 2026" (not numeric) — requires `FRENCH_MONTHS` mapping |
| `client=None` | Client name not exposed on detail pages — matches Free-Work behavior |
| Keyword extraction: structured block first | "Domaine, métier et expertises" section uses platform-curated tags, more reliable than free-text scan |
| Télétravail "Possible" → HYBRID | Most common value; we default `remote_days_per_week=None` when no percentage given |
| TJM regex matches `"600 /jour"` | `_normalize_text()` strips `€` (non-ASCII) via encode/decode; regex uses `(?:[€e])?` to make the symbol optional |
| No `h1` on detail pages | LeHibou renders the title in a `SPAN`; scraper waits on `.annonce-main-information__section` and extracts title as the line before "Mission LeHibou" in `innerText` |
| Cloudflare Turnstile | Uses `playwright-stealth` + `--disable-blink-features=AutomationControlled` + `--ignore-default-args=--enable-automation`; first-run `make lehibou-setup` saves the clearance cookie to the persistent profile |

---

## What is deferred

- **Malt scraper** (`openclaw/scrapers/malt.py`): Malt's mission board (`/missions`) requires a
  logged-in freelancer account. The scraper will need credentials stored in the persistent
  Playwright profile (`data/playwright/malt/`), with a one-time manual login step. Planned for
  the next iteration of Phase 5.
- **LeHibou pagination**: The scraper reads page 1 only (10 missions). Pagination via `?page=N`
  could be added if the monitor interval needs to cover a longer lookback window.
