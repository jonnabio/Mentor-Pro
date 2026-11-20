# T072 Result: Automatic Eligibility and Student Reports

- **Status:** PR #81 reviewed and merged into `dev` on 2026-11-19 (merge
  `550fc211440842f8a2daa77338ed9b39dd1f177d`, exact-head guard `73391a1`,
  PR CI 44580444939, `dev` CI 44648495199, all green). Rollback safeguard
  in a follow-up PR (section 7). Release, deploy, activation and production
  acceptance are separate gates; none has happened yet.
- **Design:** [ADR-038](../adr/ADR-038-automatic-eligibility-and-student-reports.md),
  [plan](../planning/2026-11-19-T072-auto-eligibility-plan.md)
- **PO decisions (2026-11-19):**
  - no student authentication for now; one student is assumed;
  - the report hold applies on deploy;
  - the scheduler pause is enforced in code.

## 1. Assessment

- Eligibility has one decision point, `QuestionBank.candidates()`:
  1. validation (checker `accept` or revalidation);
  2. not quarantined;
  3. `NOT_HELD_SQL`, which required a passed batch gate or a tutor
     approval.

  Composition, availability, capacity and coverage all use it.
- **Components that treated "pending" as not servable:**
  - `replenishment.inventory` (`pending_review`, which feeds the
    triggers);
  - `tutor_coverage._pending_and_plan`;
  - the review queue's wording.
- **Student identity:** there is none. The 32-hex practice session ID and
  the slot are the only reference.

## 2. Changes

- **`bank.py`:**
  - new `generation.question_report` table;
  - `auto_eligibility()`, which reads `MENTOR_PRO_AUTO_ELIGIBILITY` (`on` or
    `off`, default off; any other value is refused);
  - `NOT_HELD_AUTO_SQL`: active link and batch review not `failed`;
  - `NOT_REPORTED_SQL`: no open report, in both modes.
- **`question_reports.py` (new):**
  - `create`: idempotent per session and slot, content SHA-256, 30 per 24
    hours cap;
  - `open_reports`: question, key, explanation, validation evidence and
    practices that used it, with no student identity;
  - `resolve`: retain or quarantine in one transaction under the review
    lock, re-checking that reports are still open. It never adds a second
    quarantine.
- **Student API:** `POST /api/practice/sessions/{id}/reports`, returning
  404, 422 or 429 as appropriate and never an answer key.
- **Tutor API:**
  - `GET /api/tutor/reports`;
  - `POST /api/tutor/reports/{request_id}/resolve`;
  - both token-protected and absent from the student service;
  - the queue response carries `auto_eligibility`.
- **Replenishment and coverage:** an eligible question no longer counts as
  pending, so the review backlog doesn't block generation.
- **Scheduler:**
  - `MENTOR_PRO_REPORT_PAUSE` (default 10, range 1 to 1000);
  - a tick skips with `reports_open`;
  - the status shows `open_reports`;
  - the manual pause still takes precedence.
- **Student UI:** "⚑ Reportar problema" opens a dialog with five reasons and
  an optional comment. A confirmation appears inline, and the practice
  continues.
- **Tutor UI:**
  - "Reportes de estudiantes" sits above the review and shows the reports,
    the question, the key, the evidence and its use, with **Mantener**
    (retain) and **Cuarentena** (quarantine);
  - the review policy text follows the flag.

## 3. Verification

- `tests/app/test_question_reports.py`: 17 API tests and 1 browser test.
  - **Eligibility:**
    - flag parsing;
    - flag off is unchanged;
    - flag on serves validated questions and creates no verdict;
    - quarantined questions, missing or outdated validation evidence, and
      failed batches stay excluded;
    - approved questions stay eligible;
    - inventory counts each question once.
  - **Reporting:**
    - the hold and the stored fields;
    - no answer key in the response;
    - practice data unchanged;
    - duplicate and concurrent reports;
    - 404 and 422 cases;
    - the cap (429);
    - the student service has no tutor routes.
  - **Resolution:**
    - the token is required;
    - no student identity is shown;
    - retain clears the hold with no verdict and leaves data unchanged;
    - quarantine records one verdict and reopens the cell;
    - a repeat gets 409;
    - concurrent resolutions apply exactly once;
    - no second quarantine.
  - **Scheduler:** the threshold skip, status fields, settings validation,
    and the manual pause.
  - **Browser:**
    - the student reports and keeps answering;
    - the tutor sees the report and retains it;
    - the T071 bulk list still renders.
- Existing suites pass with no regressions: seeding, review, bulk,
  question bank, replenishment, schedule, coverage and bank-only practice.
- The full gate and CI results are in the PR.

## 4. Security and data integrity

