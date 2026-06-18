# OpenClaw — Full Technical Flow

This document traces every layer of the system end-to-end: from the scheduled scraper waking up, through scoring, Telegram alerting, human decision, proposal generation, and automated submission to Free-Work.

---

## Architecture at a glance

```
┌─────────────────┐    ┌──────────────────┐    ┌──────────────┐
│  monitor.py     │───▶│  freework.py     │───▶│  PostgreSQL  │
│  (async loop)   │    │  (Playwright)    │    │  (SQLAlchemy)│
└─────────────────┘    └──────────────────┘    └──────────────┘
        │                                              │
        │ qualify_opportunity()                        │
        ▼                                              │
┌─────────────────┐                                   │
│  filtering.py   │  score 0–100                      │
│  qualification  │  route: REJECT / REVIEW / ALERT   │
└─────────────────┘                                   │
        │ route == ALERT                               │
        ▼                                              │
┌─────────────────┐                                   │
│  sender.py      │  Telegram Bot API                 │
│  (PTB library)  │──────────────────────────────────▶│ Telegram
└─────────────────┘                                   │
        │                                             │
        │  Human taps a button (callback_query)       │
        ▼                                             │
┌─────────────────┐    ┌──────────────────┐          │
│  handlers.py    │───▶│  proposal_       │          │
│  (bot router)   │    │  generator.py    │          │
└─────────────────┘    │  (OpenAI API)    │          │
        │              └──────────────────┘          │
        │ draft saved to DB                           │
        ▼                                             │
┌─────────────────┐                                  │
│  freework_      │  Playwright automation            │
│  submitter.py   │─────────────────────────────────▶│ Free-Work
└─────────────────┘                                  │
```

---

## Stage 1 — Monitor loop starts

**Entry point:** `python -m openclaw.monitor` → `main()` → `asyncio.run(monitor_loop(settings))`

1. `get_settings()` reads `.env` (via pydantic-settings) and `config/job_criteria.yml` (via PyYAML). The result is an `lru_cache` singleton — it is never reloaded mid-run.
2. `FilteringRules.from_settings(settings)` copies all thresholds from settings into an immutable dataclass: `minimum_tjm`, `remote_required`, `excluded_keywords`, `required_keywords`, `auto_reject_score_below`, `alert_score_from`.
3. The loop enters `while True:` — it iterates every `settings.monitor_interval_seconds` (default: 900 s).
4. For each platform listed in `settings.platform_targets` (e.g. `["free-work"]`), it calls `_scrape_platform(platform, settings, rules)`.

---

## Stage 2 — Scraping (Free-Work)

**File:** `openclaw/scrapers/freework.py` — `FreeWorkScraper`

### 2a. Browser launch

`get_scrapers("free-work", settings)` returns a `FreeWorkScraper` instance per search URL. The scraper calls `fetch_new_opportunity_records()`:

```python
context = await playwright.chromium.launch_persistent_context(
    user_data_dir="data/playwright/freework",   # reuses login cookies
    headless=True,
    locale="fr-FR",
    viewport={"width": 1440, "height": 1200},
)
```

A **persistent context** is used so the authenticated Free-Work session (cookies, localStorage) survives between runs. No login step is needed at runtime.

### 2b. URL discovery

`_discover_mission_urls(list_page)`:

1. `page.goto(search_url)` — e.g. `https://www.free-work.com/fr/tech-it/jobs/java`
2. Dismisses the Didomi cookie banner if present (tries 4 selectors with 1-second timeout each).
3. Waits for `a[href*='/job-mission/']` to attach (up to 10 s).
4. Iterates all matching `<a>` elements, deduplicates, returns a list of absolute mission URLs.

### 2c. Detail scraping

For each URL, `_scrape_mission_detail(detail_page, url)` runs:

