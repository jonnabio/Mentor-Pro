# Implementation Plan: T069 (Quiz Sizes 5–30, Coverage and Capacity)

- **Date:** 2026-11-16
- **Role:** Developer
- **Authorization:** PO-T069-2026-11-16. The PO asked for no separate
  planning cycle, so this plan was written with the analysis and executed
  directly.
- **Branch:** `feat/T069-quiz-sizes`, PR into `dev`.

## Scope

1. Report the review inventory, read-only:
   - the 23 pending questions by subject, objective and difficulty;
   - the backlog and the scheduler's rate.

   No verdict is recorded and the scheduler is not changed.
2. Size regression on a synthetic four-subject bank, sizes 5 to 30:
   - API: allocation, level balance, distinct questions, exact count, no
     model call, scoring, history, tutor analytics, shortage;
   - browser, desktop and phone.
3. Tutor coverage view in the existing tutor service:
   - sizes available per subject;
   - blockers of the next size per objective and level, with the pending
     questions that could close them;
   - progress toward 30;
   - questions per objective, level and plan cell.
4. Capacity assessment by stage (allocation, plan, generated, approved),
   distinguishing structural limits from inventory shortfalls.
5. ADR for any plan expansion, proposed only.

## Not in scope

- Any change to `BankComposer`, the availability rule (T063) or the student
  UI (`app/static/app.js`, RCA-003 and RCA-006 guarded).
- Any change to the seeding plan, the scheduler or the review flow.

## Design

- `app/practice/capacity.py`: pure counting.
  - Per-objective demand comes from `allocate`, the level share from
    `level_bounds`.
  - An exact max-flow over objective × level gives the fewest missing
    questions or cells.
  - The same check runs on four supplies, so the first failing stage names
    the cause.
- `app/practice/tutor_coverage.py`: `GET /api/tutor/coverage?subject=`.
  - It sits behind the tutor check, like `/api/tutor/review`.
  - Availability is `BankComposer.available_sizes`, the same call as the
    student availability.
  - The plan and pending questions come from the subject's current batch.
- `replenish capacity`: the same report from the command line, plus the
  plan's structural limits.

## Regression guards

| Guard | Touched? | How it is kept |
| --- | --- | --- |
| RCA-006 | `routes.py`, `jobs.py`, `bank_allocation.py`, `app.js` untouched | The new tests assert that offered sizes equal what composes, that larger sizes are refused with nothing created, and that there are no model calls; `test_quiz_sizes.py` and `test_bank_only_practice.py` run in the gate |
| RCA-005 | `ci.yml` adds browser tests to the existing step | No runtime dependency added; the smoke and publish steps are unchanged |
| RCA-003 | `verify.sh` and `app.js` untouched | — |

## Verification

- The new tests: `test_capacity.py`, `test_quiz_sizes_subjects.py`,
  `test_tutor_coverage.py`.
- Full ACE gate: `bash .ace/scripts/verify.sh`.
- CI, including the browser step, which now also runs the T069 browser tests.
- Read-only production capacity run, recorded in the T069 result.
