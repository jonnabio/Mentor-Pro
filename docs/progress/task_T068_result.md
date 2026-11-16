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

PR #72 merged into `dev` as `8aeaad9` (CI run 43614514102). Released
together with T068 in `v2026.11.16-1` (see below).

## Release PO-T067-T068-PROD-2026-11-14 (resumed PO-T067-T068-RESUME-2026-11-15)

- **PR #73:** PO-reviewed after the corrective changes. Merged into `dev`
  as `f2f308c`; `dev` CI run 43672511622 green.
- **Release PR #74:** PR CI run 43782145310 green. Merged into `main` with
  `--match-head-commit f2f308c`, giving `2bd7dad`.
- **`main` CI run 43783087848:** green on all four jobs (Python Tests,
  Release Identity, Validate and Publish Docker Image, Tag and Release).
  `dev` synced to `main`.
- **Release `v2026.11.16-1`:**
  - image digest `sha256:47431d24…ee8e`;
  - manifest sha256 `69311fd1…60c7bb`, identical for the download and the
    server copy;
  - the manifest reports smoke pass for student and tutor.
- **Pause:** the server steps were paused on 2026-11-15 because the
  workstation's Tailscale was not connected. They resumed under
  PO-T067-T068-RESUME-2026-11-15 once it was restored.
- **Preflight:** `DEPLOY COMPATIBLE` (schema 0001..0001, live 0001).
- **Backup:** `mentor_pro_2026-11-16_012303.dump` (sha256 `7aacad97…f8e3`,
  37 tables, 2290 rows), `VERIFY OK`.
- **Deploy:** window `T067-T068-RELEASE-2026-11-16`. Result `DEPLOY OK`,
  `SMOKE PASS (13/13)`, `STATUS HEALTHY`. The app and tutor containers run
  `@sha256:47431d24…ee8e` and are healthy.

## Production Acceptance (2026-11-16, read-only)

- **Review schema:**
  - before the deploy, `generation.bank_item_review` had no `comment`
    column; after it, the column exists;
  - historical verdicts are unchanged: 41 rows (26 approved, 15
    quarantined), max `review_id` 41;
  - the md5 fingerprint over every verdict row is `44c18195…e801`, the
    same before and after.
- **Dashboard:**
  - `https://macedonianserver.tailb0ac04.ts.net:8443/tutor` (tailnet only)
    serves the "Revisión de preguntas" section (`#tutor-nav-review`,
    `#tutor-review`);
  - `/api/tutor/review/queue` without the token returns 403.
- **Review queue:**
  - read through `ReviewQueue` in the tutor container;
  - 23 pending: Español 7, Matemáticas 6, Ciencias 6, Estudios Sociales
    4;
  - every pending question has 4 options and a key;
  - no verdict was recorded, so the original Español candidate and the
    later ones all await the tutor.
  - The queue grew from 1 because the T066 scheduler ran its authorized
    3-hour ticks on `v2026.11.13-1` between 2026-11-14 and 2026-11-16.
- **T067 priorities** (`replenish coverage`): the first tier
  (`unblock_smallest_size`) is exactly the eight PO objectives:
  - Matemáticas: M08, M15, M21 (size 15);
  - Español: EL04, EL05 (size 5);
  - Ciencias: C04, C16 (size 5);
  - Estudios Sociales: ES24 (size 5).
- **Eligible questions:** Matemáticas 42, Español 10, Ciencias 10,
  Estudios Sociales 20. Mixed quizzes compose only for Matemáticas, at
  sizes 5 and 10.
- **T066 scheduler:**
  - `schedule-status`: enabled, not paused, `tick_calls` 10,
    `consecutive_failures` 0;
  - the last 10 ticks are all `ok`, each `tick_call_limit` with 10 calls,
    rotating through all four subjects;
  - one cron line installed.
  - Since 2026-11-14, `llm.usage_record` shows 140 calls, all `free`, at
    $0. `OPENROUTER_ALLOW_PAID=false`, `MENTOR_PRO_REPLENISH_SCHEDULE=on`.
  - Generation limits were not changed.
