# Phase 3 — Continuous Monitor Loop: Implementation Summary

## What was implemented

Phase 3 wires the scraper (Phase 1) and Telegram bot (Phase 2) into an unattended loop. Every `MONITOR_INTERVAL_SECONDS` (default 15 min) it scrapes all configured platforms, deduplicates against the DB, persists new opportunities, and fires a Telegram alert for any that score at or above `alert_score_from`.

---

## Files created

| File | Purpose |
|------|---------|
| `openclaw/scrapers/registry.py` | `get_scrapers(platform, settings)` — maps platform name to configured scraper instances |
| `openclaw/monitor.py` | `monitor_loop()` async loop + `main()` entrypoint |

## Files modified

| File | Change |
|------|--------|
| `Makefile` | Added `monitor` target |
| `openclaw/monitor.py` | Bug fix: `_process_record` and `_send_alert` made `async`; Telegram send now `await`s `_send()` directly instead of using `asyncio.run()` |

---

## How the loop works

1. **Every cycle**: iterates over `settings.platform_targets` (`["free-work", "malt", "lehibou"]` by default)
2. **For each platform**: registry returns scraper instances; each scraper's `fetch_new_opportunity_records()` is called
3. **Deduplication within cycle**: `seen_ids` set prevents double-processing the same `external_id` across multiple keyword search URLs
4. **Per-record processing**:
   - `qualify_opportunity()` scores the opportunity
   - DB check: if already in DB with `status != "new"` → skip entirely (already acted on)
   - `upsert_opportunity()` inserts or refreshes the record
   - If **brand new** (`is_new=True`) AND route is `ALERT` → `await _send()` directly (see bug fix note below)
5. **Sleep** `MONITOR_INTERVAL_SECONDS` then repeat

**Platforms with no scraper** (`NotImplementedError`) are logged and skipped — the loop continues. Malt and LeHibou will be added in Phase 5.

---

## How to run the full stack

Three terminals, all from the project root:

**Terminal 1 — Database:**
```bash
make db-up
```

**Terminal 2 — Telegram bot (handles button taps):**
```bash
make bot
```

**Terminal 3 — Monitor loop (scrapes + alerts):**
```bash
make monitor
```

Expected monitor log output:
```
INFO  Monitor started. Interval: 900s. Platforms: ['free-work', 'malt', 'lehibou']
INFO  --- Scrape cycle starting ---
WARNING  No scraper registered for platform 'malt' — skipping.
WARNING  No scraper registered for platform 'lehibou' — skipping.
INFO  Alert sent: [free-work] some-external-id (score=80)
INFO  --- Cycle done. Sleeping 900s ---
```

---

## How to verify alerting works quickly

To avoid waiting 15 minutes, temporarily lower the interval and the alert threshold:

**1. In `.env`:**
```
MONITOR_INTERVAL_SECONDS=60
```

**2. In `config/job_criteria.yml`:**
```yaml
alert_score_from: 60
```

**3. Clear existing rows so they appear as new:**
```bash
make db-shell
```
```sql
-- Reset a specific row to "new" to re-trigger it
UPDATE opportunities SET status = 'new' WHERE id = 17;
-- Or delete all rows to start fresh (careful!)
DELETE FROM opportunities;
```

**4. Restart monitor** — within 60 seconds a cycle fires and any opportunity scoring ≥ 60 triggers a Telegram alert.

**5. Restore defaults** after testing:
```
MONITOR_INTERVAL_SECONDS=900
alert_score_from: 75
```

---

## Bug fix: asyncio event loop conflict

`sender.py`'s `send_alert_for_opportunity()` used `asyncio.run()` to send the Telegram message. This works fine when called from a plain synchronous context (e.g. the test script), but crashes inside the monitor loop because `asyncio.run()` cannot be called from within an already-running event loop.

**Fix applied to `openclaw/monitor.py`:**
- `_process_record()` and `_send_alert()` are now `async def`
- `_send_alert()` directly `await`s `_send()` (the inner coroutine from `sender.py`) instead of calling `asyncio.run()`
- `_scrape_platform()` now `await`s `_process_record()`

`sender.py`'s `send_alert_for_opportunity()` is unchanged and still works correctly for the standalone test script (`scripts/send_test_alert.py`) which runs outside any event loop.

---

## Alert routing logic

| Route | Score range | Telegram alert? |
|-------|-------------|-----------------|
| `reject` | < `auto_reject_score_below` (45) | No |
| `review` | 45–74 | No (persisted silently) |
| `alert` | ≥ `alert_score_from` (75) | Yes |

`REVIEW` opportunities are in the DB and can be queried manually:
```sql
SELECT id, external_id, score, status FROM opportunities WHERE payload->>'route' = 'review' ORDER BY score DESC;
```

---

## What is deferred to later phases

- **Phase 4**: Proposal generation — tapping "Draft Proposal" currently sets status to `"drafting"` only
- **Phase 5**: Malt and LeHibou scrapers — registry already raises `NotImplementedError` for them, monitor loop skips gracefully
