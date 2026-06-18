# Phase 1 — DB Persistence: Implementation Summary

## What was implemented

Phase 1 adds PostgreSQL persistence so scraped opportunities are stored and deduplicated across runs. This is the prerequisite for the Telegram bot (Phase 2) and the continuous monitor loop (Phase 3).

---

## Files created

| File | Purpose |
|------|---------|
| `alembic.ini` | Alembic configuration; `sqlalchemy.url` is overridden at runtime by `env.py` |
| `alembic/env.py` | Wires Alembic to `get_settings().database_url` and `Base.metadata` from all 6 ORM models |
| `alembic/script.py.mako` | Standard Alembic migration template required by `alembic revision` |
| `alembic/versions/` | Directory for generated migration files (populated after running `alembic revision`) |
| `openclaw/db/repository.py` | Three repository functions: `upsert_opportunity`, `get_opportunity_by_external_id`, `update_opportunity_status` |

## Files modified

| File | Change |
|------|--------|
| `openclaw/db/session.py` | `get_session()` decorated with `@contextmanager`; added `session.commit()` on success and `session.rollback()` on error |
| `openclaw/models/storage.py` | Added `ForeignKey("opportunities.id")` to `ProposalDraftRecord.opportunity_id` and `OutcomeRecord.opportunity_id` |
| `openclaw/scrapers/freework.py` | Added persistence loop in `_run_cli()`: qualifies each record and upserts to DB before printing JSON; skips records already acted on (status != "new") |

---

## How to start the database and apply migrations

Docker Desktop must be running.

```bash
# 1. Start the PostgreSQL + pgvector container
make db-up

# 2. Generate the initial migration (run once, then commit the generated file)
.venv/bin/alembic revision --autogenerate -m "initial_schema"

# 3. Apply the migration
make db-migrate
```

The DB credentials are `openclaw/openclaw` on port 5432, database `openclaw` (matches `DATABASE_URL` in `.env`).

---

## How to verify persistence end-to-end

```bash
# Run the Free-Work scraper
make freework-smoke ARGS="--from-date 2026-05-01"

# Check rows in the DB
docker exec -it $(docker ps -qf name=openclaw) psql -U openclaw -d openclaw \
  -c "SELECT id, platform, external_id, status, score FROM opportunities LIMIT 10;"

# Verify idempotency: run again — row count must not increase for already-seen opportunities
make freework-smoke ARGS="--from-date 2026-05-01"

# Verify skip logic: update a row status, re-run — that row must NOT be reset
docker exec -it $(docker ps -qf name=openclaw) psql -U openclaw -d openclaw \
  -c "UPDATE opportunities SET status='approved' WHERE id=1;"
make freework-smoke ARGS="--from-date 2026-05-01"
# Row id=1 must still have status='approved'
```

---

## Design decisions

- **`session.flush()` in repository, not `session.commit()`** — the `with get_session()` context manager owns the transaction. The repository only flushes to populate `record.id` within the transaction; the caller commits.
- **Each record in its own `with get_session()` block** — a failure on one opportunity doesn't roll back others. Correct semantics for a scraper that may partially succeed.
- **Double `qualify_opportunity()` call in `_run_cli()`** — called once for persistence, once inside `_qualify_records()` for JSON output. The scoring function is pure/stateless so this is safe. The Phase 3 monitor loop will consolidate this.
- **`ProposalDraftRecord.resume_key` has no FK** — resume records are optional and may not exist yet. Soft reference is intentional.

---

## What is deferred to Phase 2

- Telegram bot process (`openclaw/bot/`)
- Inline keyboard buttons (Approve / Reject / Draft Proposal)
- `update_opportunity_status` is wired but not yet called — it will be used by Telegram callback handlers in Phase 2
- Malt and LeHibou scrapers (Phase 5)
