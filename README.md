# OpenClaw

OpenClaw is an AI-assisted freelance operating system for finding high-value missions, qualifying them, drafting a tailored proposal, and only sending after human confirmation on Telegram.

This repository is intentionally scoped for a clean V1 foundation. It gives you:

- a sane Python/FastAPI project layout
- local setup primitives (`.gitignore`, `Makefile`, `compose.yml`, `.env.example`)
- a working qualification pipeline scaffold
- a resume selection layer
- Telegram message shaping for approval workflows
- deployment guidance for running the stack on a VPS

It does **not** pretend the full system is finished. Platform scrapers, Telegram bot handlers, proposal generation, and submission automation are the next implementation layers.

## Product direction

OpenClaw is designed around:

1. Platform monitoring
2. Hard filtering
3. AI qualification
4. Telegram alerting
5. Proposal drafting
6. CV selection
7. Human approval
8. Submission

This is intentionally not a spam bot. The leverage comes from:

- identifying strong missions quickly
- reducing proposal preparation time
- selecting the most relevant CV
- keeping the final send action under human control

## V1 scope

Priority platforms:

1. Free-Work
2. Malt
3. LeHibou

Core capabilities:

1. Watch the target platforms continuously with Playwright.
2. Apply hard eliminatory rules before notifying you.
3. Score only the relevant missions.
4. Send Telegram alerts with approval buttons.
5. Retrieve similar proposal examples before drafting.
6. Select the best resume variant automatically.

## Current scaffold

Implemented in this repository now:

- FastAPI application entrypoint
- configuration loading via `.env`
- domain models for opportunities and resume variants
- scoring and filtering logic
- resume selection logic
- proposal memory query builder
- Telegram alert formatting
- qualification workflow composition
- local PostgreSQL + pgvector compose stack
- API health and qualification preview routes
- starter Playwright smoke scraper for Free-Work mission extraction

Still to implement:

- production-ready Playwright scrapers per platform
- authenticated session persistence / cookie rotation
- real Telegram Bot API handlers for callbacks
- OpenAI retrieval + draft generation
- database migrations and persistence wiring
- browser-driven proposal submission

## Repository layout

```text
.
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── config
│   └── job_criteria.yml
├── compose.yml
├── pyproject.toml
├── openclaw
│   ├── api
│   │   └── routes
│   ├── core
│   ├── db
│   ├── models
│   ├── scrapers
│   ├── services
│   └── workflows
├── ops
│   └── systemd
└── tests
```

## Qualification model

The qualification flow is intentionally split into two layers.

### 1. Hard filters

These reject missions before they can pollute Telegram:

- `minimum_tjm`
- `remote_required`
- `excluded_keywords`
- `required_keywords`

Default values in the scaffold now live in `config/job_criteria.yml`:

```yaml
platform_targets:
  - free-work
  - malt
  - lehibou

minimum_tjm: 650
remote_required: true
excluded_keywords:
  - wordpress
  - php
  - onsite only
required_keywords:
  - java
  - spring
  - sso
  - keycloak
```

### 2. Scoring layer

The current scoring engine encodes the signals you described:

- remote: `+30`
- hybrid Paris / Ile-de-France: `+10`
- TJM >= 700: `+25`
- Java + Spring: `+20`
- IAM / SSO keywords such as Keycloak, OAuth2, SAML: `+20`
- banking / finance context: `+15`
- legacy Java / maintenance-heavy context: `-10`

Routing:

- below `AUTO_REJECT_SCORE_BELOW`: reject
- between reject threshold and `ALERT_SCORE_FROM`: manual review bucket
- above `ALERT_SCORE_FROM`: Telegram alert

## Telegram approval flow

The intended runtime flow is:

1. A scraper collects a new mission.
2. OpenClaw applies hard filters and scoring.
3. If the mission qualifies, OpenClaw sends a Telegram alert with inline buttons:
   - `Approve`
   - `Reject`
   - `Draft Proposal`
4. If you click `Draft Proposal`, OpenClaw should:
   - retrieve similar successful proposals
   - choose the best matching CV
   - assemble a generation context
   - draft a concise proposal preview
5. If you click `Approve`, OpenClaw submits the validated proposal.
6. If you click `Reject`, the mission is archived or muted.

The scaffold already builds the Telegram alert text and callback payloads. What remains is wiring those payloads into a real bot process.

## Proposal memory and retrieval

The memory system is your moat. Before drafting, retrieve:

- similar industry
- similar stack
- similar mission type
- similar successful proposal style
- the best resume for the opportunity

Recommended storage tables:

- `opportunities`
- `proposal_examples`
- `proposal_drafts`
- `resumes`
- `platform_accounts`
- `outcomes`

Recommended retrieval inputs:

- detected stack keywords
- client / industry
- selected resume key
- preferred tone

The scaffold includes a `ProposalMemoryQuery` object that can feed either a pgvector retrieval query or a hybrid SQL + embedding search later.

## Resume strategy

OpenClaw should maintain multiple CV variants rather than a single generic one. The scaffold includes a first-pass catalog:

- `java-backend`
- `iam-sso`
- `enterprise-architect`
- `api-security`
- `cloud-migration`

The current resume selector is rule-based and chooses the strongest match from detected keywords and industry hints. That is enough for V1 and can later be upgraded with embeddings or historical conversion data.

## Local development

### Prerequisites

- Python 3.12
- Docker with Compose support
- Chromium dependencies for Playwright on your machine

### Bootstrap

```bash
make bootstrap
make db-up
make dev
```

The first command creates `.env` if missing, installs dependencies, and installs the Playwright browser.

