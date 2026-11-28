# RCA-009: A question reported before answering blocks the practice

## Issue Summary

**One-line description:** after a student reports a question they have
not answered, the practice offers no way to the next question.

**Impact:** a student who reports a question because it can't be answered
(confusing, missing information, broken table) has to answer it anyway,
or abandon the practice. Seen on production `v2026.11.24-1` during T072
Gate C. No data was lost; the report was stored.

**Detection:** user report during Gate C acceptance, 2026-11-26.

## Timeline

- 2026-11-22: T072 deployed (`v2026.11.21-1`) with student reports.
- 2026-11-26 15:43Z: the PO reports slot 1 of session `1c53d3c2…`
  (`confusing`) before answering. Report 1 is stored `open`; the session
  has 5 items and 0 answers.
- 2026-11-26: the PO reports that the practice can't continue.

## Symptoms

- The report confirmation appears; the question stays on screen.
- "Siguiente pregunta" (`#next`) lives in the feedback panel, which only
  appears after an answer.
- The result requires every slot answered (`routes.summary`), so even
  the last question could not finish the practice.

## Root Cause Analysis

### The 5 Whys

1. Why can't the student continue? The only "next" control is shown
   after an answer.
2. Why is that the only control? Before T072, every question had to be
   answered; there was no reason to leave one.
3. Why didn't T072 add one? ADR-038 D3 said the student reports "without
   leaving" the question, and assumed the student would still answer it.
4. Why wasn't the gap caught? The T072 browser test answered the question
   after reporting it, so it never tried to move on without answering.
5. Why did the result also block? `summary` returned nothing while any
   slot was unanswered, and the session view never carried `reported`,
   so a reload also forgot the report.

### Root Cause Statement

Reporting was added as a side action on a flow whose only way forward is
answering. Neither the client nor the result scoring treated "reported
and unanswered" as a resolved state for the student.

### Contributing Factors

- The browser regression covered the report-then-answer path only.
- The session view did not expose `reported`, so the client's state
  depended on the page never reloading.

## Resolution

### Permanent Fix

PO decision 2026-11-26: a question reported before it is answered can be
skipped and is not scored (ADR-038 D3 amendment).

- The session view marks each question `reported`
  (`question_reports.reported_slots`).
- `summary` treats a reported, unanswered question as skipped: it doesn't
  block the result, isn't scored, and is counted as `skipped`. A
  reported question that was answered is scored as before. With nothing
  answered, `percentage` is `null`.
- The report response returns `summary`, so reporting the last open
  question leads straight to the result.
- The student sees "Siguiente pregunta" or "Ver resultados" after
  reporting, and the result says how many reported questions weren't
  scored.

**Files Changed:** `app/practice/question_reports.py`,
`app/practice/routes.py`, `app/static/app.js`, `app/static/index.html`,
`tests/app/test_question_reports.py`.

**Commit:** see PR for T073.

## Regression Prevention

### Tests Added

- `test_a_question_reported_before_answering_is_skipped_and_not_scored`
- `test_reporting_the_last_open_question_returns_the_result`
- `test_a_question_reported_after_answering_keeps_its_score`
- `test_student_reports_and_tutor_resolves_in_the_browser` now reports a
  question without answering it, skips it and reaches the result.

- `test_navigation_labels_follow_the_result_not_the_position` (PR #87
  review): "Ver resultados" appears only when the result exists; on the
  last question with an earlier one still open, both the skip button and
  the normal button say "Siguiente pregunta" and lead to the open
  question.
- Both report browser tests run in the required CI browser suite (floor
  raised to 31, none skipped).

### Regression Guard

`RCA-009` in `docs/rca/regression-guards.yaml`.

## Verification

### Fix Verification

The API tests and the browser test pass locally
(`MENTOR_PRO_BROWSER=1`); the first browser run caught a skip button left
visible after answering a reported question, fixed before commit.

## Lessons Learned

### What could improve

- A side action added to a step-by-step flow needs a test for each way
  the student can leave that step, not only the expected path.
