# T068 Result: Tutor Question Review Dashboard

- **Role:** Developer (PO authorization PO-QBANK-COMPLETION-2026-11-14)
- **Status:** implemented and tested; PO review of the PR required before
  release; first acceptance is a real pending candidate reviewed by the
  human tutor in production
- **Decision:** [ADR-036](../adr/ADR-036-question-bank-phase-b.md)

## Change

- Tutor page: a third section, **Revisión de preguntas**:
  - pending queue with filters (subject, objective, difficulty, batch);
  - full question (stimulus, stem, options, explanation), with the proposed
    correct answer highlighted;
  - curriculum objective and its evidencia as grounding;
  - approve or quarantine; the quarantine reason is required, the comment
    optional;
  - next-question navigation, "Pregunta n de N", and live
    pending/approved/quarantined counts per subject.
- `app/practice/tutor_review.py`: `GET /api/tutor/review/queue` and
  `POST /api/tutor/review/decisions`, served by the tutor service only, with
  the existing tutor check (allowed client address and tutor token).
- **No second approval mechanism.** The queue is
  `seeding.item_review_export` for each subject's current batch. Verdicts go
  through `seeding.item_review_record` (T051, append-only
  `generation.bank_item_review`); eligibility stays the existing
  `QuestionBank` rule. The reviewer is `tutor`, the same value the CLI
  records.
- **Exactly once.** `item_review_record` now takes an advisory transaction
  lock (4047, 1) and re-checks inside the transaction. A repeated, stale or
  simultaneous submission is refused with 409 `already_reviewed` and records
  nothing. The page also disables the button while a decision is in flight.
- **Audit trail:** `generation.bank_item_review` gains an optional `comment`
  column (additive, `ADD COLUMN IF NOT EXISTS`). Verdict, reason, reviewer
  and timestamp were already recorded.

## Unchanged

- Pending questions are never eligible.
- Nothing is approved without the tutor; the page never preselects a verdict.
- The batch sample gate and the CLI (`seed_bank item-review-sample/-record`)
  still work.
- The student app has no review route.
- Tutor token handling is unchanged.

## Tests

`tests/app/test_tutor_review.py`:

- **Queue content:** key, grounding and counts.
- **Filters:** all four, plus invalid values rejected.
- **Authorization:** no token, wrong token and wrong address are refused,
  and nothing is recorded.
- **Approve and quarantine:** a reason is required; eligibility follows the
  verdict; the audit row holds the comment; a repeat is refused (409); an
  unknown request is refused; the batch gate is untouched.
- **Concurrency:** four simultaneous submissions record one verdict.
- **Student app:** no review routes; the tutor service registers them.
- **Browser (Playwright, `MENTOR_PRO_BROWSER=1`):**
  - a wrong code returns to the login;
  - the key is highlighted and the progress is shown;
  - a missing verdict or reason is refused;
  - navigation works;
  - an approval with a comment (double click) records once;
  - the quarantine is recorded with its reason;
  - the counts update;
  - a stale-tab resubmission is refused (409).

## Corrective changes (PO-T068-CORRECTIVE-2026-11-14)

The PO's pre-release review found two gaps at `030714c`.

### Tutor schema initialization

- **Gap:** the `comment` column is added by the Question Bank schema
  (`QuestionBank` initialization, `bank.SCHEMA_SQL`). The tutor service never
  built a `QuestionBank`, so in production the column depended on a student
  practice request or a replenishment run happening first. A tutor verdict
  saved before either would fail on the missing column. The API tests missed
  this because their fixture seeds through generation, which applies the
  schema.
- **Fix:** `ReviewQueue.ensure_schema()` reuses the existing `QuestionBank`
  initialization; there is no new schema or migration. The tutor app calls it
  at startup, after the writing schema check. An unreachable database at
  startup is left to the first request, as `check_schema` already does, and
  every queue operation calls it again until it succeeds. The statements are
  `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS`, so they are
  idempotent and leave existing rows unchanged.
- **Regression test:**
  `test_tutor_startup_adds_the_comment_column_to_the_previous_schema`.
  1. Records a verdict without a comment.
  2. Drops the column to reproduce the `v2026.11.13-1` schema.
  3. Starts the tutor app twice.
  4. Checks the column exists, the earlier verdict is unchanged with a NULL
     comment, and a new verdict with a comment is recorded.

  With the fix removed, the test fails: the column is still missing after
  startup.

### Browser test execution

- **Gap:** the browser test is opt-in (`MENTOR_PRO_BROWSER=1`). Neither CI nor
  the ACE gate set the flag, so both skipped it. The earlier browser result
  above came from a manual run only.
- **Explicit run** (`MENTOR_PRO_BROWSER=1`, `tests/app/test_tutor_review.py`):
  9 executed, 9 passed, 0 failed, 0 skipped. This includes
  `test_review_in_the_browser`.
- **CI:** the `Python Tests` job now installs Chromium and runs
  `test_review_in_the_browser` with the flag set, against the CI test
  database with synthetic data only. A JUnit check fails the step when the
  test is skipped or not collected. A failing test also fails the step.
  Locally, the check returned exit 1 for a skipped run and exit 0 for an
  executed one.
- **ACE gate:** unchanged and reported separately. It does not run browser
  tests. `bash .ace/scripts/verify.sh` returned `VERIFY_RESULT=pass gate=all`
  with 1172 passed and 10 skipped, the skips being the opt-in browser and
  Docker tests. The lint gate also passed.

## T067 merge record

PR #72 merged into `dev` as `8aeaad9` (CI run 43614514102). Not yet
released.
