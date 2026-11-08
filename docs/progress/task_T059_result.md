# T059 Result: Matemáticas Bank-Only Acceptance and Generate-on-Shortage Fix

- **Role:** Developer (PO 2026-11-08, critical production fix)
- **Status:** in progress (fix ready; supervised acceptance pending)

## Regression

During supervised acceptance on `v2026.11.08-2`, a Matemáticas choice the
bank could not fill answered "Todavía estamos preparando preguntas
revisadas…" and created nothing. See
[RCA-006](../rca/RCA-006-bank-only-shortage-dead-end.md).

## Change

- `app/practice/routes.py`: a bank-only request is composed from the bank
  first (unchanged). On a shortage at size 5, the existing generated flow
  starts for the whole practice with the same subject, objectives and
  difficulty, marked `generation: whole_session`, with no bank items.
  Other sizes keep the explained 409. Request retries return the same
  practice. A whole-session failure says "No se pudo preparar la práctica
  completa" after the cause.
- `app/practice/jobs.py`: a whole-session practice ends `complete` or
  `failed`, never `partial`; on failure nothing can be answered.
- Unchanged: allocation, D1-D4, bank eligibility (quarantined and
  unreviewed excluded), validation, provider fallback, budgets, paid
  approval, the per-subject switch, other subjects.

## Tests

`tests/app/test_bank_only_practice.py`: empty bank generates the whole
practice once (retry gives the same practice; size 10 still 409); partial
bank falls back without mixing; unstocked objective and level fall back;
failed generation (partial result, budget, exception) is `failed` with
nothing to answer; failure names the cause; quarantined stock is never
served. Existing: complete bank makes no LLM call; unreviewed generated
questions are held; other subjects keep the generated flow.

## Verification

- `tests/app/test_bank_only_practice.py`: 54 passed, 1 skipped.
- Browser E2E (mock): `E2E=pass` (485 checks, 0 failed).
- Full gate tests (ace, curriculum, app): 1025 passed, 9 skipped.
- ACE gate: `VERIFY_RESULT=pass gate=all` (log 20261108-130324-429).

## Release

- PR #61 merged into `dev` as `bcb6569` (CI 42514366739, green).
