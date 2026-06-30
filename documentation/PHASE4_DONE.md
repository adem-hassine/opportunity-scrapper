# Phase 4 — Proposal Generation: Implementation Summary

## What was implemented

Tapping "Draft Proposal" in Telegram now generates a real, personalised freelance proposal using **Gemini 2.0 Flash** (via the OpenAI-compatible API) and replies directly in the chat. The draft is also persisted in the `proposal_drafts` DB table.

Generation strategy: **retrieval + adaptation** — the system finds the closest matching past proposal from `data/proposal_examples/` by stack keyword overlap, then instructs Gemini to adapt it to the specific job offer. This produces consistent, natural-sounding proposals rather than cold-generated text.

---

## Files created

| File | Purpose |
|------|---------|
| `openclaw/services/proposal_generator.py` | Core generation logic: load examples, retrieve best match, build prompt, call Gemini |
| `scripts/seed_examples.py` | Parse `data/proposal_examples/*.md`, upsert into `proposal_examples` DB table |
| `data/proposal_examples/java-backend-banque.md` | Example proposal — Java/Spring backend, banking |
| `data/proposal_examples/iam-sso-keycloak.md` | Example proposal — IAM/SSO, Keycloak, banking |
| `data/proposal_examples/api-security-gateway.md` | Example proposal — API security, Zero Trust |

## Files modified

| File | Change |
|------|--------|
| `openclaw/bot/handlers.py` | Replaced `_handle_draft()` stub with real generation + Telegram reply + DB persistence |
| `Makefile` | Added `seed-examples` target |

---

## How generation works

1. **Button tap** — user taps "Draft Proposal" on a Telegram alert
2. **Status update** — opportunity status set to `"drafting"` in DB; buttons removed from message
3. **Feedback** — "Génération de la proposition en cours..." sent immediately so user knows it's working
4. **Opportunity reconstruction** — `OpportunityRecord.payload` is parsed back into an `Opportunity` domain object; re-qualified to get `resume_match` and `memory_query`
5. **Example retrieval** — `data/proposal_examples/*.md` files are scanned; each is scored by keyword overlap with `memory_query.stack_keywords` (+2 per match) and industry alignment (+3). Best-matching example is used as reference
6. **Prompt assembly** — system prompt (fixed, French) + user message with: job details, reference proposal, selected CV profile, preferred tone
7. **Gemini call** — synchronous `openai.OpenAI` call run in executor so it doesn't block the bot event loop; `max_tokens=1024`, `temperature=0.7`
8. **Persistence** — `ProposalDraftRecord` inserted with the generated text, resume key, and tone
9. **Reply** — draft text replied in Telegram (truncated to 4096 chars if needed)

---

## Prompt format

**System message:**
> Tu es un expert en adaptation de propositions commerciales freelance.
> Tu reçois une proposition existante réussie et une offre de mission.
> Adapte la proposition à la nouvelle offre en conservant le ton et la structure, mais en personnalisant le contenu.
> Réponds uniquement avec le texte de la proposition, sans commentaires ni balises.

**User message sections:**
- `## Offre de mission` — title, client, TJM, remote mode, keywords, summary
- `## Proposition de référence` — best matching example text (or "Aucune proposition similaire disponible.")
- `## Profil CV sélectionné` — resume label + rationale
- `## Ton souhaité` — `enterprise` (banking/security/architecture) or `consultative`

---

## How to add more proposal examples

1. Create a `.md` file in `data/proposal_examples/` with this frontmatter:

```markdown
---
title: Your Proposal Title
client_type: grand_compte
industry: banking
tone: enterprise
stack_keywords: ["java", "spring", "microservices"]
outcome_status: won
---

Bonjour,

[proposal text here...]
```

2. Run `make seed-examples` to load it into the DB.

The generator reads files directly — **no need to seed** for generation to work. Seeding populates the DB table for future analytics/pgvector search.

---

## How to run and verify

**Setup (first time):**
```bash
make seed-examples   # loads 3 examples into DB
```

**Full stack:**
```bash
# Terminal 1
make db-up

# Terminal 2
make bot

# Terminal 3
make monitor
```

**Test the draft flow:**
1. Wait for a Telegram alert (or lower `alert_score_from: 60` in `config/job_criteria.yml` and clear the DB)
2. Tap **"Draft Proposal"**
3. Within ~5 seconds: see "Génération en cours..." then the proposal text

**Verify in DB:**
```sql
-- Check the draft was persisted
SELECT id, opportunity_id, resume_key, status, LEFT(proposal_text, 100) FROM proposal_drafts;

-- Check opportunity status updated
SELECT id, status FROM opportunities WHERE status = 'drafting';
```

---

## Settings used (already in `.env`)

| Variable | Value |
|----------|-------|
| `OPENAI_API_KEY` | Your Gemini API key |
| `OPENAI_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| `OPENAI_MODEL` | `gemini-2.0-flash` |

No new environment variables needed.

---

## What is deferred to later phases

- **Phase 5**: Malt and LeHibou scrapers
- **Phase 6**: pgvector semantic retrieval for examples (currently keyword-based file scan)
- **Phase 6**: Outcome tracking — marking proposals as won/lost to improve future retrieval
