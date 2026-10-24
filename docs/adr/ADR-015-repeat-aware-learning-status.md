# ADR-015: Repeat-Aware Learning Status

> **Status:** Accepted (Product Owner task T014 and amendments)
> **Date:** 2026-10-23

---

## Context

T014 adds a student learning dashboard with six application-defined learning
statuses. Because the question bank (ADR-014) reuses questions, repeated
answers could inflate mastery. There are no accounts: the application serves
one anonymous student.

---

## Decision

### Source of truth

All recorded answers (`practice.answer` joined to `practice.item`) belong to
the single student, across practices, browser tabs and sessions. A question
is identified by its canonical `item_id`; the browser token is not used.
Nothing is deleted or overwritten; statuses are recomputed from the history
on every request.

### Metrics per objective (`app/practice/mastery.py`)

Total answers, practice accuracy, distinct questions answered, first-attempt
accuracy on distinct questions (mastery accuracy), repeated-question
accuracy, repeat exposure rate (repeated answers / all answers), distinct
evidencias assessed. The first attempt is the earliest answer to an
`item_id`; unanswered questions are never attempts.

### Status (exact fractions, no rounding; thresholds configurable)

| Status | Label | Rule |
|--------|-------|------|
| `unpracticed` | Sin practicar | 0 distinct questions |
| `insufficient_evidence` | Evidencia insuficiente | 1–4 distinct questions |
| `needs_reinforcement` | Necesita refuerzo | ≥ 5 distinct, mastery < 60 % |
| `in_progress` | En progreso | ≥ 5 distinct, 60 % ≤ mastery < 80 % |
| `good_proficiency` | Buen dominio | ≥ 5 distinct, 80 % ≤ mastery ≤ 90 % |
| `consolidated_mastery` | Dominio consolidado | ≥ 5 distinct, mastery > 90 % |

Environment: `MENTOR_PRO_MASTERY_MIN_DISTINCT`,
`MENTOR_PRO_MASTERY_REINFORCEMENT_BELOW_PCT`,
`MENTOR_PRO_MASTERY_PROGRESS_BELOW_PCT`, `MENTOR_PRO_MASTERY_GOOD_UP_TO_PCT`.
"Dominio consolidado" shows "¡Excelente dominio! Practicá de vez en cuando
para mantener lo aprendido." No decay or scheduled review.

### Dashboard

`GET /api/dashboard`: every selectable objective (78) of the four subjects
with metrics and status, and per subject the six status counts, practice
accuracy, mastery accuracy and repeat exposure. The page shows practice and
mastery accuracy side by side and a notice that these are Mentor Pro
indicators, not official MEP performance levels.

### Exposure in practice composition

The bank (ADR-014) now prefers questions never served before according to
PostgreSQL history (all sessions), instead of the per-tab token; reused
questions are counted as repeats in the analytics.

---

## Consequences

### Positive

- Repeating a question cannot raise mastery; history stays complete.

### Negative

- With one global student, any testing in the same database counts as the
  student's history.

### Neutral

- The per-tab `browser_hash` column remains but no longer affects selection.

---

## Related

- [ADR-013](ADR-013-student-practice-sessions.md),
  [ADR-014](ADR-014-validated-question-bank.md)
- Report: `docs/progress/task_T014_result.md`
