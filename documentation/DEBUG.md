# Local Debug Guide

Step-by-step instructions for running and debugging every part of OpenClaw on your local machine.

---

## Prerequisites

- Python 3.12 (installed via deadsnakes in WSL — see `SETUP_EXTERNAL.md` section 4)
- Docker Engine running inside WSL (`sudo service docker start`)
- A `.env` file at the project root (see step 1)

---

## Step 1 — First-time setup

```bash
make bootstrap
```

This does three things in one shot:
1. Copies `.env.example` → `.env` if it doesn't exist yet
2. Creates `.venv/` and installs all dev dependencies (including Alembic and PyYAML)
3. Installs the Playwright Chromium browser

Then open `.env` and fill in the real values for anything marked `replace-me`:

```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
OPENAI_EMBEDDINGS_MODEL=text-embedding-3-small

TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_CHAT_ID=your_chat_id
TELEGRAM_ALLOWED_USER_IDS=your_telegram_user_id
```

Leave `DATABASE_URL` as-is — it matches the Docker Compose defaults.

> For instructions on getting your Telegram bot token, OpenAI key, and other external accounts, see **SETUP_EXTERNAL.md**.

After filling in `.env`, run the environment check to confirm everything is wired up:

```bash
make check-env
```

---

## Step 2 — Start the database

```bash
make db-up
```

Starts a PostgreSQL 16 + pgvector container named `openclaw-postgres` on port `5432`.

**Verify it is healthy:**
```bash
docker ps
# Should show: openclaw-postgres   Up X seconds (healthy)

make db-check
# Should print: DB: connected
```

**Create tables (first time, or after a `make db-down`):**
```bash
make db-create-tables
```
This runs `Base.metadata.create_all()` — no migrations needed for local dev.

**Connect directly to inspect data:**
```bash
make db-shell
# or: docker exec -it openclaw-postgres psql -U openclaw -d openclaw
```

Useful psql commands:
```sql
\dt                          -- list all tables
SELECT * FROM opportunities LIMIT 10;
SELECT status, count(*) FROM opportunities GROUP BY status;
\q
```

**Stop the database:**
```bash
make db-down
```

---

## Step 3 — Run the verification suite

```bash
make check
```

This runs a compile check + all unit tests. Run this after any code change. Expected output:
```
Compiling openclaw ...
Compiling tests ...
...
Ran 20 tests in 0.XXXs
OK
```

Run a single test file:
```bash
.venv/bin/python -m unittest tests/test_filtering.py -v
```

Run a single test case:
```bash
.venv/bin/python -m unittest tests.test_filtering.TestFiltering.test_high_quality_opportunity -v
```

---

## Step 4 — Run the FastAPI server

```bash
make dev
```

Server starts at `http://127.0.0.1:8000` with hot reload.

**Check it is alive:**
```bash
curl http://127.0.0.1:8000/healthz
```

Expected response:
```json
{"status": "ok", "app_name": "OpenClaw", "environment": "development", ...}
```

**Test the qualification preview endpoint:**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/qualification/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "platform": "free-work",
    "external_id": "debug-1",
    "title": "Senior Java / Keycloak Consultant",
    "client": "BNP Paribas",
    "location": "Paris",
    "daily_rate_eur": 750,
    "remote_mode": "remote",
    "summary": "Java 21, Spring Boot, Keycloak, OAuth2",
    "keywords": ["java", "spring", "keycloak", "oauth2"],
    "industry": "banking"
  }'
```

The response shows `score`, `route` (`alert` / `review` / `reject`), matched keywords, resume suggestion, and the Telegram message that would be sent.

**Swagger UI** (interactive): `http://127.0.0.1:8000/docs`

---

## Step 5 — Run the Free-Work scraper manually

This is the main thing to test without needing a running bot or database.

**Headless (default, faster):**
```bash
make freework-smoke ARGS="--from-date 2026-05-01"
```

**Headful (watch the browser):**
```bash
make freework-smoke ARGS="--headful --from-date 2026-05-01"
```

**Custom search URL:**
```bash
make freework-smoke ARGS="--headful --search-url 'https://www.free-work.com/fr/tech-it/jobs/keycloak' --from-date 2026-05-01"
```

**Include rejected missions in output:**
```bash
make freework-smoke ARGS="--include-rejected --from-date 2026-05-01"
```

**Reuse a saved browser session (cookies, login state):**
```bash
make freework-smoke ARGS="--user-data-dir data/playwright/freework --headful --slow-mo 150"
```

The scraper prints qualified missions as JSON to stdout. Each entry contains `score`, `route`, `resume`, and the Telegram message preview.

**If Playwright fails to launch:**
```bash
.venv/bin/playwright install chromium
# On Linux also run:
.venv/bin/playwright install-deps chromium
```

---

## Step 6 — Debug the filtering and scoring logic

The fastest way to test a filter change without running the browser:

```python
# Paste into a .venv Python REPL or a scratch script
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.services.filtering import FilteringRules, score_opportunity

opp = Opportunity(
    platform="free-work",
    external_id="test-1",
    title="Java / Keycloak Senior",
    daily_rate_eur=750,
    remote_mode=RemoteMode.REMOTE,
    summary="Java 21 Spring Boot Keycloak OAuth2 banking",
    keywords=("java", "spring", "keycloak"),
    industry="banking",
)

rules = FilteringRules()
result = score_opportunity(opp, rules)
print(result.score, result.route, result.reasons, result.matched_signals)
```

Run it:
```bash
.venv/bin/python scratch.py
```

---

## Step 7 — Debug the job criteria YAML

If you change `config/job_criteria.yml` and want to verify it loads correctly:

```bash
.venv/bin/python -c "
from openclaw.core.config import load_job_criteria
c = load_job_criteria('config/job_criteria.yml')
print(c)
"
```

If PyYAML is not installed, the built-in fallback parser is used (supports only simple key-value and list syntax — no anchors, no multiline strings).

---

## Step 8 — Inspect what the settings object sees

```bash
.venv/bin/python -c "
from openclaw.core.config import get_settings
s = get_settings()
import json; print(json.dumps(s.public_summary(), indent=2))
print('TJM floor:', s.minimum_tjm)
print('Required keywords:', s.required_keywords)
"
```

---

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'openclaw'` | Not installed in venv | Run `make install-dev` |
| `playwright._impl._errors.Error: Executable doesn't exist` | Chromium not installed | Run `make playwright-install` |
| `connection refused` on port 5432 | DB container not running | Run `make db-up` |
| `FileNotFoundError: Job criteria file does not exist` | `.env` points to wrong path | Check `JOB_CRITERIA_FILE` in `.env` |
| `ValidationError` on settings load | Missing required `.env` key | Compare `.env` against `.env.example` |
| Scraper finds 0 missions | Free-Work changed page structure or cookie banner | Run `--headful` to watch what happens |
| Score is 0 and route is `reject` with "No required keywords matched" | Mission text doesn't contain any of `required_keywords` | Use `--include-rejected` to see the raw output |

---

## Useful one-liners

```bash
# Watch DB rows appear in real time while scraper runs
watch -n 2 'docker exec openclaw-postgres psql -U openclaw -d openclaw -c "SELECT platform, external_id, status FROM opportunities ORDER BY created_at DESC LIMIT 10;"'

# Tail FastAPI logs with timestamps
make dev 2>&1 | ts

# Check what Ruff would flag before running tests
make lint

# Format everything
make format
```
