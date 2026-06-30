# OpenClaw — Full Implementation Plan

## Context

OpenClaw is an AI-assisted freelance opportunity monitor. The scraping, filtering, scoring, and message-formatting layers are complete. What is missing is everything that makes it run unattended and talk back: database persistence, a live Telegram bot, a continuous monitor loop, proposal generation, and automated application submission. This plan sequences those pieces in dependency order so each step is immediately testable before the next begins.

**Current status (as of 2026-06-15):**
- Phases 1–5 are complete (Free-Work scraper, DB persistence, Telegram bot, monitor loop, proposal generation, LeHibou scraper).
- **Active focus: Phase 6 — Automated submission on Free-Work.** The flow described in Phase 4 is being extended so that "Approve" after reviewing a draft triggers an actual platform submission, not a manual step.

---

## Phase 1 — Database foundation ✅ DONE

**Goal:** Opportunities discovered by the scraper are persisted and deduplicated.

See `PHASE1_DONE.md` for full implementation details.

---

## Phase 2 — Telegram bot process ✅ DONE

**Goal:** Qualified opportunities appear in Telegram with action buttons. Tapping a button updates the DB.

See `PHASE2_DONE.md` for full implementation details.

---

## Phase 3 — Continuous monitor loop ✅ DONE

**Goal:** The system runs unattended, scraping every 15 minutes and alerting on new ALERT-routed opportunities.

See `PHASE3_DONE.md` for full implementation details.

---

## Phase 4 — Proposal generation ✅ DONE (revised scope below)

**Goal:** Tapping "Draft Proposal" generates a tailored proposal and shows both the draft text and the selected CV in Telegram, so the user can review before approving.

> **Scope revision (2026-06-15):** The original Phase 4 ended with the draft text sent as a Telegram reply. The revised flow adds a CV preview step and wires "Approve" to trigger automatic submission (implemented in Phase 6). The generation code itself is unchanged; only the Telegram UX and the Approve handler are extended.

### What the revised "Draft Proposal" flow looks like

1. User taps **"Draft Proposal"** on a Telegram alert.
2. Bot replies with two messages in sequence:
   - **Message A — CV preview:** "📄 CV sélectionné: IAM/SSO Expert — *rationale*"
     followed by the key CV bullet points (from the selected `ResumeVariant`).
   - **Message B — Proposal preview:** the full generated proposal text.
   - Both messages end with two inline buttons: **[✅ Approve & Submit]** and **[❌ Reject]**.
3. The user can approve **from either message** (or skip reading and tap Approve immediately).
4. Tapping **"Approve & Submit"** triggers Phase 6 (automated submission).
5. Tapping **"Reject"** marks the opportunity as `"rejected"` and removes the buttons.

### What was already implemented (unchanged from original Phase 4)

- `openclaw/services/proposal_generator.py` — retrieval + adaptation generation via Gemini
- `scripts/seed_examples.py` — seeds `data/proposal_examples/` into DB
- `ProposalDraftRecord` persistence

### What needs to change for the revised flow (done in Phase 6 prep)

- `openclaw/bot/handlers.py` — `_handle_draft()`: add CV preview message before proposal message; add `approve_submit` and `reject_draft` callback actions
- `openclaw/bot/handlers.py` — `_handle_approve_submit()`: new handler that calls the submission service (Phase 6)

See `PHASE4_DONE.md` for generation internals.

---

## Phase 5 — Additional platform scrapers ✅ DONE (LeHibou)

**Goal:** LeHibou monitored alongside Free-Work. Malt deferred.

### 5.1 `openclaw/scrapers/lehibou.py` ✅ DONE
- `LeHibouScraper` — Playwright persistent context, Cloudflare stealth, French date parsing
- Persistent session under `data/playwright/lehibou/`
- Registered in `scrapers/registry.py`

### 5.2 `openclaw/scrapers/malt.py` — DEFERRED
- Malt requires an authenticated freelancer account
- Will need persistent profile under `data/playwright/malt/` + one-time manual login
- Planned after Phase 6 is stable on Free-Work

### 5.3 Post-V1: `openclaw/scrapers/freelance_informatique.py`
- Fourth platform identified by client
- Planned after V1 is stable

See `PHASE5_DONE.md` for LeHibou implementation details.

---

## Phase 6 — Automated submission (Free-Work) ← ACTIVE

**Goal:** After the user reviews the proposal draft and CV in Telegram and taps "Approve & Submit", OpenClaw automatically submits the application on Free-Work without any manual browser interaction.

This is the core value delivery: reducing the apply workflow from 30 minutes → 3 minutes of review.

### 6.1 Research Free-Work submission flow (first step)

Before writing code, use Playwright MCP to map the exact submission flow:
- How to navigate to a mission's "Postuler" page
- What fields exist (cover letter textarea, CV selection, any other required fields)
- Whether Free-Work uses a multi-step form or a single page
- Session requirements (must be logged in — persistent Playwright profile already exists)

### 6.2 Create `openclaw/scrapers/freework_submitter.py`

```python
class FreeWorkSubmitter:
    platform = "free-work"

    async def submit_application(
        self,
        mission_url: str,
        proposal_text: str,
        resume_variant: ResumeVariant,
    ) -> SubmissionResult:
        ...
```

- Uses the same persistent Playwright profile as `FreeWorkScraper` (`data/playwright/freework/`)
- Navigates to the mission URL, clicks "Postuler"
- Fills the cover letter field with `proposal_text`
- Selects or uploads the CV file matching `resume_variant.file_path`
- Confirms and submits the form
- Returns `SubmissionResult(success=True, confirmation_url=...)` or `SubmissionResult(success=False, error=...)`

