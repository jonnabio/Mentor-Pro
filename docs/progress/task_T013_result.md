# Task T013 Result: Validated Question Bank

> **Date:** 2026-10-23
> **Status:** Done
> **Decision:** [ADR-014](../adr/ADR-014-validated-question-bank.md)

---

## Summary

Practices are now composed from previously accepted questions in PostgreSQL
before anything is generated. A slot takes a bank question only if it matches
the slot's baseline, objective, evidencia and exact difficulty and is
eligible under the current quality policy (checker 1.6.0), directly or by a
recorded revalidation. A fully covered practice starts at once without
OpenRouter; otherwise only the missing slots are generated with the existing
engine. Live: a bank-only practice was ready in 1.9 s with 0 calls; a mixed
practice reused 2 and generated 3 in 315 s at $0.00.

---

## Implementation

| Area | Change |
|------|--------|
| `app/practice/bank.py` | `QuestionBank`: eligibility (current checker, or revalidation stored in `generation.bank_revalidation`), slot matching, no duplicates or near duplicates in a set, preference for items this browser did not receive in 14 days |
| `app/practice/routes.py` | Compose from the bank at creation; complete at once or queue a job; `composition` in the response; status texts |
| `app/practice/jobs.py` | Generate only missing slots (`missing_allocation`); bank items seeded into set-wide D01; status from bank + generated |
| `app/practice/store.py` | `practice.item.source` (`bank`/`generated`), `source_request_id`; `practice.session.bank_count`, `browser_hash` |
| `app/generation/practice_set.py` | `seed_items` for the duplicate check |
| `app/static/app.js`, `styles.css` | Per-tab anonymous token; "Preparando práctica con preguntas disponibles…" while composing; fix for hidden action buttons |
| `scripts/dev/practice_e2e.py` | Bank scenario (mocked mode) and live bank + mixed acceptance |

Revalidation re-runs the current deterministic checker on the stored item and
grounding and reuses recorded evidence: the key must be proven by current
rules or confirmed by a recorded agreeing blind solve, and the recorded
rubric must be all 2. Historical attempt rows are not modified. Validation
rules, curriculum data, budgets, limits and answer protection are unchanged.

---

## Acceptance

### Live (browser, Chrome, real OpenRouter)

| Practice | Composition | OpenRouter calls | Ready after | Tokens in / out | Cost |
|----------|-------------|------------------|-------------|-----------------|------|
| Matemáticas M02, M04, M05 · Intermedia · 5 | **5 bank**, 0 generated | **0** | **1.9 s** | — | $0.00 |
| Matemáticas M02, M06 · Intermedia · 5 | 2 bank (M02 E1, E2), **3 generated** (M02 E3, M06 E1, E2) | 16 (12 ok) | 315 s | 10 978 / 33 524 | $0.00 |

Both practices were answered to the summary in the browser. M02 E3 had three
older items, all ineligible under 1.6.0, so it was generated; M06 had none.

An earlier live attempt in this task was misconfigured by the test script (it
requested "Difícil", where the bank was empty): it correctly generated all 5
hard questions (564 s), and a second practice then reused 2 of them. That run
added 63 calls, 40 940 / 111 886 tokens, $0.00.

### Eligibility of older items (revalidated against 1.6.0)

| Original checker | Eligible | Excluded | Exclusion reasons |
|------------------|----------|----------|-------------------|
| 1.2.0 | 0 | 2 | No recorded blind solve under current rules; L01 |
| 1.4.0 | 0 | 1 | L01 / L02 (the T006 M02 "siguientes resultados:" item) |
| 1.5.0 | 13 | 2 | No recorded blind solve (the T007 `3 × 6` and T008 `select: max` property items) |

### Acceptance checklist

| # | Check | Result |
|---|-------|--------|
| 1–2 | Five-question practice from inventory, no OpenRouter calls | Live: 5 bank, 0 calls; test: runner never called |
| 3–4 | Objectives, evidencias, exact difficulty and count | Slots match the allocation; all items `medium`; 5 questions |
| 5–6 | Partial inventory; only missing slots generated | Live 2 + 3; test: runner received only slots 4 and 5 |
| 7 | Old or invalid items excluded | 5 excluded with recorded reasons; wrong difficulty never considered |
| 8 | No duplicates in a set | Distinct item IDs and stems; an identical twin is not reused |
| 9 | Keys hidden until submission | No key or explanation in any response before answering (API and browser) |
| 10 | Complete practice in the browser | Live and mocked |

---

## Defects Found and Fixed

1. **Leave-practice buttons visible during generation** (introduced in
   T012): `.actions { display: grid }` overrode `[hidden]`, so "Nueva
   práctica" and "Volver al menú principal" showed while a job ran. Fixed and
   covered by a browser check.
2. **Mocked browser scenarios depended on an empty bank**: they now use
   objectives and a difficulty without inventory (M10–M12, "Difícil").

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 337 passed (5 new bank tests: full bank, partial generation, eligibility and revalidation, near duplicates, unseen preference) |
| Browser, mocked | 125/125 (includes a real-bank practice: 5 from the bank, ready in 1.4 s, no job) |
| Browser, live | 11/11 |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Screenshots and logs: `docs/progress/screenshots/T013/`.

---

## Notes

- Selection within eligible items is random; the unseen-first preference is
  per browser tab (`sessionStorage`) and needs alternatives to take effect.
- Bank quality depends on the original rubric and blind-solve records, which
  were model-scored.
