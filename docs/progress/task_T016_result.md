# Task T016 Result: Isolate Student Learning Data from Automated Tests

> **Date:** 2026-10-24
> **Status:** Done (Product Owner task T014.1)
> **Decision:** [ADR-016](../adr/ADR-016-test-database-isolation.md)

---

## Cause

The pytest suites already ran on `mentor_pro_test`, but
`scripts/dev/practice_e2e.py` called `create_app()` without a URL, so its
mocked and live browser runs wrote practices and answers to `DATABASE_URL`
(the student database). The dashboard counted them as the student's.

---

## Test Database Configuration

| Setting | Value |
|---------|-------|
| Student database | `DATABASE_URL` → `mentor_pro` (unchanged; used by `uvicorn app.main:app`) |
| Automated runs | `TEST_DATABASE_URL` → `mentor_pro_test` (environment, then `.env`) |
| Rule | Name ends in `_test` and differs from the `DATABASE_URL` database (`.env` and environment); parsed with libpq rules, so `?dbname=` overrides are caught; no connection is made |
| pytest | Throwaway schema `t_<hex>` per test or module, dropped afterwards |
| Browser script | Fixed schemas (`curriculum`, `practice`, `generation`, `llm`) of the test database; baseline imported if missing |

---

## Isolation Measures

| Where | Change |
|-------|--------|
| `curriculum/db.py` | `test_database_url()`, `database_name()`, `require_test_database()`, `UnsafeDatabaseError` |
| `tests/conftest.py` (new) | `pytest_configure` validates `TEST_DATABASE_URL` (usage error, exit 4, nothing collected if unsafe) and redirects `DATABASE_URL` to it for the whole run |
| `tests/curriculum/workbook_fixtures.py` | `new_target()` uses the same gate |
| `scripts/dev/practice_e2e.py` | Gate in `main()` before any server or connection (`E2E=refused`, exit 2); `create_app(test_url)` in mock and live mode; prints `E2E_DATABASE=…`; mock mode seeds synthetic bank items `e2e-bank-…` / `Q-e2e-bank-…` (M02, M04, M05, "Intermedia"); live mode generates, then repeats the configuration from the test database's own bank |
| `scripts/dev/test_data_report.py` (new) | Read-only (`default_transaction_read_only=on`) classification report |

The application, curriculum, generation policies, learning-status
thresholds and student-facing behaviour are unchanged. Still single-student,
no authentication.

---

## Historical Contamination (student database, nothing modified)

Full report: [T016_test_data_report.md](T016_test_data_report.md).

| Class | Sessions | Questions | Answers | Basis |
|-------|----------|-----------|---------|-------|
| Confirmed test | 103 | 424 | 308 | `set-mock-…` practice set or `Q-mock-…` items (mocked runner only) |
| Probable test (ambiguous) | 14 | 68 | 68 | Real bank or live-generated questions; created seconds after a confirmed test session and/or the scripted configuration (Matemáticas M02/M04/M05 or M02/M06) answered A, B, C, D, A |
| Presumed student | 2 | 9 | 5 | No test marker (Ciencias C06, 5 answers; Español EL06–EL08, no answers) |
| **Total** | 119 | 501 | 381 | |

Mocked runs never wrote to `generation.*` (0 mock attempts or sets). The 14
probable sessions include the live acceptance runs of T012–T014, whose
generated questions are also in the validated bank; those bank items are
valid and are not test data. Cleanup (for example deleting the confirmed
sessions' answers, items and sessions) needs explicit approval.

---

## Verification

| Requirement | Evidence |
|-------------|----------|
| Automation refuses the student database | `test_database_safety.py`: `practice_e2e.py` (mock and `--live`) exits 2 with `E2E=refused` before connecting; pytest exits 4 with "refusing to run automation"; gate unit tests (non-`_test` name, `?dbname=` override, `_test` name equal to the student database in `.env` or environment, no credentials in errors) |
| pytest runs only on the test database | `test_pytest_session_runs_on_the_test_database` |
| Browser runs do not touch student data | Read-only snapshot of the student database (counts and every non-mock session) identical before and after: full suite, two mocked browser runs, live run |
| Test answers cannot change mastery | Follows from the above: the dashboard reads only the student database, which automation cannot reach |
| Cancelled practices still count submitted answers | `test_answers_from_cancelled_practices_count_and_unanswered_do_not` (T015), unchanged and passing |
| Generated questions without answers do not affect progress | `test_generated_questions_without_answers_do_not_affect_progress` (new), `test_unanswered_questions_are_not_first_attempts` |
| Existing tests keep working | Suite 375 passed (365 + 10 new); browser mock 182/182 on `mentor_pro_test` (twice) |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Live run (`--live`, real OpenRouter, free models) on `mentor_pro_test`:
14/14 checks. Matemáticas M02, M04, M05 "Intermedia": 5 generated (435 s,
complete); the same configuration again: 5 of 5 from the test bank in 0.4 s;
M02, M06: partial, 3 bank + 1 generated. A first live run was discarded: it
was served the mocked run's synthetic seeds, so live mode now removes
`e2e-bank-…` rows from the test bank before starting.

The first complete mocked run on the test database stopped once on the 5 s
wait for the dashboard view; the endpoint answered 200 when called directly
and the next three runs passed 182/182 with no change. Cause not reproduced.
One ACE gate run reported `gate=test` failed right after a mocked browser
run; its output was not captured, and the next gate run and three further
full suite runs passed (375). Treat as a possible intermittent test.

---

## Regression Guards

No guarded file was modified (RCA-001: scaffold CLI; RCA-002:
`item_checker.py`, `app/generation/pipeline.py`).
