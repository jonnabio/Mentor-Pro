# Task T015 Result: Practice Cancellation

> **Date:** 2026-10-23
> **Status:** Done
> **Decision:** [ADR-013](../adr/ADR-013-student-practice-sessions.md)
> (cancellation section)

---

## Implementation

| Area | Change |
|------|--------|
| `app/practice/store.py` | `practice.session.cancelled_at`; `cancel()` under a row lock: `cancelled`, `already_cancelled`, `finished` (no open question) or `not_ready` |
| `app/practice/routes.py` | `POST /api/practice/sessions/{id}/cancel`; `cancelled` in the session view; answers refused after cancellation |
| `app/static/*` | "Salir de la práctica" on the question screen; native `<dialog>`: "¿Querés salir de la práctica?", message, "Seguir practicando" / "Salir al menú principal"; cancelled practices are never resumed |
| `scripts/dev/practice_e2e.py` | Exit scenarios (desktop and mobile) |

Cancelled practices keep their generation status (`complete` or `partial`)
with `cancelled_at` set, so they stay distinct from completed (no
`cancelled_at`) and failed generations (`failed`). Submitted answers and
their timestamps are untouched and still feed the learning dashboard;
unanswered questions have no answer row and are never counted. No generation
is triggered. Curriculum, generation, OpenRouter settings and validation
rules are unchanged.

---

## Verification

| Case | API test | Browser |
|------|----------|---------|
| Exit before answering | Pass (partial practice) | Pass (desktop, mobile) |
| Exit after some answers; answers kept, rest unanswered | Pass | Pass: 2 answered, 3 open |
| "Seguir practicando" | — | Pass: dialog closes, stays on question 3 |
| Exit from a partial practice | Pass | Pass: 1 of 2 answered |
| Unanswered not counted | Pass (summary stays empty; dashboard test) | Pass: dashboard +2 answers only |
| No new generation jobs | Pass | Pass |
| Reload after exit does not resume | — | Pass |
| Duplicate / parallel cancellation | Pass: 5 parallel → one `cancelled` | Button disabled while sending |
| Cancel after the final answer | Pass: `finished`, not cancelled | — |
| Cancel during generation / unknown session | Pass: 409 / 404 | — |
| Desktop and mobile rendering | — | Pass; no overflow |

| Check | Result |
|-------|--------|
| Full suite | 365 passed |
| Browser (Chrome, mocked generator) | 182/182 |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Screenshot: `docs/progress/screenshots/T015-exit-dialog-mobile.png`.
