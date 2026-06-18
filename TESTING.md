# OpenClaw — Full Flow Testing Guide

## Prerequisites

Make sure `.env` has these filled in before starting:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_ALLOWED_USER_IDS=...
OPENAI_API_KEY=...
DATABASE_URL=postgresql+psycopg://openclaw:openclaw@localhost:5432/openclaw
```

---

## Step 1 — Run the test suite

```bash
make check
```

Expected output:
```
Ran 19 tests in 0.4s
OK
```

---

## Step 2 — Start the full stack

Open **3 separate terminals** in the project directory.

**Terminal 1 — Database:**
```bash
make db-up
```

**Terminal 2 — Telegram bot:**
```bash
make bot
```

**Terminal 3 — Monitor loop:**
```bash
make monitor
```

---

## Step 3 — Lower the alert threshold

Edit `config/job_criteria.yml`:
```yaml
alert_score_from: 60
```

Set a short monitor interval in `.env`:
```env
MONITOR_INTERVAL_SECONDS=30
```

Restart Terminal 3:
```bash
make monitor
```

---

## Step 4 — Reset a DB row to trigger a Telegram alert

```bash
make db-shell
```

```sql
UPDATE opportunities
SET status = 'new'
WHERE id = (SELECT id FROM opportunities ORDER BY score DESC LIMIT 1);
```

Wait up to 30 seconds — a Telegram alert should appear with:
```
[⚡ Quick Apply]  [📝 Review & Apply]  [✗ Reject]
```

---

## Step 5 — Test each button

### Test A — ✗ Reject (from alert)

Tap **✗ Reject** on the alert.

Expected:
- Buttons disappear
- Reply: "✗ Rejeté."

Verify in DB:
```bash
make db-shell
```
```sql
SELECT id, status FROM opportunities ORDER BY id DESC LIMIT 1;
-- Expected: status = 'rejected'
```

---

### Test B — 📝 Review & Apply

Reset a row and wait for a fresh alert:
```sql
UPDATE opportunities SET status = 'new'
WHERE id = (SELECT id FROM opportunities ORDER BY score DESC LIMIT 1);
```

Tap **📝 Review & Apply**.

Expected:
- "📝 Génération en cours..." reply
- Then ONE combined message:
  ```
  📋 TITLE — CLIENT

  📄 CV : IAM / SSO Expert
  Matched: keycloak, oauth2

  ──────────────────────
  Bonjour, je suis consultant...
  ──────────────────────

  [✅ Envoyer]  [🔄 Regénérer]  [✗ Rejeter]
  ```

---

### Test C — 🔄 Regénérer (from preview)

After Test B, tap **🔄 Regénérer**.

Expected:
- The preview message changes to "🔄 Regénération en cours..." (buttons removed)
- Then the **same message** updates in-place with a new proposal text
- Buttons reappear: `[✅ Envoyer]  [🔄 Regénérer]  [✗ Rejeter]`

Verify a new draft was saved:
```bash
make db-shell
```
```sql
SELECT id, opportunity_id, resume_key, LEFT(proposal_text, 80)
FROM proposal_drafts
ORDER BY id DESC LIMIT 3;
```

---

### Test D — ✅ Envoyer (from preview)

After Test B or C, tap **✅ Envoyer**.

Expected:
- "📤 Envoi de la candidature en cours..."
- Then confirmation:
  ```
  ✅ Candidature envoyée — TECH LEAD JAVA
  📋 "Bonjour, je suis consultant Java/IAM..."
  ```

Verify in DB:
```bash
make db-shell
```
```sql
SELECT id, opportunity_id, success, error_message, submitted_at
FROM submissions
ORDER BY id DESC LIMIT 1;
-- Expected: success = true

SELECT id, status FROM opportunities ORDER BY id DESC LIMIT 1;
-- Expected: status = 'submitted'
```

Also check Free-Work "Mes candidatures" in the browser to confirm the application was received.

---

### Test E — ⚡ Quick Apply

Reset a row and wait for a fresh alert:
```sql
UPDATE opportunities SET status = 'new'
WHERE id = (SELECT id FROM opportunities ORDER BY score DESC LIMIT 1);
```

Tap **⚡ Quick Apply**.

Expected:
- "⚡ Génération et envoi en cours..."
- No preview shown
- Then confirmation directly:
  ```
  ✅ Candidature envoyée — TECH LEAD JAVA
  📋 "Bonjour, je suis consultant Java/IAM..."
  ```

---

### Test F — ✗ Rejeter (from preview)

Reset a row, tap **📝 Review & Apply**, then tap **✗ Rejeter** on the preview message.

Expected:
- Preview buttons disappear
- Reply: "✗ Rejeté."

Verify in DB:
```sql
SELECT status FROM opportunities ORDER BY id DESC LIMIT 1;
-- Expected: status = 'rejected'
```

---

## Step 6 — Full DB snapshot after all tests

```bash
make db-shell
```

```sql
-- Opportunities status overview
SELECT status, COUNT(*) FROM opportunities GROUP BY status;

-- All submissions
SELECT id, opportunity_id, platform, success, error_message
FROM submissions
ORDER BY id DESC LIMIT 10;

-- All proposal drafts
SELECT id, opportunity_id, resume_key, status
FROM proposal_drafts
ORDER BY id DESC LIMIT 10;
```

---

## Step 7 — Restore defaults

`config/job_criteria.yml`:
```yaml
alert_score_from: 75
```

`.env`:
```env
MONITOR_INTERVAL_SECONDS=900
```

Restart the monitor:
```bash
make monitor
```

---

## Dry-run submission test (without Telegram)

To test the Free-Work submitter directly without going through the full bot flow:

```bash
make freework-submit-test URL="https://www.free-work.com/fr/tech-it/developpeur-java-kotlin-groovy-scala/job-mission/tech-lead-java-283"
```

Expected:
```
INFO [freework] Application form found (selector: #job-application-message)
INFO [freework] Proposal filled (25 chars)
INFO [freework] DRY RUN — form filled but not submitted
✅ DRY RUN — Submission successful
```
