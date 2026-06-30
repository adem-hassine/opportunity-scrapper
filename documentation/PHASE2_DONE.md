# Phase 2 — Telegram Bot: Implementation Summary

## What was implemented

Phase 2 adds the human-in-the-loop layer: a Telegram bot that sends scored opportunity alerts with inline buttons (Approve / Reject / Draft Proposal) and updates the DB when a button is tapped.

---

## Files created

| File | Purpose |
|------|---------|
| `openclaw/bot/__init__.py` | `build_application(settings)` — assembles the python-telegram-bot Application with the callback handler registered |
| `openclaw/bot/handlers.py` | `send_opportunity_alert()` sends a message with DB-id-based buttons; `handle_callback()` routes taps to approve/reject/draft sub-handlers |
| `openclaw/bot/sender.py` | `send_alert_for_opportunity()` — one-shot async sender for use by the monitor loop (Phase 3); no polling |
| `openclaw/bot/main.py` | `main()` entrypoint — calls `app.run_polling(drop_pending_updates=True)` |

## Files modified

| File | Change |
|------|--------|
| `Makefile` | Added `bot` target: `.venv/bin/python -m openclaw.bot.main` |

---

## Design decisions

- **Callback data uses DB integer id** (`"approve:34"`) — Telegram limits callback_data to 64 bytes; some Free-Work external_id slugs exceed that limit.
- **Buttons are removed after any action** (`edit_message_reply_markup(reply_markup=None)`) — prevents double-tapping the same button.
- **`query.answer()` is always called** (in a `finally` block) — clears the Telegram spinner even if an exception occurs in the handler.
- **`drop_pending_updates=True`** — skips callbacks queued while the bot was offline, avoiding stale actions on restart.
- **No backfill on startup** — existing DB rows stay as `"new"` but no Telegram alert is sent for them. Only future scraper runs (Phase 3 monitor loop) trigger alerts.

---

## Required `.env` configuration

Before running `make bot`, fill in these values in `.env`:

```
TELEGRAM_BOT_TOKEN=<get from @BotFather on Telegram>
TELEGRAM_CHAT_ID=<your personal chat ID or group ID>
TELEGRAM_ALLOWED_USER_IDS=<your Telegram numeric user ID>
```

To find your Telegram user ID: message @userinfobot on Telegram.
To find your chat ID: message the bot and check `https://api.telegram.org/bot<TOKEN>/getUpdates`.

---

## How to run

```bash
make bot
```

The bot logs startup info and waits for callbacks. Keep it running alongside the monitor (Phase 3).

---

## How to verify end-to-end

### Step 1 — Start the bot in one terminal

```bash
make bot
```

Leave this running. You should see log lines like:
```
INFO  Application started
INFO  Started polling
```

### Step 2 — Send a test alert from a second terminal

Open a new terminal in the project directory and launch the Python shell:

```bash
cd /mnt/c/Users/baha-eddine.gam/Desktop/BAHA_EDDINE_GAM/ME/opportunity-scrapper
.venv/bin/python
```

Then paste this block (it picks record id=17, the best-scoring Java/Spring opportunity from the smoke test):

```python
from datetime import date
from openclaw.core.config import get_settings
from openclaw.db.session import get_session
from openclaw.bot.sender import send_alert_for_opportunity
from openclaw.models.domain import Opportunity, RemoteMode
from openclaw.models.storage import OpportunityRecord
from openclaw.services.filtering import FilteringRules
from openclaw.workflows.qualification import qualify_opportunity
from sqlalchemy import select

settings = get_settings()
rules = FilteringRules.from_settings(settings)

# Load the DB record and reconstruct the domain Opportunity from its payload
with get_session() as session:
    record = session.scalars(
        select(OpportunityRecord).where(OpportunityRecord.id == 17)
    ).one()
    p = record.payload  # JSON snapshot stored during scrape

    opp = Opportunity(
        platform=p["platform"],
        external_id=p["external_id"],
        title=p["title"],
        published_at=date.fromisoformat(p["published_at"]) if p.get("published_at") else None,
        client=p.get("client"),
        location=p.get("location"),
        daily_rate_eur=p.get("daily_rate_eur"),
        remote_mode=RemoteMode(p.get("remote_mode", "hybrid")),
        summary=record.summary,
        keywords=tuple(p.get("keywords", [])),
        industry=p.get("industry"),
    )

    # Need to keep record usable after session closes
    record_id = record.id
    record_platform = record.platform

# Re-qualify the opportunity to get telegram_message + buttons
packet = qualify_opportunity(opp, rules=rules)

# Re-load the record in a fresh context for sender
with get_session() as session:
    rec = session.scalars(
        select(OpportunityRecord).where(OpportunityRecord.id == record_id)
    ).one()
    send_alert_for_opportunity(settings, rec, packet)

print("Alert sent! Check Telegram.")
```

### Step 3 — Verify in Telegram

- The message should appear in your chat with 3 buttons: **Approve**, **Reject**, **Draft Proposal**
- Tap **Approve** → buttons disappear, reply "✓ Approved." appears

### Step 4 — Verify in DB

```bash
make db-shell
```

```sql
SELECT id, status FROM opportunities WHERE id = 17;
-- Expected: status = 'approved'
```

### Step 5 — Test Reject and Draft on other rows

Repeat Step 2 with `id=12` (score=45) and `id=34` (score=60), tapping a different button each time. Verify `status` in DB matches the action taken.

### Changing the record id

If you want to test a different opportunity, change `id == 17` to any id visible in:
```bash
make db-shell
# then:
SELECT id, external_id, score, status FROM opportunities WHERE status = 'new' ORDER BY score DESC LIMIT 10;
```

---

## What is deferred to Phase 3

- The monitor loop (`openclaw/monitor.py`) that calls `send_alert_for_opportunity()` automatically every 15 minutes
- The scraper registry (`openclaw/scrapers/registry.py`)
- `handle_draft` currently sets status to `"drafting"` and sends a placeholder reply; actual proposal generation is Phase 4
