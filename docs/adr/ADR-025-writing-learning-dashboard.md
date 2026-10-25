# ADR-025: Writing Progress in the Learning Dashboard

> **Status:** Accepted (Product Owner task T027)
> **Date:** 2026-10-25

---

## Context

"Mi progreso" (ADR-015) shows multiple-choice status for four subjects.
Producción escrita now has submissions and completed tutor evaluations
(ADR-024), and T020 defined a separate progress model per EE criterion
(`app/writing/progress.py`, ADR-019) that the application never showed.

---

## Decision

### Separate component and endpoint

- "Producción escrita" is the fifth tab of "Mi progreso". Its data comes
  from a new `GET /api/writing/progress`; `/api/dashboard` and the
  multiple-choice statuses are unchanged.
- The tab hides the multiple-choice metrics and shows only writing
  indicators; the six mastery statuses are never applied to rubric scores.
- A button opens the existing Producción escrita level list.

### Evidence

- Scores come only from `completed` human evaluations
  (`writing.evaluation`); `pending`, `in_progress` and `voided`
  evaluations give no score. Generated exercises are never evidence.
- The endpoint reads the application database only; automated tests use
  `mentor_pro_test` (ADR-016), so test records never reach the student
  dashboard.
- Nothing is written: drafts, submissions and evaluations are only read.

### Indicators

- Activity: submissions, completed evaluations, pending evaluations (a
  submission without a completed or voided evaluation), per level L1–L5
  the exercises submitted and evaluated, and the last practice date (the
  latest submission or saved draft).
- Per criterion EE01–EE20: official code and wording, latest and best
  points (0–4), number of scored evaluations, last evaluation date, and a
  status:
  - **Evaluado**: at least one scored completed evaluation;
  - **Evaluación pendiente**: no score yet, but a submission awaiting
    evaluation targets the criterion as scorable;
  - **Sin evaluar**: otherwise.
- "No evaluable" (EE19/EE20 on typed work) is counted apart and never
  enters scores, averages or denominators.
- Per dimension (official mapping in the rubric file): the average of the
  latest points of the criteria actually evaluated, shown "de 4", with the
  number of evaluated criteria of the dimension. No dimension weights, no
  weighted total and no examination grade.
- Coverage (evaluated, pending, unassessed of 20) is shown apart from
  performance.

---

## Consequences

- An unassessed criterion shows no number, so it cannot look mastered.
- A dimension average from one criterion is shown with its coverage
  ("1 de 12 criterios evaluados") so it is not read as the whole
  dimension.

---

## Related

- [ADR-015](ADR-015-repeat-aware-learning-status.md),
  [ADR-016](ADR-016-test-database-isolation.md),
  [ADR-019](ADR-019-produccion-escrita-foundation.md),
  [ADR-024](ADR-024-tutor-writing-evaluation.md)
- `docs/progress/task_T027_result.md`