### 6.3 Add `SubmissionResult` to `openclaw/models/domain.py`

```python
@dataclass
class SubmissionResult:
    success: bool
    platform: str
    mission_url: str
    confirmation_url: str | None = None
    error: str | None = None
    submitted_at: datetime | None = None
```

### 6.4 Add `ResumeVariant.file_path` to domain model

Each `ResumeVariant` needs a pointer to the actual CV file to upload:

```python
@dataclass
class ResumeVariant:
    key: str
    label: str
    description: str
    keywords: list[str]
    file_path: str | None = None  # path to PDF/DOCX for upload, e.g. "data/resumes/iam-sso.pdf"
```

### 6.5 Wire submission into `openclaw/bot/handlers.py`

New callback action `approve_submit:{opportunity_id}`:

```python
async def _handle_approve_submit(session, opportunity_id, settings):
    # 1. Load opportunity + draft from DB
    # 2. Reconstruct Opportunity domain object from payload
    # 3. Get resume_match from re-qualification
    # 4. Load proposal text from latest ProposalDraftRecord
    # 5. Call FreeWorkSubmitter.submit_application()
    # 6a. On success: update opportunity status to "submitted"; reply "✅ Candidature envoyée!"
    # 6b. On failure: reply "❌ Échec de soumission: {error}"; status stays "approved"
```

### 6.6 Add `SubmissionRecord` to `openclaw/models/storage.py`

```python
class SubmissionRecord(Base):
    __tablename__ = "submissions"
    id: int (PK)
    opportunity_id: int (FK → opportunities)
    proposal_draft_id: int (FK → proposal_drafts)
    platform: str
    mission_url: str
    confirmation_url: str | None
    success: bool
    error_message: str | None
    submitted_at: datetime
```

### 6.7 Update Makefile

```makefile
freework-submit-test: ## Test submission on a specific mission URL (dry run)
    $(BIN)/python -m openclaw.scrapers.freework_submitter --mission-url $(URL) --dry-run
```

### 6.8 Add Alembic migration for `submissions` table

**Verification:**
1. Trigger a full flow: monitor scrapes → Telegram alert → Draft Proposal → review CV + proposal text → Approve & Submit
2. Confirm application appears in Free-Work "Mes candidatures"
3. Confirm `submissions` DB row has `success=True`
4. Confirm opportunity status is `"submitted"`

---

## Phase 7 — Test coverage and hardening

**Goal:** New code is covered; the system handles failures gracefully.

### 7.1 Tests to add
- `tests/test_repository.py` — upsert idempotency, status transitions
- `tests/test_bot_handlers.py` — callback decoding, allowlist enforcement, status dispatch, approve_submit dispatch
- `tests/test_proposal_generator.py` — prompt assembly, example retrieval (mocked OpenAI)
- `tests/test_monitor.py` — deduplication logic
- `tests/test_submitter.py` — submission flow (mocked Playwright)

### 7.2 Hardening
- Scraper errors caught and logged — never crash the monitor loop
- Bot callback errors always answer the callback (clears the Telegram spinner) even on failure
- Submission failures send a Telegram error reply and leave the opportunity in `"approved"` state so the user can retry
- Fill in `OPENAI_MODEL=gemini-2.0-flash` and `OPENAI_EMBEDDINGS_MODEL=text-embedding-004` in `.env.example`, and add `OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`

### 7.3 Post-V1: pgvector semantic retrieval
- Replace SQL `LIKE` keyword matching in proposal retrieval with pgvector embeddings
- Requires `ProposalExampleRecord.embedding` column + Alembic migration

---

## Revised pipeline diagram

```
Scraper (Free-Work / LeHibou)
    ↓
Hard Filtering + Scoring
    ↓
Telegram Alert  [Approve] [Reject] [Draft Proposal]
    ↓ (Draft Proposal tapped)
Proposal Generation (Gemini, retrieval + adaptation)
    ↓
Telegram Preview
  ├── Message A: CV preview (selected ResumeVariant + key bullets)
  └── Message B: Proposal text
       [✅ Approve & Submit]  [❌ Reject]
    ↓ (Approve & Submit tapped)
FreeWorkSubmitter (Playwright)
  → fills form, uploads CV, confirms
    ↓
Telegram confirmation "✅ Candidature envoyée!"
DB: opportunity.status = "submitted"
DB: SubmissionRecord inserted
```

---

## Dependency order

```
Phase 1 (DB + migrations) ✅
    └── Phase 2 (Telegram bot) ✅
        └── Phase 3 (Monitor loop) ✅
            └── Phase 4 (Proposal generation) ✅
                └── Phase 5 (LeHibou scraper) ✅
                    └── Phase 6 (Automated submission — Free-Work) ← NOW
                        └── Phase 7 (Tests + hardening)
                            └── Phase 5 continued (Malt scraper)
```

---

## Files to create (Phase 6)

| File | Purpose |
|---|---|
| `openclaw/scrapers/freework_submitter.py` | Playwright-based submission automation |
| Alembic migration | `submissions` table |

## Files to modify (Phase 6)

| File | Change |
|---|---|
| `openclaw/models/domain.py` | Add `SubmissionResult` dataclass; add `file_path` to `ResumeVariant` |
| `openclaw/models/storage.py` | Add `SubmissionRecord` ORM model |
| `openclaw/bot/handlers.py` | Add CV preview message to `_handle_draft()`; add `_handle_approve_submit()` |
| `Makefile` | Add `freework-submit-test` target |
| `data/resumes/` | Add actual CV PDF/DOCX files per variant |
