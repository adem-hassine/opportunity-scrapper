# OpenClaw — What It Is, How It Works, How It Will Be Used

---

## What problem it solves

As a freelance Java/IAM consultant, you spend 20–30 minutes per proposal: reading the mission, deciding if it fits, choosing which CV to send, writing a personalized text. Multiply that by the number of platforms you monitor daily and it becomes a serious time drain — most of it on missions that never deserved your attention in the first place.

OpenClaw eliminates that waste. It watches the platforms for you, throws away everything that doesn't match your criteria before you ever see it, scores what remains, and — for the good ones — prepares a draft proposal with the right CV already selected. Your job shrinks to reading a Telegram message and tapping Approve.

**The goal is not automation. The goal is leverage.** You stay in control of every send. OpenClaw just makes each decision take 3 minutes instead of 30.

---

## The full pipeline

```
Freelance platforms (Free-Work, Malt, LeHibou)
        │
        │  Playwright scraper runs every 15 min
        ▼
 ┌─────────────────────────────┐
 │   Hard filtering             │  ← eliminatory rules: TJM, remote, keywords
 │   (instant reject or pass)  │
 └────────────┬────────────────┘
              │ passes
              ▼
 ┌─────────────────────────────┐
 │   Scoring engine             │  ← adds/subtracts points per signal
 │   score 0–100               │
 └────────────┬────────────────┘
              │
        ┌─────┴──────┐
      < 45          ≥ 75
     REJECT        ALERT ──────► Telegram alert sent to you
                     │
              45–74: REVIEW (buffered, not alerted)
                     │
        ┌────────────▼──────────────┐
        │   You see on Telegram:    │
        │                           │
        │  NEW OPPORTUNITY          │
        │  Platform: Free-Work      │
        │  TJM: 750 EUR             │
        │  Remote: Fully remote     │
        │  Client: BNP Paribas      │
        │  Stack: Java, Keycloak... │
        │  Score: 91/100            │
        │  Suggested CV: IAM/SSO    │
        │                           │
        │  [Approve] [Reject]       │
        │  [Draft Proposal]         │
        └───────────┬───────────────┘
                    │
          ┌─────────┼──────────┐
       Approve    Reject    Draft Proposal
          │         │            │
       Mark      Archive    Retrieve similar
       approved  mission    past proposals
                            + best CV
                            + generate draft
                            → reply with text
                                  │
                             You read it,
                             edit if needed,
                             tap Approve
                                  │
                             Submitted ✓
```

---

## The 8 components

### 1. Platform scraper
Runs Playwright (a real browser, headless by default) to open Free-Work, navigate mission listings, visit each mission page, and extract: title, client, location, TJM, remote mode, tech stack keywords, industry, and publication date.

It uses a **persistent browser session** per platform (`data/playwright/freework/`), so accepted cookies and future logins survive across runs. No credentials are stored in the code.

Currently implemented: **Free-Work**. Planned: Malt, LeHibou, Freelance Informatique.

---

### 2. Hard filtering
Before any scoring happens, a set of **eliminatory rules** immediately reject missions that can never be a fit:

| Rule | Default value |
|---|---|
| Minimum TJM | 650 EUR/day |
| Remote required | Yes |
| Excluded keywords | wordpress, php, onsite only |
| Required keywords | at least one of: java, spring, sso, keycloak |

A mission that hits any of these walls is discarded silently. It never reaches Telegram. This is the most valuable component — it keeps the signal-to-noise ratio high.

All rules live in `config/job_criteria.yml` and can be changed without touching code.

---

### 3. Scoring engine
Missions that pass hard filtering are scored 0–100 based on how well they match your ideal profile:

| Signal | Points |
|---|---|
| Fully remote | +30 |
| Hybrid Paris / Île-de-France | +10 |
| TJM ≥ 700 EUR | +25 |
| Java + Spring | +20 |
| Keycloak / OAuth2 / SSO / SAML | +20 |
| Banking / finance sector | +15 |
| Legacy Java 8 / maintenance / TMA | −10 |

**Routing:**
- Score < 45 → auto-reject (no Telegram noise)
- Score 45–74 → buffered for manual review
- Score ≥ 75 → Telegram alert sent immediately

---

### 4. Telegram alert
For every ALERT-routed mission you receive a Telegram message with:
- Platform, TJM, remote mode, client, industry
- Full tech stack as a keyword list
- Score out of 100
- Which CV OpenClaw recommends for this mission
- Three inline buttons: **Approve**, **Reject**, **Draft Proposal**

This is your entire decision surface. You don't need to open a browser or visit the platform.

---

### 5. CV selection engine
OpenClaw maintains 5 resume profiles and automatically picks the best one per mission based on keyword and industry matching:

