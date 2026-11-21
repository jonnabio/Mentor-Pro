# Implementation Plan: T072 (Automatic Eligibility and Student Reports)

- **Date:** 2026-11-19
- **Role:** Developer
- **Authorization:** PO T072 decision, 2026-11-19.
  - No student authentication for now; one student is assumed.
  - The report hold applies on deploy.
  - The scheduler pause is enforced in code.
- **Design:** [ADR-038](../adr/ADR-038-automatic-eligibility-and-student-reports.md)
- **Branch:** `feat/T072-auto-eligibility`, PR into `dev`.

## Assessment

- Eligibility is decided in one place, `QuestionBank.candidates()`:
  1. automated validation;
  2. not quarantined;
  3. `NOT_HELD_SQL`.

  Only check 3 assumes human approval. Composition, availability, capacity
  and coverage all use `candidates()`.
- Components that treat "pending" as not servable:
  - `replenishment.inventory`, `pending_review`, which feeds the triggers;
  - `tutor_coverage._pending_and_plan`;
  - the review queue's wording.
- The student is anonymous. The practice session ID and slot are the only
  identity.

## Changes

1. **`bank.py`:**
   - add the `question_report` table;
   - add the `auto_eligibility()` flag;
   - choose `NOT_HELD_SQL` by mode;
   - exclude questions with an open report.
2. **`question_reports.py` (new):**
   - create a report (student);
   - list open reports with question, key, validation evidence and the
     count of affected practices (tutor);
   - resolve as retain or quarantine.
3. **`routes.py`:** student `POST /sessions/{id}/reports`.
4. **`tutor_review.py`:**
   - the queue reports `auto_eligibility`;
   - a new reports router under `/api/tutor/reports`, wired in
     `tutor_main.py`.
5. **`replenishment.py` and `tutor_coverage.py`:** an eligible question
   doesn't count as pending.
6. **`replenish_schedule.py`:** `MENTOR_PRO_REPORT_PAUSE` (default 10)
   enforced as a `reports_open` skip; the status shows open reports.
7. **Student UI:** a "Reportar problema" button and dialog on each question.
   - The guarded `app.js` invariants (RCA-003, RCA-006) are unaffected.
8. **Tutor UI:** a "Reportes de estudiantes" section. The review heading
   says the review is optional when the flag is on.

## Acceptance criteria

1. **Flag off:** eligibility is identical to today.
2. **Flag on:**
   - a validated, unreviewed, actively linked question is eligible;
   - validation failure, quarantine, a failed batch or an open report
     excludes it;
   - approved questions stay eligible.
3. **Reporting:**
   - a valid report is stored with a content hash and holds the question;
   - a repeat is idempotent;
   - an unknown session or slot gets 404;
   - malformed or oversized input gets 422;
   - the cap gets 429;
   - the response leaks no answer key.
4. **Resolution:**
   - the tutor sees the reports;
   - retain clears the hold with no verdict;
   - quarantine records one verdict;
   - a repeat or concurrent resolution gets 409;
   - it is token-protected, and the student service has no such route.
5. **Integrity:** sessions, answers, verdicts and batch links are unchanged
   by reporting and retaining.
6. **Scheduler:** it skips `reports_open` at the threshold. The manual pause
   is unchanged.
7. **Browser:** the student reports without leaving the question and sees a
   confirmation. The tutor sees the report and resolves it. The T071 bulk
   review still works.

## Not in scope

- Student authentication.
- Activating the flag or resuming the scheduler in production.
- Rewriting scores.