1. `page.goto(url, wait_until="domcontentloaded")` — no JS hydration wait, just initial HTML.
2. Waits for `h1` to be visible (confirms the mission title loaded).
3. Reads `page.locator("body").inner_text()` — full visible text of the page.
4. Runs a series of pure-Python regex/string extractors:
   - `_extract_top_metadata()` — finds location and client name from the first 12 lines after the `<h1>`, skipping noise tokens like "freelance", "postuler", "expérience".
   - `_extract_daily_rate()` — regex for patterns like `700 €/j` or `650-750 €/j` (takes lower bound of ranges).
   - `_extract_remote_mode()` — keyword scan: "100% remote" → `REMOTE`; "télétravail partiel" / "N jours remote" → `HYBRID`; "présentiel" → `ONSITE`; default → `HYBRID`.
   - `_extract_remote_days()` — regex for `[1-5] jours remote` or `[1-5] jours de télétravail`.
   - `_extract_published_at()` — regex for `publiée le DD/MM/YYYY`.
   - `_extract_keywords()` — scans normalized text against 25 `(needle, label)` pairs (e.g. "spring boot" → "spring boot", "keycloak" → "keycloak"); first 12 matches returned.
   - `_extract_industry()` — maps clusters of keywords to one of: banking, insurance, security, retail.
   - `_extract_summary()` — collects lines between the title and stop-tokens ("profil recherché", "postuler", etc.), up to 900 chars.
   - `_extract_external_id()` — tries the "Référence de l'offre : XXX" pattern, falls back to URL slug.

5. Returns an `Opportunity` dataclass (immutable, `slots=True`).

---

## Stage 3 — Qualification

**File:** `openclaw/workflows/qualification.py` → `qualify_opportunity(opportunity, rules)`

This is a pure synchronous function called once per scraped opportunity.

### 3a. Scoring (`filtering.py` — `score_opportunity`)

**Hard rejection** (checked first, in order — any match → score 0, route REJECT):
1. Excluded keyword in `opportunity.search_blob()` (lowercased title + summary + keywords joined).
2. `remote_required=True` and `remote_mode == ONSITE`.
3. `daily_rate_eur` is known and below `minimum_tjm`.
4. None of the `required_keywords` appear in the text blob.

**Signal scoring** (only if no hard rejection):

| Signal | Points |
|--------|--------|
| `remote_mode == REMOTE` | +30 |
| `remote_mode == HYBRID` in Paris | +10 |
| `remote_mode == HYBRID` elsewhere | +5 |
| TJM ≥ 700 €/day | +25 |
| TJM ≥ minimum_tjm (floor) | +10 |
| Java + Spring both present (or "spring boot") | +20 |
| IAM keywords (keycloak, oauth2, sso, saml, auth0, okta) | +20 |
| Banking/finance keywords | +15 |
| Legacy Java (java 8, maintenance, TMA) | −10 |

Score is clamped to [0, 100].

**Route assignment:**
- Score < `auto_reject_score_below` → REJECT
- Score ≥ `alert_score_from` → ALERT (triggers Telegram)
- Otherwise → REVIEW (buffered, no alert sent)

### 3b. Resume selection (`resume_selector.py`)

Only runs if not rejected. `select_best_resume(opportunity, resumes)` scores each of 5 built-in `ResumeVariant` entries against the opportunity's keyword blob:

| Key | Label |
|-----|-------|
| `java-backend` | Java Backend Developer |
| `iam-sso` | IAM / SSO Expert |
| `enterprise-architect` | Enterprise Architect |
| `api-security` | API Security Specialist |
| `cloud-migration` | Cloud Migration Lead |

Each variant has a list of `keywords`. Score = count of variant keywords found in opportunity blob. Highest score wins; tie → first variant in list.

### 3c. Memory query (`proposal_memory.py`)

`build_memory_query(opportunity, resume_match)` assembles a `ProposalMemoryQuery` — a struct that captures what to search for when retrieving a reference proposal: `stack_keywords`, `industry`, `resume_key`, `preferred_tone`. Not yet used for DB retrieval (pgvector is scaffolded, not wired).

### 3d. Packet assembly

`QualificationPacket` bundles:
- `filtering_result` — score, route, reasons, matched signals
- `resume_match` — selected CV variant + matched keywords
- `memory_query` — retrieval context for proposal generation
- `telegram_message` — pre-formatted alert text (built by `build_opportunity_alert()`)
- `telegram_buttons` — tuple of `TelegramButton(label, callback_data)` for the alert

