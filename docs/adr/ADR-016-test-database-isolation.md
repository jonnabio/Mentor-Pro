# ADR-016: Test Database Isolation

> **Status:** Accepted (Product Owner task T014.1, tracker T016)
> **Date:** 2026-10-24

---

## Context

The learning dashboard (ADR-015) counts every recorded answer as the single
student's. The pytest suites already used `mentor_pro_test`, but the browser
script `scripts/dev/practice_e2e.py` called `create_app()` without a URL and
therefore wrote to `DATABASE_URL`, the student database. On 2026-10-23 its
mocked and live runs created most of the stored practices and answers, which
the dashboard then showed as the student's progress.

---

## Decision

### One rule for every automated run

`curriculum.db.require_test_database(url)` is the only gate. It accepts a URL
only if its database name ends in `_test` and differs from the database named
by `DATABASE_URL`; otherwise it raises `UnsafeDatabaseError`. It parses the
URL with libpq rules, so `?dbname=` overrides are caught. It never connects.

`curriculum.db.test_database_url()` reads `TEST_DATABASE_URL` (environment,
then `.env`), like `database_url()`.

### Where the gate runs

| Entry point | Behaviour |
|-------------|-----------|
| `tests/conftest.py` (`pytest_configure`) | Validates `TEST_DATABASE_URL`, then sets `DATABASE_URL` to it for the whole run, so any code path that falls back to the default URL reaches the test database |
| `workbook_fixtures.new_target()` | Validates again before each throwaway schema |
| `scripts/dev/practice_e2e.py` | Validates before starting the server, in mock and `--live` mode; refuses with exit code 2 and no connection |

The app itself is unchanged: `uvicorn app.main:app` keeps using
`DATABASE_URL`. The browser script passes the test URL to `create_app()` and
also sets `DATABASE_URL` for its process.

### Test database contents for the browser script

`practice_e2e.py` prepares the test database before each run:

- imports the baseline `PNE2026-SUM-v1.0` into its `curriculum` schema if it
  is missing (from the checksummed workbook in `references/original/`);
- mock mode seeds labelled synthetic bank items (`request_id` `e2e-bank-…`,
  `item_id` `Q-e2e-bank-…`) for Matemáticas M02, M04, M05 "Intermedia", so the
  bank-only scenario does not depend on the student's bank;
- live mode starts from the test database's own bank: the first practice
  generates, and a repeat of the same configuration must be served from the
  bank. OpenRouter usage and the daily request budget for live runs are then
  recorded in the test database's `llm.usage_record`.

### Historical records

`scripts/dev/test_data_report.py` reads the student database with
`default_transaction_read_only=on` and writes a report. It never deletes or
updates. Cleanup needs explicit Product Owner approval and is a separate
task.

---

## Consequences

- Automated tests and browser runs cannot write answers into the student
  history, so they cannot change mastery classifications.
- The live acceptance run no longer reuses the student's validated bank; it
  builds and reuses its own, so its first run generates.
- Developer scripts that intentionally grow the real bank
  (`generate_examples.py`, `generate_practice_set.py`) still use
  `DATABASE_URL`; they write no practice sessions or answers.

---

## Related

- [ADR-013](ADR-013-student-practice-sessions.md),
  [ADR-014](ADR-014-validated-question-bank.md),
  [ADR-015](ADR-015-repeat-aware-learning-status.md)
- `docs/progress/task_T016_result.md`
