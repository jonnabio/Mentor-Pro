# T056 Result: Matemáticas Bank-Only Release Readiness

- **Role:** Developer (fast track, PO 2026-11-07)
- **Status:** in progress (readiness done; seeding and activation await
  PO authorization)

## Production Inventory (Read-Only, 2026-11-07)

Measured on `v2026.11.05-2` with the real `BankComposer` (no writes, no
LLM call). A one-off probe ran in the app container and was then deleted;
`seed_bank compose-check` makes the same check repeatable.

- Batch `bb-matematicas-cd792836` `open`/`pending`: 6/100 cells filled, 6
  adopted, 0 generated, 0 held, 1 deactivated (M09 quarantined, `level`).
- Eligible Matemáticas questions: **16** (the batch plus earlier bank
  questions); 40 questions seen by the student.

| Objective | easy | medium | hard |
| --------- | ---- | ------ | ---- |
| M01       | 1    | 2      | 0    |
| M02       | 0    | 2      | 0    |
| M03       | 0    | 1      | 0    |
| M05       | 0    | 1      | 0    |
| M14       | 1    | 0      | 0    |
| M16       | 1    | 0      | 1    |
| M17       | 1    | 1      | 0    |
| M18       | 1    | 1      | 1    |
| M19       | 0    | 1      | 0    |

The whole-subject size-5 plan is M01, M05, M09, M14 and M18, one question
each. Every difficulty currently fails (largest size 0).

## Minimum Additional Approved Questions

- **Mixed (each level 1 or 2 of 5):** 1 M09 question, `easy` or `medium`
  (for example M01 easy, M05 medium, M09 medium, M14 easy, M18 hard). The
  existing M18 hard question meets the hard requirement.
- **Recommended for release:** 2 M09 questions (`easy` and `medium`), so
  the first quiz does not depend on a single candidate.
- **Explicit levels (optional):** easy needs M05 and M09; medium needs M09
  and M14; hard needs M01, M05, M09 and M14. That is 8 distinct cells in
  total.

## Change

- `app/practice/bank_allocation.py`: `readiness()` returns counts only:
  eligible questions per objective and difficulty, and per difficulty the
  size-5 objectives, the missing objectives and the largest feasible size.
- `app/practice/seed_bank.py`: read-only `compose-check --subject` command.
- `tests/app/test_bank_only_practice.py`: 2 tests (counts, missing
  objectives, largest size; no question text in the output).
- No change to RCA-guarded files.

## Verification

- `tests/app/test_bank_only_practice.py`: 35 passed, 1 skipped.
- Full gate tests (ace, curriculum, app): 1006 passed, 9 skipped.
- ACE gate: `VERIFY_RESULT=pass gate=all` (test 289 s, lint 5.1 s; log
  20261107-075106-343).

## Release

- PR #56 merged into `dev` as `b98a443` (CI 42420702854, green).
- PO authorization `PO-T056-FASTTRACK-2026-11-07`, window
  `T056-2026-11-07`.
