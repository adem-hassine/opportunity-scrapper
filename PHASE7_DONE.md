# Phase 7 — Telegram UX Revamp: Implementation Summary

## What was implemented

Phase 7 replaces the original Telegram button flow with a clearer, more user-friendly experience.

**Before:**
- "Approve" silently generated and submitted — user had no idea what was sent
- "Draft Proposal" sent two separate messages (CV + proposal) each with duplicate buttons — 4 buttons for one decision
- No way to regenerate without rejecting the whole opportunity
- Confirmation showed no content from the submission

**After:**
- Three distinct, clearly-labelled alert buttons with obvious intent
- Single combined preview message (CV + proposal together) with three focused action buttons
- In-place regeneration — edit same message without clutter
- Rich confirmation showing mission title + proposal snippet

---

## Files modified

| File | Change |
|------|--------|
| `openclaw/services/telegram.py` | Rewrote `TelegramAction` enum with 6 new actions; updated `default_decision_buttons()` to new labels; added `build_preview_message()` and `preview_action_buttons()` |
| `openclaw/bot/handlers.py` | Full rewrite — renamed/replaced all handlers; added `_handle_regenerate()`; added `_reply_submission_result()` and `_persist_submission()` helpers; removed `send_opportunity_alert()` (no longer needed) |
| `openclaw/bot/sender.py` | Updated `_send()` to build keyboard from `packet.telegram_buttons` dynamically (no hardcoded labels) |

---

## New flow

### 1. Alert message buttons

```
[⚡ Quick Apply]  [📝 Review & Apply]  [✗ Reject]
```

| Button | Behaviour |
|--------|-----------|
| ⚡ Quick Apply | Generates proposal silently + submits immediately; shows rich confirmation |
| 📝 Review & Apply | Generates proposal + shows combined preview with action buttons |
| ✗ Reject | Marks rejected, removes buttons |

### 2. Combined preview message

```
📋 TECH LEAD JAVA — PARTECK INGENIERIE

📄 CV : IAM / SSO Expert
Matched: keycloak, oauth2

──────────────────────
Bonjour, je suis consultant Java/IAM avec 10 ans
d'expérience sur Keycloak et les architectures SSO...
(1842 chars total)
──────────────────────

[✅ Envoyer]  [🔄 Regénérer]  [✗ Rejeter]
```

| Button | Behaviour |
|--------|-----------|
| ✅ Envoyer | Submits the stored draft |
| 🔄 Regénérer | Edits the message in-place with a new generated proposal |
| ✗ Rejeter | Marks rejected, removes buttons |

### 3. Confirmation messages

**Success:**
```
✅ Candidature envoyée — TECH LEAD JAVA
📋 "Bonjour, je suis consultant Java/IAM avec 10 ans…"
```

**Failure:**
```
❌ Échec — TECH LEAD JAVA
{error details}
Statut conservé à 'approved' — retappez ✅ Envoyer pour réessayer.
```

---

## Callback routing table

| Callback prefix | Handler | Triggered by |
|---|---|---|
| `quick_apply` | `_handle_quick_apply` | ⚡ Quick Apply on alert |
| `review` | `_handle_review` | 📝 Review & Apply on alert |
| `reject` | `_handle_reject` | ✗ Reject on alert |
| `send` | `_handle_send` | ✅ Envoyer on preview |
| `regenerate` | `_handle_regenerate` | 🔄 Regénérer on preview |
| `reject_preview` | `_handle_reject_preview` | ✗ Rejeter on preview |

---

## Key design decisions

| Decision | Rationale |
|---|---|
| Single preview message instead of two | Reduces notification noise; one decision = one message |
| Edit in-place for Regénérer | Keeps chat clean — no accumulation of old previews |
| `_persist_submission()` extracted | Both `_handle_quick_apply` and `_handle_send` share the same DB write logic |
| `_reply_submission_result()` extracted | Consistent confirmation format across both submit paths |
| `sender.py` builds keyboard from `telegram_buttons` | Decoupled — button labels defined in `telegram.py`, not duplicated in `sender.py` |

---

## How to verify end-to-end

```bash
# 1. Start the stack
make db-up
make bot       # terminal 2
make monitor   # terminal 3

# 2. Lower the alert threshold and reset a row
# In config/job_criteria.yml: alert_score_from: 60
# In DB: UPDATE opportunities SET status='new' WHERE id=<id>;

# 3. Watch for Telegram alert — verify 3 new buttons appear

# 4. Tap 📝 Review & Apply → verify ONE combined message with CV + proposal + 3 buttons

# 5. Tap 🔄 Regénérer → verify message updates in-place with new proposal

# 6. Tap ✅ Envoyer → verify confirmation shows mission title + proposal snippet

# 7. Tap ⚡ Quick Apply on a fresh alert → verify silent generation + submission + rich confirmation

# 8. Tap ✗ Reject / ✗ Rejeter at any stage → verify status = 'rejected' in DB
```