To run the first Free-Work monitoring example after bootstrap:

```bash
make freework-smoke ARGS="--headful --limit 3"
```

The smoke command uses Playwright's persistent profile directory at
`data/playwright/freework`, so accepted cookies and future authenticated sessions can be
reused across runs.

### Manual setup

```bash
make env
make install-dev
make db-up
make playwright-install
make dev
```

### Quick verification

```bash
make check
```

### Free-Work smoke example

The first monitoring example now lives in:

- `openclaw/scrapers/freework.py`

It performs a minimal but useful first pass:

1. opens a Free-Work listing page
2. collects the first mission links
3. visits each mission page
4. extracts title, client, location, rate, remote mode, keywords, and summary
5. prints JSON to stdout

Default command:

```bash
python -m openclaw.scrapers.freework --headful --limit 3
```

Useful variants:

```bash
python -m openclaw.scrapers.freework --search-url "https://www.free-work.com/fr/tech-it/jobs/keycloak" --limit 5
python -m openclaw.scrapers.freework --user-data-dir data/playwright/freework --slow-mo 150 --headful
```

### Qualification preview endpoint

Once the API is running, you can preview how a mission would be scored:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/qualification/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "platform": "free-work",
    "external_id": "demo-1",
    "title": "Senior Java / IAM Consultant",
    "client": "Large Banking Group",
    "location": "Paris",
    "daily_rate_eur": 750,
    "remote_mode": "remote",
    "summary": "Java 21, Spring Boot, Keycloak, OAuth2, Kubernetes",
    "keywords": ["java", "spring", "keycloak", "oauth2", "kubernetes"],
    "industry": "banking"
  }'
```

## Configuration

The main configuration surface is `.env`.

Important variables:

- `DATABASE_URL`: PostgreSQL connection string
- `TELEGRAM_BOT_TOKEN`: bot token used for alerts and callback actions
- `TELEGRAM_CHAT_ID`: default destination chat for alerts
- `TELEGRAM_ALLOWED_USER_IDS`: optional allowlist for callback approval actions
- `OPENAI_API_KEY`: used for proposal drafting and retrieval augmentation
- `JOB_CRITERIA_FILE`: path to the YAML file containing platform targets and filtering criteria
- `RESUME_DIR`, `PROPOSAL_EXAMPLES_DIR`, `PLAYWRIGHT_STORAGE_DIR`

Example `config/job_criteria.yml`:

```yaml
platform_targets:
  - free-work
  - malt
  - lehibou

minimum_tjm: 650
remote_required: true
excluded_keywords:
  - wordpress
  - php
  - onsite only
required_keywords:
  - java
  - spring
  - sso
  - keycloak
auto_reject_score_below: 45
alert_score_from: 75
```

Recommended local directories:

- `data/resumes/`
- `data/proposal_examples/`
- `data/playwright/`
- `config/`

Inside `data/playwright`, keep platform-specific session storage such as:

- `data/playwright/free-work/`
- `data/playwright/malt/`
- `data/playwright/lehibou/`

## VPS deployment guide

### Recommended VPS process layout

Run three long-lived components on the VPS:

1. `api`
   Exposes health checks, admin/debug endpoints, and internal workflow endpoints.
2. `monitor`
   Runs Playwright scraping loops, applies filters, and stores opportunities.
3. `telegram`
   Listens for Telegram callbacks and triggers draft / approval actions.

For V1, long polling is simpler than a Telegram webhook because it avoids TLS and reverse-proxy complexity for bot callbacks.

### Recommended server responsibilities

- FastAPI for health and internal control endpoints
- PostgreSQL for opportunities, outcomes, proposals, and resumes
- Playwright browser contexts with persistent storage per platform
- Telegram bot process for alerting and approvals
- worker logic for proposal drafting and submission

### VPS setup sequence

1. Create an `openclaw` system user.
2. Clone the repository under `/opt/openclaw`.
3. Create a virtualenv and install dependencies.
4. Copy `.env.example` to `.env` and fill in real secrets.
5. Start PostgreSQL locally or point `DATABASE_URL` to a managed instance.
6. Install Playwright Chromium and required OS packages.
7. Run the API behind a reverse proxy if you want remote admin access.
8. Run monitor and Telegram workers as separate systemd services.

### Minimal API service

An example API unit file is included at [ops/systemd/openclaw-api.service](/Users/proxym/Desktop/FOLDER/DEV/PERSONAL/JOB_SCRAPPER/clawd-proposal/ops/systemd/openclaw-api.service).

Typical deployment flow on the VPS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
playwright install chromium
```

### Telegram approval requirements

Before you let the bot trigger any send action:

- restrict approvals to your Telegram user ID
- log every callback action
- keep a persisted opportunity state machine
- require a proposal draft preview before final submission
- never auto-send from the discovery event itself

### Platform submission discipline

Keep the system compliant and high-quality:

- do not auto-send blindly
- do not spam low-fit missions
- do not automate conversations end-to-end
- do log outcomes so proposal quality improves over time

## Suggested next implementation order

1. Add one Playwright scraper for Free-Work only.
2. Persist scored opportunities to PostgreSQL.
3. Wire real Telegram inline buttons and callback handlers.
4. Add proposal example retrieval from PostgreSQL.
5. Add resume file inventory and selection persistence.
6. Add proposal generation with retrieval + adaptation.
7. Add browser-assisted submission with explicit approval gates.

## Verification status

The scaffold includes lightweight unit tests around filtering and resume selection. Use `make check` after edits. For full runtime verification later, add integration tests around:

- scraper extraction
- Telegram callback handling
- proposal retrieval
- submission flow