---

## Stage 4 — Persistence & deduplication

**File:** `openclaw/db/repository.py` → `upsert_opportunity()`

```python
existing = get_opportunity_by_external_id(session, platform, external_id)
if existing is not None and existing.status != "new":
    return  # already acted on — skip entirely
db_record = upsert_opportunity(session, opp, filtering_result)
```

- **INSERT** (new): `status = "new"`, all fields populated, full `payload` JSON stored.
- **UPDATE** (seen before, still "new"): score, summary, payload refreshed; status unchanged.
- **Skip** (seen before, status changed): the human already acted on it — don't re-alert.

The `payload` JSON column stores every field the scraper extracted (title, client, location, rate, remote mode, keywords, source_url, route, signals, etc.) so handlers can reconstruct an `Opportunity` later without re-scraping.

---

## Stage 5 — Telegram alert

**Files:** `openclaw/bot/sender.py` → `_send()` (called from `monitor.py`)

Only executes if `is_new AND route == ALERT`.

1. Loads the `OpportunityRecord` from DB by its integer `id`.
2. Builds an `InlineKeyboardMarkup` from `packet.telegram_buttons` — three buttons:
   ```
   [⚡ Quick Apply]  [📝 Review & Apply]  [✗ Reject]
   ```
   Each button's `callback_data` is `"{action}:{db_id}"` — e.g. `"quick_apply:42"`.
3. Calls `bot.send_message(chat_id=..., text=packet.telegram_message, reply_markup=markup)`.

The `telegram_message` text contains: platform, TJM, remote mode, client, industry, stack keywords, score/100, route, and suggested CV.

> **callback_data format:** `"{TelegramAction.value}:{opportunity_id}"` — e.g. `"review:42"`. Maximum 64 bytes (Telegram limit). The `opportunity_id` is the PostgreSQL row integer ID, not the Free-Work external_id.

---

## Stage 6 — Human decision (Telegram bot)

**File:** `openclaw/bot/handlers.py` — `handle_callback(update, context)`

The PTB (python-telegram-bot) bot is running via `make bot` → `python -m openclaw.bot`. It polls the Telegram API for updates.

When the user taps a button, `handle_callback` receives the `CallbackQuery`:

1. Validates `sender_id` against `settings.telegram_allowed_user_ids`.
2. Splits `callback_data` on `:` → `action`, `opportunity_id`.
3. Dispatches to the appropriate handler.

### Path A — ✗ Reject

`_handle_reject(query, opportunity_id)`:
- DB: `UPDATE opportunities SET status = 'rejected'`
- Telegram: remove buttons (`edit_message_reply_markup(None)`) → reply `"✗ Rejeté."`

### Path B — 📝 Review & Apply

`_handle_review(query, opportunity_id)`:

1. DB: status → `"drafting"`
2. Remove alert buttons; reply `"📝 Génération en cours..."`
3. Load `OpportunityRecord` from DB → reconstruct `Opportunity` from `payload` JSON.
4. Re-run `qualify_opportunity()` to get fresh `packet` (resume match, memory query).
5. Call `generate_proposal()` in a thread pool executor (`asyncio.get_running_loop().run_in_executor(None, ...)`) — this is the blocking OpenAI call.
6. DB: insert `ProposalDraftRecord` (status `"drafted"`) + update opportunity status → `"drafted"`.
7. Build combined preview message via `build_preview_message(opp, resume_match, draft_text)`:
   ```
   📋 TITLE — CLIENT
   
   📄 CV : IAM / SSO Expert
   Matched: keycloak, oauth2
   
   ──────────────────────
   [proposal text, up to 800 chars, then "… (N chars total)"]
   ──────────────────────
   ```
8. Send preview with `[✅ Envoyer]  [🔄 Regénérer]  [✗ Rejeter]` buttons.

### Path C — 🔄 Regénérer

`_handle_regenerate(query, opportunity_id)`:

