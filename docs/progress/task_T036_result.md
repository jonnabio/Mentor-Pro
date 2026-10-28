# T036 Result: Student Attempt Data Foundation (ADR-032)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T036-guided-writing-revision-design` (not merged)
- **Status:** implemented and verified locally on `mentor_pro_test`; three
  implementation decisions await Product Owner confirmation (ADR-032
  "T036 implementation", PO 1–3); no production migration, deployment or
  release

## Thought

ADR-032 principles approved: one stable exercise, many student attempts,
one draft and one submission per attempt, one human evaluation per
submission, earlier work immutable. The code matched the ADR's description
(draft keyed by `exercise_id`, `uq_submission_exercise`,
`uq_evaluation_submission`, `client_seq`, L4 `sections`, locked completed
evaluations, DDL in `WritingStore.__init__`). Two findings shaped the
design:

- `SCHEMA_SQL` ran `CREATE UNIQUE INDEX IF NOT EXISTS uq_submission_exercise`
  at every start, which would recreate the index after a migration.
- An unsubmitted answer follows the latest editorial revision (ADR-023,
  `routes.py`); pinning attempt 1 at creation would change that.

## Action

- `app/writing/migrations.py`: migration `0001_student_attempts` (schema,
  attempt 1 backfill, validation, constraints, ledger
  `writing.schema_migration`), `rollback`, `state`.
- `app/writing/migrate.py`: `python -m app.writing.migrate
  status | apply [--dry-run] | rollback`.
- `app/writing/store.py`: startup states (empty → current version; older
  tables → `SchemaMigrationRequired`; current → additive DDL only);
  `uq_submission_exercise` no longer created at startup; exercise-level
  methods read and write attempt 1 only; new `attempts`, `attempt`,
  `attempt_draft`, `attempt_submission`, `save_attempt_draft`,
  `submit_attempt`, `start_revision` (no route); `tutor_queue` adds
  `attempt_number`; `add_submission` attaches attempt 1.
- `app/writing/bank.py`: `student_attempt` counted among the student
  tables an import must leave untouched.
- `tests/app/test_writing_attempts.py` (19 tests).
- ADR-032 section "T036 implementation"; runbook section K; plan rewrapped
  for lint (content unchanged).

Commits: `1652181` (plan wrap), `8bd806f` (tracker), `ce0fa5c`
(implementation), followed by the documentation commit.

## Observation

Data model:

```text
writing.exercise
  -> student_attempt (attempt_id PK; UNIQUE(exercise_id, attempt_number);
                      UNIQUE(attempt_id, exercise_id); UNIQUE(previous);
                      attempt 1 <=> no previous; previous in same exercise)
       -> draft      (PK attempt_id; FK (attempt_id, exercise_id))
       -> submission (submission_id PK; UNIQUE(attempt_id);
                      FK (attempt_id, exercise_id))
            -> evaluation (UNIQUE(submission_id), unchanged)
                 -> criterion_score (unchanged)
```

Migration tests (synthetic pre-T036 database: L2 draft only without
`client_seq` or revision, L3 submission without draft, L1 correction with
draft and completed evaluation with two scores, L4 five sections):

| Case | Result |
| --- | --- |
| Empty database | created at current version, ledger `fresh`, no attempts, draft PK `attempt_id`, old index absent after restart |
| Unmigrated database at startup | refused with the command to run; nothing changed |
| Backfill | 4 attempts, all number 1, revision 1; drafts, submissions, evaluations, scores byte-identical; `progress_inputs()` identical; app starts |
| Re-apply | `already_applied`, nothing changed |
| Dry run | report, then `legacy` state and identical data |
| Injected validation failure | full rollback (no table, no column, old index kept) |
| Two submissions for one exercise | refused before any change |
| Rollback with only attempt 1 | old schema back, data identical, re-apply works |
| Rollback after a revision attempt | refused |

Persistence and integrity tests: duplicate attempt number, attempt 2
without predecessor, predecessor in another exercise, draft or submission
pointing at another exercise's attempt, submission without attempt and a
second submission per attempt are all rejected by the database. Twelve
parallel first saves create one attempt; eight parallel `start_revision`
calls create one attempt 2. A revision needs a completed evaluation (not
pending or in progress), at most two attempts, typed submissions only. L1
revision drafts start from the submitted correction (not the source text);
L4 keeps the five sections and the assembled text; the first submission,
evaluation and scores do not change. Attempt-scoped autosave ignores stale
`client_seq`, submission retries return the first submission, submitted
attempts are frozen. Legacy exercise-level writes cannot reach an open
revision. Attempt 1 follows editorial revisions until submitted; a
revision attempt stays pinned.

CLI on `mentor_pro_test` (`DATABASE_URL` set explicitly to the test
database): `status` → `current`, `apply` → `already_applied`, `rollback` →
`rolled_back` with equal digests, `status` → `legacy`, `apply --dry-run` →
`dry_run_rolled_back`; schema dropped afterwards.

Verification:

- `tests/app/test_writing_attempts.py`: 19 passed.
- Existing writing and tutor tests (`-k "writing or tutor"`): 194 passed.
- `bash .ace/scripts/verify.sh` first run: gate `test` passed (601 passed,
  skills valid); gate `lint` failed on 20 MD013 lines in the committed
  plan (formatting) → rewrapped; final gate result below.
- `scripts/dev/practice_e2e.py` (mocked browser, test database):
  `E2E=pass (447 checks, 0 failed)`.
- Multiple choice, tutor token and isolation suites are part of the 601.

Final gate (after the documentation): `VERIFY_RESULT=pass gate=all`, test
601 passed, lint passed (log `.ace/logs/verify/20261028-062220-1096`).

## Risks

- A release of an image containing T036 needs the migration first
  (runbook K); without it the app and tutor service refuse to start (fail
  closed, old image unaffected).
- `progress_inputs()` and the tutor queue count every submission; once
  revision attempts exist, activity counts include them (T039 must
  separate attempts from exercises). No route can create one yet.
- "Predecessor is attempt n−1" is enforced by the store transaction, not
  by a database constraint (tested).
- After a revision attempt exists, the migration cannot be rolled back
  without restoring a backup (ADR-032).
- Not tested against a restored copy of production data (not authorized);
  required before any production migration.

## Next

T037 (student revision) can build on `start_revision`,
`save_attempt_draft` and `submit_attempt`; it still needs the API paths,
the "Mejorar mi respuesta" flow and browser tests.
