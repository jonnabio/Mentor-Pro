# T039 Result: Writing Progress and Revision Comparison

- **Date:** 2026-10-29
- **Role:** Developer
- **Branch:** `feature/T039-writing-progress` (from `dev` at `b192f01`)
- **Status:** implemented; PR into `dev` for PO review, not merged.
  Synthetic data only (`mentor_pro_test`); nothing deployed, migrated
  or published.

## Thought

The plan (PR #25, merged as `b192f01`) was approved with two
refinements: existing progress fields stay backward compatible, and
comparisons carry the Spanish criterion descriptions. A revision is a
second submission of the same exercise; before T039 the dashboard showed
it as another "entregado" exercise, which blocked the T037+T038 release.

## Action

- `app/writing/progress.py`:
  - existing fields unchanged in meaning; new `activity`
    `exercises_submitted`, `exercises_evaluated`, `first_attempts`,
    `improvements`, `improvements_pending`, per level
    `exercises_submitted` and `exercises_evaluated`, per criterion
    `exercises` and `improvements_pending`;
  - `compare(first, improved)`: per criterion a change only when both
    completed evaluations score it with the same rubric ID and checksum
    and the same pinned exercise revision; otherwise "No comparable";
    not-evaluable and missing scores have no number; a pending,
    in-progress or voided improvement shows "Tu mejora está pendiente de
    revisión"; changes as "+1 punto en EE03"; every row carries the
    official `statement_es`; no total, average or grade;
  - `revisions`: one comparison per revised exercise, newest first.
- `app/writing/store.py`: the progress read adds exercise, pinned
  revision, title, attempt order (from the submission order per
  exercise, so it also reads the legacy schema) and the completed
  evaluation. Read-only.
- `app/writing/routes.py`: `revision_attempt.attempt.comparison` on the
  exercise page once both reviews are completed.
- `app/writing/tutor.py`: `comparison` in the tutor submission detail
  once both evaluations are completed (tutor service only).
- UI: dashboard counts exercises once ("Ejercicios entregados", per
  level) and shows "Mejoras entregadas" and "Mis mejoras"; the exercise
  page shows "Comparación con mi primera versión"; the tutor page shows
  "Comparación por criterio".
- Tests: `tests/app/test_writing_progress_revisions.py` (11): compare
  rules (changes, pending/in-progress/voided, not evaluable, missing
  first or later score, mismatched rubric ID, checksum or exercise
  revision, missing first evaluation), existing fields unchanged for
  single-attempt histories and for inputs without the new fields,
  revision counting, several exercises and levels, API pending then
  completed (student progress, exercise page, tutor detail), reads write
  nothing, no tutor-only fields on the student side. Browser e2e: T039
  checks for the student comparison and the tutor comparison.
- ADR-032 "T039 amendment"; plan status, PO decisions and changes.

## Observation

| Check | Result |
| --- | --- |
| New and existing writing tests | 11 new passed; writing and tutor suites passed; migration test `test_migration_backfills_attempt_one_and_preserves_every_record` passes (progress identical before and after `0001`) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 878 passed, 6 skipped (log `.ace/logs/verify/20261029-201008-439`) |
| Browser e2e (`scripts/dev/practice_e2e.py`, `mentor_pro_test`) | `E2E=pass (485 checks, 0 failed)`, desktop and mobile, including the 4 T039 checks |

## Not verified

- No production data: the historical guarantee rests on the migration
  test and on single-attempt fixtures.
- Release still requires T037, T038 and T039 together under separate
  authorization, the production migration (I6 onward), T032/T033
  real-user acceptance, `v*` tag protection and the real GHCR path.

## Next

PO review of the T039 PR. Merge only with approval.
