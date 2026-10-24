# ADR-021: Student Writing Practice Interface

> **Status:** Accepted (Product Owner task T022)
> **Date:** 2026-10-24

---

## Context

T020 (ADR-019) defined the writing contracts and schema; T021 (ADR-020)
stores generated exercises. The student needs a screen to read an exercise
and write a typed answer, without grading and without generation.

---

## Decision

- **Entry:** a "Producción escrita · Español" card on the main menu opens a
  view of the same page (no framework, no new route). The four
  multiple-choice subjects and the 78 objectives are unchanged.
- **API** (`app/writing/routes.py`, `/api/writing`): levels with counts,
  exercises per level with state (`new`, `draft`, `submitted`), the
  student view of one exercise, `PUT …/draft`, `POST …/submit`. Only
  exercises already in `writing.exercise` are listed; nothing generates.
- **Student view:** topic, communicative situation, suggested ideas,
  instructions, deliverable description and plain requirements. Target
  criteria, evaluation parameters and rubric descriptors are never sent.
- **Typed work (L1–L4):** a textarea with `spellcheck=false`,
  `autocorrect=off`, `autocapitalize=off`, a word counter, "Guardar
  borrador" and "Entregar texto" with a confirmation dialog. Drafts are in
  `writing.draft` (one per exercise). Leaving the exercise saves unsaved
  changes first; the open exercise is restored after a reload.
- **Submission:** one per exercise (`uq_submission_exercise`, row lock);
  repeated or parallel requests return the first. The draft is frozen and
  the view shows "Pendiente de revisión del tutor". No evaluation row is
  created.
- **Handwritten work (L5):** the exercise and its official conditions
  (paper, blue or black pen, one letter type, 90 minutes) are shown; there
  is no typed editor and the API refuses typed drafts and submissions. EE19
  and EE20 are therefore never evaluated from typed text.
- **Tests:** browser runs use the test database (ADR-016) seeded with the
  T021 exercise (`scripts/dev/fixtures/writing-exercise-T021.json`, no
  student data) and the T020 examples.

---

## Consequences

- Resubmission and tutor evaluation are future tasks.
- Handwritten work has no upload yet; the tutor receives the sheet.

---

## Related

- [ADR-016](ADR-016-test-database-isolation.md),
  [ADR-019](ADR-019-produccion-escrita-foundation.md),
  [ADR-020](ADR-020-writing-exercise-generation.md)
- `docs/progress/task_T022_result.md`
