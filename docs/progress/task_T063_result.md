# T063 Result: Quiz Sizes 5-30 Offered Only When They Start

- **Role:** Developer (PO authorization PO-QUESTION-BANK-PHASE-B-2026-11-09)
- **Status:** implemented and tested; production enabling pending deployment

## Change (ADR-035 amendment T063, ADR-036)

- `POST /api/practice/availability` (read-only): for the exact choice
  (subject, scope, objectives, difficulty) it returns the permitted sizes
  the real composer fills now (`bank_counts`) and the sizes to offer
  (`question_counts` = `bank_counts` plus 5).
- `BankComposer.available_sizes` (ascending order, stops at the first
  failure) and a stock-count pre-check, so hopeless sizes fail at once.
- `app/static/app.js`:
  - Offers 5 until the server answers, then exactly the returned sizes.
  - Re-checks when the choice changes, not when a size is picked.
  - Explains when only 5 is available.
- Unchanged:
  - The 409 refusal for sizes above 5 and the size-5 generation fallback.
  - Unseen-first selection and difficulty balance.
  - Exclusion of quarantined and unreviewed questions.
  - Live generation stays at 5 questions.

## Tests

- `tests/app/test_quiz_sizes.py` (9), RCA-006:
  - Whole subject and every single objective at every difficulty.
  - Every offered size starts a complete bank practice with no generation;
    the next size up is refused with 409.
  - Switch off; empty bank; incomplete choice; configured cap; availability
    creates and calls nothing; invalid selection refused.
- Browser E2E `run_quiz_sizes` (desktop and mobile):
  - Offered sizes match the server.
  - The largest offered size (15 on the E2E bank) starts at once.
  - An unstocked level offers only 5.
  - No overflow and no JavaScript errors.
