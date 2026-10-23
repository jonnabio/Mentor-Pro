# Task T010 Result: Student Practice Integration and Real Testing

> **Date:** 2026-10-23
> **Status:** Done — live browser practice complete (5/5)
> **Decision:** [ADR-013](../adr/ADR-013-student-practice-sessions.md)

---

## Summary

The Spanish "Práctica PNE" page now generates a validated practice through a
server-managed job, shows progress, presents one question at a time,
evaluates answers on the server, gives feedback and explanation after each
answer, and ends with a summary. Keys never reach the browser before an
answer is submitted. A real browser (headless Chrome) completed the
Matemáticas acceptance practice with live OpenRouter generation in 366 s at
$0.00.

---

## What Was Inspected and Reused

| Existing component | Reuse |
|--------------------|-------|
| Static page `app/static` (T004) | Same page and styles; configuration form kept; allocation preview replaced by the practice flow |
| `select_objectives`, `allocate` | Session creation (same validation messages) |
| `generate_set` (T007/T008), checker 1.6.0 | Job runner; validation unchanged |
| `generation.practice_set`, usage records | Still written per set |
| `/api/practice/configure` | Kept (API tests); no longer used by the page |

---

## Implementation

| Area | Change |
|------|--------|
| `app/practice/store.py` | Schema `practice`: `session` (random 128-bit token, config, allocation, status, progress, stop reason), `item` (keys, server only), `answer` (first answer final); active-configuration unique index |
| `app/practice/jobs.py` | Single-worker in-process queue; progress per finished slot; failures end the job (`internal_error`); logs only session ID and status |
| `app/practice/routes.py` | `POST /api/practice/sessions` (202), `GET /api/practice/sessions/{id}`, `POST …/answers`; Spanish status messages |
| `generate_set` | `on_slot_done` progress callback |
| `app/static/*` | Progress view (polling 3 s), question view, feedback with text tags, result view, resume from `sessionStorage`; only 5 questions selectable |
| `scripts/dev/practice_e2e.py` | Playwright + Chrome, mocked and live modes; replaces `ui_smoke.py` (Edge cannot start here) |

---

## Browser Test Results

### Mocked generator (real API, PostgreSQL, evaluation and UI) — 71/71 checks pass

| Scenario | Result |
|----------|--------|
| All four subjects (desktop): configure → generate → answer 5 → summary | Pass: Q1 wrong, Q2–5 right, summary 4 / 1 / 80 %, objectives listed |
| Mobile 390 px (Matemáticas) | Pass; no horizontal overflow on any view |
| Correct and incorrect answers | Feedback text and highlighted options correct |
| No premature disclosure | No key, `correct_label` or explanation in any session response or page text before answering |
| Five clicks + a second tab with the same configuration | One job; the second tab reuses the running session |
| Reload during generation | Progress view restored; no second job; quiz appears when ready |
| Repeated submission | Second answer to Q1 ignored, first kept; reload resumes at the next unanswered question |
| OpenRouter failure (0 questions) | "El servicio de generación … no respondió. No se pudo preparar ninguna pregunta." and a restart button |
| Budget exhaustion (2 of 5) | Warning "Se alcanzó el límite diario … 2 de 5 …"; practice of 2 questions and summary 50 % |
| JavaScript errors | None |

### Live acceptance (Matemáticas M02, M04, M05; Intermedia; 5)

| Run | Session | Result | Generation time | Requests / calls | Tokens in / out | Cost |
|-----|---------|--------|-----------------|------------------|-----------------|------|
| 1 | `fa72cb38…` | **Partial 4/5** (`llm_unavailable`) shown to the student; 4 practised, 0 % | 743 s | 8 / 30 | 21 173 / 60 726 | $0.00 |
| 2 | `75b0d012…` | **Complete 5/5**; 3 correct, 2 incorrect, 60 % | 366 s | 6 / 22 | 12 654 / 25 950 | $0.00 |

Run 1: slot 1 failed all three requests because both free models were cut off
at the 4 000-token generation limit (`truncated`) and one returned HTTP 502.
The page displayed the partial state and let the student practise four
questions, as designed. Run 2 repeated the same practice unchanged.

Run 2 questions (keys verified by hand; validation under checker 1.6.0):

| Slot | Objective / evidencia | Key | Validation |
|------|-----------------------|-----|------------|
| 1 | M02 E1 | A 475 000 (450 000 < x < 500 000) | Blind solve agrees |
| 2 | M02 E2 | A 3/4 (largest of 3/4, 5/8, 2/3, 7/10) | Proven (`select: max`) |
| 3 | M04 E1 | C 20 (even, multiple of 5, divides 60) | Property → blind solve agrees |
| 4 | M04 E2 | A 1 230 (= 30 × 41) | Blind solve agrees |
| 5 | M05 E1 | A 12 grupos (3 × 28 ÷ 7) | Proven |

OpenRouter usage for T010 live runs: 52 calls, 33 827 / 86 676 tokens,
**$0.00** (all provider-reported). Daily usage after the runs: 142 of 1 000
requests. Budgets, concurrency and paid fallback unchanged (paid disabled).

Screenshots: `docs/progress/screenshots/T010/` (progress, mobile feedback
and result, partial, failure, live question, feedback and result); check
logs `mock-e2e.txt`, `live-e2e.txt`.

---

## Defects Found and Fixed

1. **Wrong answer shown green.** After an incorrect answer the chosen option
   kept the "selected" green style (the `:has(input:checked)` rule outranked
   `.is-wrong`). Fixed, and options now carry text tags ("Su respuesta",
   "Respuesta correcta") so feedback does not rely on colour.
2. **Cards touching the header** (pre-existing): `.wrap` overrode `main`
   padding. Fixed.
3. **Obsolete smoke test**: `ui_smoke.py` targeted the removed allocation
   preview and Edge, which cannot start under automation here. Replaced by
   `practice_e2e.py` on Chrome.

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 312 passed (14 new API tests: flow and key hiding, repeated submission, duplicate and parallel duplicate requests, partial, failures, not-ready, invalid input, restart → interrupted) |
| Browser, mocked | 71/71 |
| Browser, live | Run 2: 8/8 |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

---

## Privacy

No accounts or student identity are stored. Job logs contain only session ID,
status and counts. Answers are sent in POST bodies, which uvicorn does not
log; access logs do show session tokens in URLs.

---

## Open Items

1. Truncation at the 4 000-token generation limit is the main cause of
   partial sets (run 1). Raising `GENERATION_MAX_TOKENS` changes generation
   behaviour and needs approval.
2. The in-process worker generates one practice at a time and loses running
   jobs on restart (shown as "se interrumpió").
3. The student never sees which question failed in a partial set, only the
   count.