- **Trust boundary:** the flag stays off until the PO activates it.
  Reporting can only remove questions from practices.
- **No authentication:** a report needs a real session ID (128-bit,
  unguessable) and a real slot. One report per slot and a global daily cap
  bound misuse. Student authentication is deferred by PO decision.
- **Data:** no historical row is modified. Reports reference the exact
  content hash. Scores are never rewritten; affected practices are counted
  for the tutor.

## 5. Migration and compatibility

- **Additive:** one table and one partial index, created with `CREATE ...
  IF NOT EXISTS` like the other Question Bank tables. The writing schema
  version is unchanged.
- **Rollback:** the previous image ignores the table, so the deploy helper
  refuses it while reports are open (section 7).
- **New settings:** `MENTOR_PRO_AUTO_ELIGIBILITY` (absent means off) and
  `MENTOR_PRO_REPORT_PAUSE` (absent means 10). Production needs no
  configuration change to deploy T072.

## 6. Deployment and activation risks

- With the flag off after deploy, eligibility is unchanged. The new
  behavior is reporting and the hold.
- **Activation:** turning the flag on exposes about 50 validated, unreviewed
  production questions to the student at once. It needs PO authorization.
  Afterwards, watch the report queue and the cap.
- The scheduler stays paused (PO 2026-11-18). Once resumed, the report pause
  bounds the tutor's workload.

## 7. Rollback safeguard (ADR-038 D6, RCA-008)

- **PO decision (2026-11-19):** an older image must not run while open
  reports exist.
- **Capability:** CI labels every image
  `io.mentorpro.capability.report-holds=1`. The helper reads the label only
  after verifying the registry digest, version tag, commit and labels, so it
  is bound to the immutable release identity. A manifest cannot supply it.
- **Check:** `preflight`, `deploy` (and `migrate`, through it) and
  `rollback` (manifest and legacy targets), inside the lock, before any
  container change. The open count is a read-only query, read only when the
  image lacks the label.
- **Matrix:** label `1` proceeds; no label with 0 reports or no table
  proceeds; no label with open reports, an unreadable count, or an unknown
  label value is BLOCKED. A blocked rollback is recorded `REFUSED`.
- **Write barrier (PR #82 review):** for an image without the label, one
  read-only psql session takes the report lock `(4047, 2)` before the count
  and keeps it until the containers changed; on release it terminates
  report requests still waiting for it. A report therefore commits before
  the count (and blocks) or never.
- **Recovery:** production runbook, "Report holds". No override flag; the
  script never clears reports or changes verdicts.
- **Tests:** `tests/app/test_deploy_report_holds.py` (matrix, label parsing,
  count parsing, psql failures, deploy, rollback for manifest and legacy
  targets, preflight, CLI refusal, release labels, the real query on
  PostgreSQL in CI).
- **Unchanged:** image identity checks, backup evidence, deploy lock, schema
  compatibility and the other gates.

## 8. Concurrency fix found by CI (PR #82)

- **Symptom:** `test_simultaneous_resolutions_apply_once` failed once in CI
  with `DeadlockDetected` (run 44671405859). It is a real defect: two tutor
  resolutions at the same time could fail one of them.
- **Cause:** every report call ran the Question Bank schema SQL, whose
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` takes an ACCESS EXCLUSIVE lock
  even when nothing changes. It deadlocked against the other request's
  verdict insert.
- **Fix:** `question_reports._ensure_schema` runs the schema SQL once per
  database URL and process, under a thread lock. The report suites passed
  six consecutive local runs.

## 9. PR #82 review corrections (2026-11-20)

- **Race closed:** the write barrier above replaces the separate count in
  deploy and rollback; preflight keeps the advisory count.
  `test_in_flight_report_cannot_commit_across_the_switch` starts a report
  after the barrier counted zero, switches only once PostgreSQL shows it
  waiting for the lock, and proves it is rolled back and nothing is open.
  Further tests: a report committed first blocks; a failed switch leaves no
  lock; an unreachable database refuses; the lock key equals the
  application's.
- **PostgreSQL tests mandatory:** CI sets `MENTORPRO_REQUIRE_PSQL=1`; without
  psql these tests fail instead of skipping.
- **`_ensure_schema` cache:** safe in production. The student service runs
  one uvicorn process (no `--workers`), the tutor service one
  `uvicorn.run` process, and each scheduler tick is a new `docker exec`
  process. The schema is additive and never dropped while a process runs;
  a restore goes into a new database with restarted containers. No change.
  Residual, pre-existing: the first schema run of a tick process can still
  meet a tutor resolution (replenishment also builds `QuestionBank` per
  tick); PostgreSQL then aborts one side and the tutor retries.
