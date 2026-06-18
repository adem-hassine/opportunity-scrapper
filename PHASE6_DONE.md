# Phase 6 — Automated Submission on Free-Work: Implementation Summary

## What was implemented

Phase 6 closes the loop: after reviewing an AI-generated proposal in Telegram, the user taps
**"Approve & Submit"** and OpenClaw automatically fills the Free-Work application form and submits
it — no browser interaction required.

The full end-to-end flow is now:

```
Scraper → Telegram alert
  [Approve]          → generate proposal silently → submit → "✅ Candidature envoyée!"
  [Draft Proposal]   → show CV preview + proposal text with [✅ Approve & Submit] [❌ Reject]
  [✅ Approve & Submit] → submit stored draft → "✅ Candidature envoyée!"
  [❌ Reject]         → mark rejected, clear buttons
```

---

## Files created

| File | Purpose |
|------|---------|
| `openclaw/scrapers/freework_submitter.py` | `FreeWorkSubmitter` Playwright class + CLI |
| `data/resumes/java-backend.pdf` | Placeholder CV — replace with real PDF |
| `data/resumes/iam-sso.pdf` | Placeholder CV — replace with real PDF |
| `data/resumes/enterprise-architect.pdf` | Placeholder CV — replace with real PDF |
| `data/resumes/api-security.pdf` | Placeholder CV — replace with real PDF |
| `data/resumes/cloud-migration.pdf` | Placeholder CV — replace with real PDF |
| `alembic/versions/349bca546cc4_add_submissions_table.py` | DB migration for `submissions` table |

## Files modified

| File | Change |
|------|--------|
| `openclaw/models/domain.py` | Added `SubmissionResult` dataclass; `source_url` field on `Opportunity`; `file_path` field on `ResumeVariant` |
| `openclaw/models/storage.py` | Added `SubmissionRecord` ORM model |
| `openclaw/db/repository.py` | Stores `source_url` in `payload` dict on upsert |
| `openclaw/scrapers/freework.py` | Sets `source_url=url` on `Opportunity` in `_scrape_mission_detail()` |
| `openclaw/services/resume_selector.py` | Added `file_path` to all 5 `DEFAULT_RESUME_VARIANTS` entries |
| `openclaw/bot/handlers.py` | Revised `_handle_draft()`, `_handle_approve()`; new `_handle_approve_submit()`, `_handle_reject_draft()`; new callback routing |
| `Makefile` | Added `freework-submit-test` target |

---

## How the submission flow works

### "Draft Proposal" button

1. Status → `"drafting"`; original alert buttons removed
2. "Génération en cours..." reply sent immediately
3. `generate_proposal()` called in executor (Gemini, retrieval + adaptation)
4. `ProposalDraftRecord` saved to DB
5. **Two preview messages sent**, each with `[✅ Approve & Submit]` `[❌ Reject]` buttons:
   - **CV preview**: selected `ResumeVariant` name + rationale
   - **Proposal preview**: full generated text (truncated to 4096 chars)

### "Approve & Submit" button (after draft)

1. Loads `OpportunityRecord` + latest `ProposalDraftRecord` from DB
2. Retrieves `source_url` from `payload`
3. Looks up `ResumeVariant.file_path` from `DEFAULT_RESUME_VARIANTS`
4. Calls `FreeWorkSubmitter.submit_application(mission_url, proposal_text, resume_file_path)`
5. On success → status `"submitted"`, `SubmissionRecord` inserted, reply "✅ Candidature envoyée!"
6. On failure → error reply, status stays `"approved"` (retry possible)

### "Approve" button (direct, no draft)

Same as above but generates the proposal silently in the same handler before submitting.

### `FreeWorkSubmitter` internals

**Important discovery:** Free-Work does NOT use a cover letter form. Clicking "Postuler"
opens the platform's **internal inbox/messaging drawer**. Applications are sent as a message
to the recruiter. The CV stored in the user's profile is used automatically — no file upload.

**Prerequisite:** The Free-Work profile must be complete (run `make freework-onboarding` once
to upload your CV and fill in personal/professional info). Without a complete profile, clicking
Postuler redirects to `/fr/onboarding` and the automation returns an error.

