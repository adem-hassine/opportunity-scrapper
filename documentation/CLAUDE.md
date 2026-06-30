# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

OpenClaw is an AI-assisted freelance opportunity monitor for a Java/IAM consultant. It watches freelance platforms (Free-Work, Malt, LeHibou), applies hard filters and a scoring engine, then routes qualified opportunities to Telegram for human approval before any proposal is sent.

## Commands

```bash
make bootstrap          # First-time setup: creates .env, installs deps, installs Playwright Chromium
make db-up              # Start local PostgreSQL + pgvector via Docker Compose
make dev                # Run FastAPI with hot reload (port 8000)
make check              # Compile check + unit tests (run this before every commit)
make test               # Unit tests only
make lint               # Ruff lint
make format             # Ruff format
make freework-smoke ARGS="--headful --from-date 2026-05-01"  # Run the Free-Work scraper manually
```

Run a single test file directly:
```bash
.venv/bin/python -m unittest tests/test_filtering.py
```

The linter is Ruff (`line-length = 100`, rules `E F I B UP`, `B008` ignored). Python 3.12 is required.

## Architecture

The pipeline flows: **scraper → filtering → qualification workflow → Telegram alert → human approval → proposal**.

### Key layers

**`openclaw/core/config.py`** — single source of truth for settings. `Settings` (pydantic-settings, reads `.env`) delegates filtering criteria to `JobCriteria` (loaded from `config/job_criteria.yml`). `get_settings()` is an `lru_cache` singleton. All filtering thresholds (`minimum_tjm`, `remote_required`, `excluded_keywords`, `required_keywords`, `auto_reject_score_below`, `alert_score_from`) live in `config/job_criteria.yml`, not in `.env`.

**`openclaw/models/domain.py`** — two core dataclasses: `Opportunity` (platform mission data) and `ResumeVariant` (CV catalog entry). `Opportunity.search_blob()` produces a lowercased text blob used throughout the scoring engine.

**`openclaw/services/filtering.py`** — `score_opportunity(opportunity, rules) → FilteringResult`. Hard rejection happens first (excluded keywords, onsite-only, TJM below floor, no required keyword match). Scoring signals add/subtract points: remote (+30), TJM ≥ 700 (+25), Java+Spring (+20), IAM/SSO keywords (+20), banking (+15), legacy Java (−10). Routes: `REJECT` / `REVIEW` / `ALERT`.

**`openclaw/services/resume_selector.py`** — rule-based CV picker. `DEFAULT_RESUME_VARIANTS` is the built-in catalog (java-backend, iam-sso, enterprise-architect, api-security, cloud-migration). `select_best_resume(opportunity, resumes)` scores each variant against the opportunity's keyword blob.

**`openclaw/services/proposal_memory.py`** — builds a `ProposalMemoryQuery` from an opportunity and a resume match. This query is the retrieval context for future proposal generation (pgvector / hybrid SQL).

**`openclaw/services/telegram.py`** — formats the Telegram alert message and inline callback buttons (`Approve`, `Reject`, `Draft Proposal`).

**`openclaw/workflows/qualification.py`** — `qualify_opportunity(opportunity, rules, resumes) → QualificationPacket` composes all services into one call. `qualification_packet_to_dict()` serializes it for the API.

**`openclaw/scrapers/`** — `base.py` defines the `OpportunityScraper` protocol. `freework.py` is the only implemented scraper; it uses Playwright with a persistent profile under `data/playwright/freework`. Run it as `python -m openclaw.scrapers.freework`. Target platforms for V1: Free-Work, Malt, LeHibou. Post-V1: Freelance Informatique.

**`openclaw/api/routes/`** — two routes: `GET /health` and `POST /api/v1/qualification/preview` (scores an opportunity without persisting it).

### Data flow for a new platform scraper

1. Implement `OpportunityScraper` protocol in `openclaw/scrapers/<platform>.py`.
2. Yield `Opportunity` objects with `platform`, `external_id`, `daily_rate_eur`, `remote_mode`, `keywords`.
3. Pass each to `qualify_opportunity()` with `FilteringRules.from_settings(get_settings())`.
4. Send `ALERT`-routed packets to Telegram; ignore `REJECT`; buffer `REVIEW`.

### Storage (not yet wired)

`openclaw/db/session.py` and `openclaw/models/storage.py` scaffold SQLAlchemy + pgvector. The compose stack (`compose.yml`) runs PostgreSQL with the pgvector extension. Persistence to DB is not implemented yet.

### Proposal generation — prompting strategy

When implementing `openclaw/services/proposal_generator.py` (Phase 4), use **retrieval + adaptation**, not generation from scratch. The system prompt structure:

```
SYSTEM: You are adapting an existing successful freelance proposal.
INPUTS:
  - Job offer (title, stack, client, rate, remote mode)
  - Similar successful proposal retrieved from DB (matched by stack + industry)
  - Selected resume summary (from ResumeVariant)
  - Preferred tone: enterprise | consultative | technical
TASK: Generate a concise personalized proposal in French.
```

Retrieve similar examples from `ProposalExampleRecord` using `memory_query.stack_keywords` (SQL `LIKE` for V1, pgvector embeddings later). This pattern outperforms cold generation and improves over time as `OutcomeRecord` accumulates win/loss data.

## Configuration

All filtering criteria go in `config/job_criteria.yml`. Secrets and infrastructure settings go in `.env` (copy from `.env.example`). The `Settings` class proxies all `job_criteria.yml` fields, so callers use `settings.minimum_tjm` rather than reading the YAML directly.

`TELEGRAM_ALLOWED_USER_IDS` accepts a comma-separated string of integers in `.env`.