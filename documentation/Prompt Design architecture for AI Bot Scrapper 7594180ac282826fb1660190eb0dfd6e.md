# Prompt: Design architecture for AI Bot Scrapper

What you're describing is a very strong and realistic architecture for OpenClaw.

This is much better than "fully autonomous bidding."

You're building an AI-assisted freelance operating system with:

- intelligent filtering
- proposal drafting
- human approval
- automated submission
- reusable positioning assets

That is exactly the right level of automation for platforms like:

- Malt
- Free-Work
- LeHibou
- Freelance Informatique

because it avoids spam behavior and keeps proposal quality high.

---

## Current implementation status (2026-06-15)

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 — DB | ✅ Done | PostgreSQL + pgvector, Alembic migrations, repository layer |
| Phase 2 — Telegram bot | ✅ Done | Alerts with inline buttons, callback handlers |
| Phase 3 — Monitor loop | ✅ Done | 15-min scrape cycle, deduplication, alert routing |
| Phase 4 — Proposal generation | ✅ Done | Gemini 2.0 Flash, retrieval + adaptation, CV selection |
| Phase 5 — LeHibou scraper | ✅ Done | Playwright + Cloudflare stealth, persistent profile |
| Phase 6 — Automated submission | 🔄 In progress | Free-Work Playwright submitter, full end-to-end flow |
| Malt scraper | ⏳ Deferred | Requires authenticated session |

---

## Architecture (updated)

Your ideal architecture is:

```
Platform Monitoring (Free-Work / LeHibou / Malt)
    ↓
Hard Filtering (eliminatory rules)
    ↓
AI Qualification + Scoring
    ↓
Telegram Alert
    [Approve]  [Reject]  [Draft Proposal]
    ↓ (Draft Proposal)
AI Proposal Generation (Gemini — retrieval + adaptation)
    ↓
CV Selection (ResumeVariant engine)
    ↓
Telegram Preview
  ├── CV preview (selected variant + key bullets)
  └── Proposal text
       [✅ Approve & Submit]  [❌ Reject]
    ↓ (Approve & Submit)
Automated Submission (Playwright — fills form, uploads CV, confirms)
    ↓
Confirmation in Telegram + DB record
```

**Key change from original design:** The "Human Approval" step now comes *after* reviewing the AI-generated proposal and CV, not before. Tapping "Approve & Submit" directly triggers submission — no manual browser step.

---

## V1 Scope (6 components)

### 1. Multi-Platform Monitoring

**Goal:** Continuously watch freelance platforms.

**Suggested stack:**
- Playwright
- Python
- Headless Chromium (headful for Cloudflare-protected sites like LeHibou)
- Persistent browser profiles per platform

**Platforms:**
1. Free-Work ✅
2. LeHibou ✅ (Cloudflare Turnstile — headful + stealth required)
3. Malt ⏳ (requires authenticated session — deferred)

---

### 2. Eliminatory Filtering (Critical)

This is the highest-value component.

Hard filters defined in `config/job_criteria.yml`:

```yaml
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

**Scoring logic:**

| Signal | Score |
|--------|-------|
| Remote | +30 |
| Hybrid Paris | +10 |
| Full onsite | reject |
| TJM > 700 | +25 |
| Java/Spring | +20 |
| Keycloak/OAuth2 | +20 |
| Banking sector | +15 |
| Legacy Java 8 only | −10 |

Routes:
- `reject` — score below 45 → dropped silently
- `review` — score 45–74 → persisted, no Telegram alert
- `alert` — score ≥ 75 → Telegram alert fired

---

### 3. Telegram Approval Workflow

**Telegram alert message:**

```
NEW OPPORTUNITY
Platform: Free-Work
TJM: 750€
Remote: 4d remote
Client: Banking
Stack: Java 21, Spring Boot, Keycloak, Kubernetes
Score: 91/100

[Approve]  [Reject]  [Draft Proposal]
```

**After clicking "Draft Proposal":**

OpenClaw:
1. Retrieves similar past proposals (keyword overlap)
2. Selects best matching CV variant
3. Generates proposal (Gemini, retrieval + adaptation)
4. Sends two preview messages:
   - **CV preview** — selected variant name, rationale, key bullets
   - **Proposal preview** — full generated text
   - Both have **[✅ Approve & Submit]** and **[❌ Reject]** buttons

**After clicking "Approve & Submit":**

OpenClaw:
1. Loads proposal text + resume file path from DB
2. Launches Playwright with the Free-Work persistent session
3. Navigates to the mission, fills the application form
4. Uploads the CV, submits
5. Sends confirmation: "✅ Candidature envoyée sur Free-Work!"
6. Updates opportunity status to `"submitted"` in DB

The user can also tap **"Approve"** on the *original alert* (before drafting) if they want to skip the draft step — this was preserved for speed.

---

### 4. Proposal Memory System

This is the real moat.

**Past proposals stored in `data/proposal_examples/`:**

```markdown
---
title: IAM/SSO Banking Mission
client_type: grand_compte
industry: banking
tone: enterprise
stack_keywords: ["java", "keycloak", "oauth2"]
outcome_status: won
---