| CV | Best for |
|---|---|
| Java Backend | Generic Java/Spring missions |
| IAM / SSO Expert | Keycloak, OAuth2, SAML, Auth0, Okta |
| Enterprise Architect | Large accounts, modernization programs |
| API Security | Banking/security, zero-trust, API gateway |
| Cloud Migration | AWS/Azure/GCP, Kubernetes, modernization |

Example: a mission mentioning Keycloak + OAuth2 + banking → automatically selects **IAM/SSO Expert**.

In V1 the selection is rule-based. Post-V1 it can be improved with historical conversion data (which CV won more interviews).

---

### 6. Proposal generation (Phase 4 — not yet built)
When you tap **Draft Proposal**, OpenClaw:
1. Retrieves your 3 most similar past successful proposals from the database (matched by stack and industry)
2. Takes the selected CV's summary
3. Sends everything to OpenAI with this prompt structure:

```
SYSTEM: You are adapting an existing successful freelance proposal.
INPUTS:
  - The job offer (title, stack, client, rate, remote mode)
  - A similar successful proposal (retrieved from database)
  - The selected resume summary
  - Preferred tone: enterprise / consultative / technical
TASK: Generate a concise personalized proposal in French.
```

This is **retrieval + adaptation**, not generation from scratch. It produces better results because it reuses proven language from your own past wins and adapts it to the new context.

The draft is sent back to Telegram as a reply. You read it, optionally edit, then tap Approve to submit.

---

### 7. Proposal memory system
Every proposal you send — and its outcome (response received / interview / won / rejected) — is stored in the database. Over time this becomes your moat:
- OpenClaw learns which proposal styles convert in banking vs. insurance
- It learns which tone wins more interviews per industry
- Each new draft is anchored to your actual track record, not generic templates

Tables: `opportunities`, `proposal_examples`, `proposal_drafts`, `outcomes`.

---

### 8. Human approval gate
**Nothing is ever sent without your explicit tap.**

The architecture is designed so that:
- AI prepares everything (scraping, filtering, scoring, CV selection, draft)
- You make every final call (approve, reject, edit)

This keeps you compliant with platform rules, keeps proposal quality high, and keeps you in full control of your positioning. OpenClaw is a decision-support tool, not an autonomous agent.

---

## Daily usage — what your day looks like

**Without OpenClaw:**
- Open 3 platforms manually
- Scroll through 40–60 missions
- Read each one, decide fit, write proposal
- ~3 hours/week minimum

**With OpenClaw (current state — scraper + filtering + scoring):**
```bash
make freework-smoke ARGS='--from-date=2026-06-12'
```
Prints a JSON list of qualified missions with scores. You read the output and decide manually.

**With OpenClaw (after Phase 2 — Telegram bot live):**
- You receive a Telegram message for each qualifying mission
- You tap Approve / Reject / Draft Proposal directly from your phone
- No terminal, no browser needed

**With OpenClaw (after Phase 4 — proposal generation live):**
- Telegram alert arrives
- You tap Draft Proposal
- 10 seconds later: a personalized proposal appears in the same chat
- You read it, optionally tweak, tap Approve
- Done in under 3 minutes per mission

**With the scheduled digest (planned):**
- Every morning at 8:00 a summary of the day's new missions arrives in Telegram
- Each entry shows TJM, remote mode, score, and a direct link to the mission page
- You scan it over coffee, tap on anything interesting, proceed from there

---

## What is built today vs. what is coming

| Capability | Status |
|---|---|
| Free-Work Playwright scraper | **Done** |
| Hard filtering engine | **Done** |
| Scoring engine | **Done** |
| CV selection (rule-based) | **Done** |
| Telegram message formatting | **Done** (messages built, not sent yet) |
| FastAPI qualification preview endpoint | **Done** |
| PostgreSQL schema (all tables) | **Done** (tables defined, not yet written to) |
| Database persistence + deduplication | Phase 1 — next |
| Live Telegram bot (send + receive buttons) | Phase 2 |
| Continuous monitor loop (every 15 min) | Phase 3 |
| Proposal generation with OpenAI | Phase 4 |
| Morning digest sender script | Phase 4 |
| Malt scraper | Phase 5 |
| LeHibou scraper | Phase 5 |
| Freelance Informatique scraper | Post-V1 |

---

## Who controls what

| Action | Who does it |
|---|---|
| Scraping platforms | OpenClaw (automated) |
| Filtering junk missions | OpenClaw (automated) |
| Scoring what remains | OpenClaw (automated) |
| Sending Telegram alerts | OpenClaw (automated) |
| Selecting the best CV | OpenClaw (automated) |
| Drafting a proposal | OpenClaw (AI-assisted) |
| Approving / rejecting missions | **You** |
| Editing the draft | **You** |
| Final submission | **You** (after explicit approval) |

The automation boundary is intentional. Platforms penalize spam behavior. Your conversion rate depends on proposal quality. Keeping you in the loop on every send is not a limitation — it is the design.
