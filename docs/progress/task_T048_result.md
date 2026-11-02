# T048 Result: Configurable Practice (Increment 2)

- **Date:** 2026-11-01
- **Role:** Developer
- **Status:** Done (PR into `dev`, awaiting PO review). No deployment, no
  live generation, no production seeding, budget unchanged.
- **Decision record:** [ADR-035](../adr/ADR-035-bank-only-configurable-practice.md)

## Change

- `app/allocation.py`: permitted sizes 5, 10, 15, 20, 25, 30.
- `app/practice/bank_allocation.py` (new): bank-only composer (D1–D4) and
  the largest feasible size.
- `app/practice/bank.py`: `candidates` (one query per objective); `eligible`
  now uses it, rules unchanged.
- `app/practice/routes.py`, `app/practice/store.py`, `app/main.py`: `source`
  field, bank-only path, 409 `insufficient_inventory`, Spanish messages.
- `app/static/index.html`, `app/static/app.js`: six sizes, default 5,
  shortage message with a one-tap smaller practice.
- Also carries the T047 merge record (commit `e64617b`, cherry-picked).

## Verification

- `tests/app/test_bank_only_practice.py`: every size, exact cells, objective
  counts, D1 evidencia spread, no level substitution, mixed balance, unseen
  first, no duplicates, backtracking out of difficulty and near-duplicate
  dead ends (both fail on plain greedy), largest feasible size, ready at once without
  generation, shortage creates nothing, empty bank, quarantine, earlier
  5-question flow kept.
- ACE gate: `VERIFY_RESULT=pass gate=all`; pytest 916 passed, 8 skipped
  (opt-in latency and browser tests); baseline 892 passed, 6 skipped.
- Latency (opt-in, `MENTOR_PRO_LATENCY=1`), p95 of 20 starts: 5 questions
  439 ms, 30 questions 863 ms; earlier bank-first flow 592 ms.
- Browser (opt-in, `MENTOR_PRO_BROWSER=1`, Chromium 390 px): six sizes,
  default 5, a 30-question request shows the shortage message and "Hacer una
  práctica de 10 preguntas", which starts a 10-question practice answered to
  the summary; no generation.