Bonjour, [proposal text...]
```

**Outcome tracking** (Phase 7):
- Store: response? / interview? / won? / rejected?
- Over time OpenClaw learns which proposal styles convert best

---

### 5. Multi-Resume Intelligence

Maintain multiple CVs mapped to `ResumeVariant` objects:

| Resume key | Best For | File |
|-----------|----------|------|
| `java-backend` | Generic backend missions | `data/resumes/java-backend.pdf` |
| `iam-sso` | Keycloak/Auth0/Okta | `data/resumes/iam-sso.pdf` |
| `enterprise-architect` | Large accounts | `data/resumes/enterprise-architect.pdf` |
| `api-security` | Banking/security | `data/resumes/api-security.pdf` |
| `cloud-migration` | AWS/K8s modernization | `data/resumes/cloud-migration.pdf` |

**Resume selection engine** (`openclaw/services/resume_selector.py`):
1. Analyze mission stack keywords
2. Score each variant by keyword overlap
3. Return best match + rationale string
4. `ResumeVariant.file_path` points to the actual PDF for upload

Example:
```
Detected: OAuth2, SAML, Keycloak
→ select "iam-sso" variant → upload data/resumes/iam-sso.pdf
```

---

### 6. Human Validation Before Submission

This is non-negotiable.

The flow:

```
AI prepares everything (proposal + CV selection)
    ↓
Human reviews preview in Telegram (proposal text + CV name)
    ↓
Human taps "Approve & Submit"
    ↓
Automated submission fires
```

The user stays:
- compliant with platform ToS (human-approved content)
- high-quality (reviewed before sending)
- in control (can reject at any point)

---

## Technical Architecture

**Backend:** Python, FastAPI

**Scraping + Submission:** Playwright, persistent browser profiles per platform

**Storage:** PostgreSQL + pgvector

Tables:
- `opportunities`
- `proposal_drafts`
- `submissions` ← new in Phase 6
- `proposal_examples`
- `outcomes` (Phase 7)

**AI Layer:** Gemini 2.0 Flash via OpenAI-compatible API, keyword-based retrieval (pgvector semantic search in Phase 7)

**Messaging:** Telegram Bot API (python-telegram-bot)

---

## Critical Feature: Similarity Retrieval

Before generating a proposal, OpenClaw retrieves:
- similar mission stack
- similar industry
- similar successful proposal text

Then adapts from that — outperforms cold generation significantly.

**Prompting strategy:**

```
SYSTEM:
Tu es un expert en adaptation de propositions commerciales freelance.
Tu reçois une proposition existante réussie et une offre de mission.
Adapte la proposition à la nouvelle offre en conservant le ton et la structure.
Réponds uniquement avec le texte de la proposition, sans commentaires.

INPUTS:
- Offre de mission (titre, stack, TJM, remote, résumé)
- Proposition de référence (meilleur match par keywords)
- Profil CV sélectionné (nom + rationale)
- Ton souhaité (enterprise / consultative / technical)

TASK:
Générer une proposition personnalisée et concise en français.
```

---

## Revised Timeline

| Phase | Status | Deliverable |
|-------|--------|-------------|
| Phase 1 | ✅ Done | DB persistence, deduplication |
| Phase 2 | ✅ Done | Telegram alerts + button callbacks |
| Phase 3 | ✅ Done | Unattended monitor loop |
| Phase 4 | ✅ Done | AI proposal generation, CV selection |
| Phase 5 | ✅ Done | LeHibou scraper |
| **Phase 6** | 🔄 Now | Automated submission on Free-Work (full end-to-end) |
| Phase 7 | Next | Tests, hardening, outcome tracking |
| Post-V1 | Later | Malt scraper, pgvector retrieval, Freelance Informatique |

---

## Most Important Advice

Do NOT try to:
- auto-send proposals **without human review**
- automate conversations with clients
- spam platforms

The real leverage is:
- identifying high-quality missions quickly
- generating excellent personalized drafts
- selecting the best resume automatically
- **submitting automatically after human approval** — no browser required
- reducing the full apply workflow from 30 min → **3 min of Telegram review**

That is where OpenClaw becomes genuinely valuable.
