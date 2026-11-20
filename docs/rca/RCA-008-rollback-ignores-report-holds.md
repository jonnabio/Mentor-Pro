# RCA-008: Rollback to an Image Without Report Holds

- **Severity:** critical (a student could be served a question already
  reported as wrong)
- **Detected:** 2026-11-19, PO review of T072 (PR #81), before any
  production deployment. No incident occurred.
- **Status:** prevented by the T072 rollback safeguard (ADR-038 D6)

## Risk

T072 stores student reports in `generation.question_report`, and
`QuestionBank.candidates()` excludes questions with an open report. The
hold lives in the code, not the database. An image older than T072 ignores
the table, so a routine `mentorpro rollback`, which passes every existing
gate (same schema, verified backup, known-good image), would put reported
questions back into new practices.

## 5 Whys

1. Why would reported questions return? The older image has no
   `NOT_REPORTED_SQL` filter.
2. Why would the rollback be allowed? Rollback compatibility was only the
   writing schema range; the report table is additive and does not change
   that range.
3. Why not a schema migration? The Question Bank tables are created with
   `IF NOT EXISTS` outside the writing migration ledger, by design.
4. Why does it matter? Rollback is the documented first response to a bad
   release, under time pressure.
5. Why wasn't it caught earlier? No gate described what an image enforces,
   only which schema it can run on.

## Fix

- CI labels every image `io.mentorpro.capability.report-holds=1`, and the
  labels are bound to the image digest.
- `preflight`, `deploy` and `rollback` read the label only after verifying
  the image, then refuse an image without it while any report is open. An
  unknown label value or an unreadable count also refuses.
- The runbook gives the safe recovery path. No override exists.

## Prevention

- Guard RCA-008 in `docs/rca/regression-guards.yaml`, tests in
  `tests/app/test_deploy_report_holds.py`.

## Lessons Learned

When a safety rule depends on application code rather than the schema,
rollback must check that the target image enforces it. Declare that as a
capability label bound to the image digest.
