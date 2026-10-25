# ADR-023: L1 Editor and Editorial Revisions

> **Status:** Accepted (Product Owner task T024)
> **Date:** 2026-10-24

---

## Context

Students retyped the whole Nivel 1 text (ADR-022), and a manual review
found an undocumented ambiguity, redundant and non-expository sentences,
and tú forms in the instructions. Exercise records must stay traceable,
and a submitted answer must never change retroactively.

---

## Decision

### Editor

For `conventions_editing` the student view sets `editable_source`. A new
draft starts as a copy of `source_text_es`; a saved draft always wins on
reload. The copy is not unsaved work until the student changes it, so
viewing saves nothing. "Restaurar texto original" asks for confirmation
and resets only the editor; the saved draft stays until the student saves
again. The original text above the editor is read-only and no endpoint
changes it. L2–L5 editors start empty.

### Versioned editorial revisions

`writing.exercise_revision (exercise_id, revision ≥ 2, record, reference,
reason, author, checks, created_at)`. The original `writing.exercise.record`
and `writing.reference_correction` row are revision 1 and never change.
The student API serves the latest revision; a submission stores
`exercise_revision`, and a submitted student keeps seeing that revision.
`reference_correction(exercise_id, revision)` returns the tutor-only
reference of a revision.

Revisions are targeted replacements
(`scripts/dev/fixtures/writing-revisions-T024.json`, applied by
`scripts/dev/revise_writing_l1.py`): instructions, the text (applied to
both the text with errors and the reference) and corrections, plus
documented alternatives. Each revision passes W02–W07 and W09–W15 before
it is stored; applying a reason twice does nothing.

### Generation rules (prompt `writing-edit-1.1`)

| Check | Rule |
|-------|------|
| W13 | Instructions in Costa Rican voseo (no «Lee», «Corrige», «No cambies»…) |
| W14 | No content word twice in a sentence of the text, no repeated sentence, no two instructions with content-word overlap ≥ 0.6 |
| W15 | An added «¿» or «¡» needs a colon or sentence start before it, or a documented alternative |
| W08 | Review adds `meaning_preserved` and `natural_text` (all ten scores must be 2) |

Routing, retries and budgets are unchanged.

---

## Consequences

- Revisions written by hand are not reviewed by a model; the deterministic
  checks still apply.
- Tutors evaluating an answer must use the reference of the revision the
  student answered.

---

## Related

- [ADR-021](ADR-021-student-writing-practice.md),
  [ADR-022](ADR-022-nivel-1-correction-exercises.md)
- `docs/progress/task_T024_result.md`