1. Launches persistent Playwright context at `data/playwright/freework` (already logged in)
2. Navigates to `mission_url`; detects login/onboarding redirect → returns descriptive error
3. Clicks "Postuler" button — this opens the inbox messaging drawer
4. Waits for the inbox drawer to appear (selector: `.inbox-threadlist-head`)
5. Finds the message composer textarea in the drawer
6. Fills with `proposal_text`
7. If `dry_run=True`: stops here — message composed but not sent
8. Otherwise: clicks "Envoyer", waits for confirmation
9. Returns `SubmissionResult(success=True/False, ...)`

Note: `resume_file_path` is accepted for API compatibility but not used — Free-Work reads
the CV from the user's profile directly.

---

## How to add real CV files

Replace the placeholder files in `data/resumes/`:

```
data/resumes/java-backend.pdf          ← Java/Spring backend CV
data/resumes/iam-sso.pdf               ← IAM/SSO/Keycloak CV
data/resumes/enterprise-architect.pdf  ← Enterprise architect CV
data/resumes/api-security.pdf          ← API security CV
data/resumes/cloud-migration.pdf       ← Cloud/K8s migration CV
```

The `ResumeMatch` engine selects the right file automatically based on mission keywords.
No code changes needed — just replace the file content.

---

## How to run

### Dry-run form inspection (first time)

```bash
make freework-submit-test URL="https://www.free-work.com/fr/tech-it/developpeur-java-kotlin-groovy-scala/job-mission/tech-lead-java-283"
```

Opens browser with existing session, navigates to mission, fills form, **does not submit**.
Use this to confirm selectors work and the session is valid before any real submission.

### Full stack

```bash
# Terminal 1
make db-up

# Terminal 2
make bot

# Terminal 3
make monitor
```

### Test the full flow

1. Lower `alert_score_from: 60` in `config/job_criteria.yml`
2. Clear the DB: `DELETE FROM opportunities;`
3. Run monitor — wait for a Telegram alert
4. Tap **"Draft Proposal"** → review CV preview + proposal
5. Tap **"✅ Approve & Submit"** → confirm "Candidature envoyée!"
6. Check Free-Work "Mes candidatures" for the new application
7. Verify DB: `SELECT * FROM submissions;`

---

## DB schema additions

### `submissions` table

| Column | Type | Notes |
|--------|------|-------|
| `id` | serial PK | |
| `opportunity_id` | int FK → opportunities | indexed |
| `proposal_draft_id` | int FK → proposal_drafts | nullable |
| `platform` | varchar(64) | e.g. `"free-work"` |
| `mission_url` | varchar(512) | the applied-to URL |
| `confirmation_url` | varchar(512) | nullable, post-submit URL |
| `success` | bool | |
| `error_message` | text | nullable, populated on failure |
| `submitted_at` | timestamptz | |

---

## Key design decisions

| Decision | Rationale |
|---|---|
| `source_url` on `Opportunity` domain object | URL is available at scrape time; storing in `payload` avoids a DB column while making it retrievable in handlers |
| Reuse `data/playwright/freework` profile | Submitter shares session with scraper — no second login needed |
| `dry_run=True` mode | Lets you inspect the live form with real session before committing to actual submission |
| `success=True` with `error="dry_run=True"` | Distinguishes intentional dry-run from actual success at the return value level |
| CV upload skipped if file is empty | Placeholder files exist but have size 0 — submitter detects this and skips upload gracefully |
| Status stays `"approved"` on submission failure | User can retry; failed `SubmissionRecord` is still inserted for audit |

---

## What is deferred

- **Free-Work profile completion**: The user must manually complete their Free-Work profile once
  via `make freework-onboarding` (upload CV + fill personal/professional info). Without this,
  Postuler redirects to `/fr/onboarding` and automation cannot proceed.
- **Inbox composer selector verification**: After profile completion, `make freework-submit-test`
  must be run to confirm `MESSAGE_COMPOSER_SELECTORS` correctly target the inbox message textarea.
  The selectors cover the most likely patterns; adjust if needed.
- **Malt and LeHibou submission**: Only Free-Work is supported in Phase 6. Other platforms will
  need separate submitter classes once their apply flows are mapped.
- **pgvector semantic retrieval**: Proposal example matching is still keyword-based (Phase 7).
- **Outcome tracking**: Win/loss recording for submitted applications (Phase 7).