1. **Immediately** edit the preview message in-place to `"🔄 Regénération en cours..."` (clears buttons, gives instant feedback).
2. Load opportunity from DB, re-qualify, generate new proposal (same executor pattern as path B).
3. Insert a new `ProposalDraftRecord` (old one stays for audit trail).
4. Edit the **same** message in-place again with the new preview text + buttons (`query.edit_message_text(preview_text, reply_markup=markup)`).

### Path D — ✅ Envoyer

`_handle_send(query, opportunity_id)`:

1. Load `OpportunityRecord` + latest `ProposalDraftRecord` (by `ORDER BY id DESC LIMIT 1`).
2. Check platform is `"free-work"` (only supported platform).
3. DB: status → `"approved"`.
4. Remove preview buttons; reply `"📤 Envoi de la candidature en cours..."`.
5. Call `_submit(mission_url, draft.proposal_text, resume_file, settings)`.
6. Call `_reply_submission_result()` and `_persist_submission()`.

### Path E — ⚡ Quick Apply

`_handle_quick_apply(query, opportunity_id)`:

Same as path D but generates the proposal on-the-fly (no preview shown). Flow:

1. DB: status → `"approved"` immediately.
2. Remove alert buttons; reply `"⚡ Génération et envoi en cours..."`.
3. Load opportunity, re-qualify, generate proposal in executor.
4. Insert `ProposalDraftRecord`.
5. Call `_submit()`, `_reply_submission_result()`, `_persist_submission()`.

### Path F — ✗ Rejeter (from preview)

`_handle_reject_preview(query, opportunity_id)`:
- Same logic as path A — status → `"rejected"`, buttons removed, `"✗ Rejeté."`.

---

## Stage 7 — Proposal generation (OpenAI)

**File:** `openclaw/services/proposal_generator.py` → `generate_proposal()`

This runs synchronously inside `run_in_executor` so it doesn't block the async event loop.

### 7a. Load example proposals

`_load_examples(settings.proposal_examples_dir)` scans `data/proposal_examples/*.md`. Each file has YAML frontmatter (title, stack_keywords, industry, tone) and proposal text body. Parsed into `ProposalExample` dataclasses.

### 7b. Find best matching example

`_find_best_example(examples, memory_query)` scores each example:
- +2 per keyword overlap between `example.stack_keywords` and `memory_query.stack_keywords`
- +3 if `example.industry == memory_query.industry`

The highest-scoring example (minimum score > 0) becomes the reference. If none match, the model receives `"Aucune proposition similaire disponible."`.

### 7c. Build user message

`_build_user_message()` assembles a structured prompt with four sections:

```
## Offre de mission
Titre : TECH LEAD JAVA
Client : PARTECK
TJM : 700 €/jour
Mode : hybrid
Stack / mots-clés : java, spring boot, keycloak
Résumé : ...

## Proposition de référence
[text of the matched example, or "Aucune..."]

## Profil CV sélectionné
Profil : IAM / SSO Expert
Justification : ...

## Ton souhaité
consultative
```

### 7d. OpenAI call

```python
client = openai.OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
response = client.chat.completions.create(
    model=settings.openai_model,   # default: "gpt-4o-mini"
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ],
    max_tokens=1024,
    temperature=0.7,
)
return response.choices[0].message.content.strip()
```

The system prompt instructs the model to adapt an existing proposal, not generate from scratch, and to respond with only the proposal text.

---

## Stage 8 — Browser submission (Free-Work)

**File:** `openclaw/scrapers/freework_submitter.py` → `FreeWorkSubmitter.submit_application()`

Same persistent Playwright profile as the scraper (`data/playwright/freework`), so login session is shared.

### Submission steps

1. `page.goto(mission_url)` + dismiss cookie banner.
2. Check current URL — if it matches `/onboarding`, `/login`, `/register`: return `SubmissionResult(success=False, error="...")`.
3. Click `button.btn--secondary:has-text('Postuler')` (or `btn--primary` variant).
4. Wait 2 seconds for Vue.js reactivity to reveal the inline form.
5. Check post-click URL — if redirected to `/onboarding`: profile is incomplete → error with instructions.
6. Try selectors in order until the textarea is found (visible within 8 s):
   - `#job-application-message` (primary)
   - `textarea[name='job-application-message']`
   - `textarea` (fallback)
