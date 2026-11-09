# T060 Result: Tutor Practice Results and Question Bank Analytics

- **Role:** Developer (PO authorization PO-T060-2026-11-08, fast track)
- **Status:** done (PR into `dev`; deployment after PO review)

## Change

- `app/practice/tutor_results.py` (new): read-only `PracticeResults` and
  the `/api/tutor/practice` router (GET only):
  - `sessions`: history with date, subject, objectives, difficulty,
    status, a practice state (completed, left, in progress, not started,
    preparing, failed), bank/generated composition, answered, correct,
    incorrect, unanswered and accuracy. Latest 200.
  - `sessions/{id}`: each question with stimulus, stem, options, the
    student's answer, the correct answer, explanation, source,
    objective, difficulty and result (correct, incorrect, unanswered).
  - `questions`: per question served, answered, correct, incorrect,
    unanswered and success rate (none when never answered), plus groups
    by objective and difficulty. A bank question is identified by its
    bank request, so repeats across practices add up.
  - Filters: subject, objective, date range (Costa Rica dates), source.
  - Queries run in read-only transactions; sessions classified
    `automated_test` or `quarantined` (ADR-017) are left out. No student
    name or identifier exists in these tables or responses.
- `app/writing/tutor.py`: the tutor check is now `tutor_guard`, shared
  by writing review and practice results (same address and token rules).
- `app/tutor_main.py`, `app/main.py`: the router is mounted only where
  writing review is (tutor service; local app with a tutor token).
- `app/static/tutor.html`, `tutor.js`, `styles.css`: after the tutor code,
  two sections, "Producción escrita" and "Resultados de práctica", with
  filters, history, a per-practice answer review, accuracy by objective
  and difficulty, and per-question accuracy (collapsible).
- Unchanged: student UI and routes, generation, scoring, budgets,
  bank eligibility, production configuration.

## Tests

- `tests/app/test_tutor_practice_results.py` (32): absent or wrong token
  and other addresses refused; write methods 405 with no data change; no
  routes without a tutor token; history of completed, left, unanswered
  and failed practices; automated-test sessions excluded; filters and
  invalid filters; answer review; repeated bank questions, zero-attempt
  and unanswered-versus-incorrect metrics; grouping; state rules.
- `scripts/dev/practice_e2e.py` `scenario_tutor_practice` (desktop and
  mobile): refused without the code; history matches stored counts;
  answer review matches stored answers and keys; source filter; no
  overflow; no data change; no JavaScript errors.

## Verification

- Browser E2E (mock): `E2E=pass` (503 checks, 0 failed).
- Full gate tests: 1057 passed, 9 skipped.
- ACE gate: `VERIFY_RESULT=pass gate=all` (log 20261108-195828-1969).

## Deployment Requirements

- Normal release and deploy; no schema change, no new setting, no new
  dependency. The tutor service reads the existing practice tables.
- Tutor access is unchanged: SSH tunnel to `127.0.0.1:8081`; the house
  Wi-Fi address only after T058 (PR #59) is merged and deployed.

## Release

- PR #63 (CI 42548953882, green) merged into `dev` as `9c96d53` (dev CI
  42551550335, green). Release authorization `PO-T060-RELEASE-2026-11-08`.
