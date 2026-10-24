# ADR-018: Dashboard-Driven Objective Practice

> **Status:** Accepted (Product Owner task T019)
> **Date:** 2026-10-24

---

## Context

The learning dashboard (ADR-015) shows a status per objective but offers no
way to act on it. The practice form (ADR-008, ADR-013) already supports a
single-objective practice with bank reuse and generation (ADR-014).

---

## Decision

- Each dashboard objective gets one action: "Practicar este objetivo", or
  "Repasar este objetivo" for "Dominio consolidado". All six statuses have
  it.
- The action only fills the existing form, in the browser: the main menu is
  reset, then the subject, scope "Un objetivo", the objective (code and text
  from `GET /api/objectives`, unchanged), "Intermedia" and 5 questions are
  selected. The settings stay editable. No session is created and no
  generation job starts until the student presses "Generar práctica"; the
  normal `POST /api/practice/sessions` path (bank first, then generation)
  is unchanged.
- The form shows a short notice naming the objective chosen from the
  dashboard.
- Actionable display: "Necesita refuerzo" items are highlighted (border and
  "Prioridad" tag), "En progreso" items are tagged, and the server adds
  Spanish recommendations for both. "Dominio consolidado" keeps its
  maintenance recommendation. Order stays the curriculum order, so
  unpracticed objectives stay where they were.
- Question counts other than 5 remain disabled ("próximamente"), as before;
  set limits (ADR-011) are unchanged.

No change to mastery calculation, thresholds, curriculum, budgets or
validation.

---

## Related

- [ADR-013](ADR-013-student-practice-sessions.md),
  [ADR-014](ADR-014-validated-question-bank.md),
  [ADR-015](ADR-015-repeat-aware-learning-status.md)
- `docs/progress/task_T019_result.md`