7. `composer.click()` then `composer.fill(proposal_text)` — the `click()` is required to trigger Vue's focus event before `fill()`.
8. If `dry_run=True`: log and return success without clicking submit.
9. Try submit button selectors in order:
   - `button.btn--primary:has-text('Je postule')`
   - `button[type='submit']:has-text('Je postule')`
   - `button[type='submit'].btn--primary`
   - `button[type='submit']`
10. Click submit, wait 3 seconds for navigation.
11. Record `confirmation_url = page.url` if it changed from `mission_url`.
12. Return `SubmissionResult(success=True, platform="free-work", mission_url=..., confirmation_url=..., submitted_at=datetime.now(UTC))`.

> **CV attachment:** Free-Work attaches the CV stored in the user's profile automatically. No file upload is needed in the submission flow.

---

## Stage 9 — Post-submission persistence

**File:** `openclaw/bot/handlers.py` → `_persist_submission()` + `_reply_submission_result()`

```python
async def _persist_submission(opportunity_id, draft_id, mission_url, result):
    status = "submitted" if result.success else "approved"  # keep retryable on failure
    with get_session() as session:
        update_opportunity_status(session, opportunity_id, status)
        session.add(SubmissionRecord(
            opportunity_id=opportunity_id,
            proposal_draft_id=draft_id,
            platform=result.platform,
            mission_url=result.mission_url or mission_url,
            confirmation_url=result.confirmation_url,
            success=result.success and result.error is None,
            error_message=result.error if not success else None,
            submitted_at=result.submitted_at or datetime.now(UTC),
        ))
```

**Success confirmation (Telegram):**
```
✅ Candidature envoyée — TECH LEAD JAVA
📋 "Bonjour, je suis consultant Java/IAM avec 10 ans…"
```

**Failure confirmation (Telegram, status stays "approved" so retry is possible):**
```
❌ Échec — TECH LEAD JAVA
{error details}
Statut conservé à 'approved' — retappez ✅ Envoyer pour réessayer.
```

---

## Database schema

| Table | Purpose | Written by |
|-------|---------|------------|
| `opportunities` | One row per scraped mission | `upsert_opportunity()` in monitor loop |
| `proposal_drafts` | Every generated proposal text, including regenerations | `handlers.py` — `_handle_review`, `_handle_quick_apply`, `_handle_regenerate` |
| `submissions` | Each submission attempt (success or failure) | `handlers.py` — `_persist_submission()` |
| `outcomes` | Win/loss feedback after interview/contract | Scaffolded; never written to yet |
| `proposal_examples` | Reference proposals for the retrieval strategy | Scaffolded; loaded from flat `.md` files instead |
| `resumes` | CV catalog in DB | Scaffolded; in-code variants used instead |
| `platform_accounts` | Login credentials per platform | Scaffolded; unused |

---

## Opportunity status lifecycle

```
new  ──────────────────────────────────────────▶  rejected
 │                                                  ▲  ▲
 │  📝 Review & Apply                               │  │
 ▼                                                  │  │
drafting ──▶ drafted ──────────────────────────────▶  │
                │                                      │
                │  ✅ Envoyer / ⚡ Quick Apply          │
                ▼                                      │
             approved ──▶ submitted                   │
                │    (fail)   │                       │
                └────────────┘                       │
             (retryable — stays "approved")           │
                                                      │
             Any stage ──────── ✗ Reject ────────────▶
```

---

## Configuration reference

| Source | What it controls |
|--------|-----------------|
| `.env` | `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_ALLOWED_USER_IDS`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `MONITOR_INTERVAL_SECONDS`, `PLAYWRIGHT_STORAGE_DIR` |
| `config/job_criteria.yml` | `minimum_tjm`, `remote_required`, `excluded_keywords`, `required_keywords`, `auto_reject_score_below`, `alert_score_from`, `platform_targets` |
| `data/proposal_examples/*.md` | Reference proposals for generation (YAML frontmatter + proposal body) |
| `data/playwright/freework/` | Playwright persistent browser profile (cookies, localStorage) |
