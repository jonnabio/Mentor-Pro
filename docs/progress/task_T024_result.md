# Task T024 Result: L1 Writing Editor and Editorial Quality

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-023](../adr/ADR-023-l1-editor-and-editorial-revisions.md)

---

## Changes

| File | Change |
|------|--------|
| `app/static/*` | L1 editor starts with a copy of the text; "Restaurar texto original" with confirmation; L2–L5 unchanged |
| `app/writing/routes.py` | `editable_source`, `revision`; submitted exercises show the revision answered |
| `app/writing/store.py` | `writing.exercise_revision`; `submission.exercise_revision`; `record()`, `revisions()`, `add_revision()`, revision-aware `reference_correction()` |
| `app/writing/revisions.py`, `scripts/dev/revise_writing_l1.py` (new) | Validated, repeatable editorial revisions |
| `scripts/dev/fixtures/writing-revisions-T024.json` (new) | The three revisions |
| `app/writing/editing.py` | W13 voseo, W14 repetition, W15 question ambiguity; review `meaning_preserved`, `natural_text`; prompt `writing-edit-1.1` |
| `scripts/dev/fixtures/writing-exercises-L1-T023.json` | Now the revised (current) records |
| `scripts/dev/practice_e2e.py`, `tests/app/test_writing_editing.py` | Editor and revision tests |

No change to the curriculum, the rubric, budgets or model routing.

---

## Editorial Revisions (student database, revision 2 each)

| Exercise | Revision |
|----------|----------|
| El fútbol en mi comunidad | "No cambies" → "No cambiés" |
| El manglar de Térraba | "Cada árbol es un árbol que sostiene la vida." → "Sus raíces también protegen la costa de las olas fuertes."; "La canción del viento entre las ramas recuerda la vida." → "Por eso, conservar el manglar beneficia a toda la comunidad."; "No agregués ni quités" |
| La feria de la ciencia | "los padres visitan los stands y preguntan cuál…?" → "las familias visitan los puestos y preguntan: cuál…?" (one correction: "preguntan: ¿Cuál"); documented alternative "¿cuál"; "No agregués ni quités" |

All three revisions passed W02–W07 and W09–W15. The revision-1 records,
references (including the earlier ambiguity note), generation histories
and validation results are unchanged. There were no submissions, so no
answered version was affected. Before the revisions, the new checks flagged
exactly the reported issues: W13 on all three, W14 ("árbol") on the manglar
text, W15 on the feria question.

---

## Verification

| Check | Result |
|-------|--------|
| L1 editor starts with the text to correct | Browser (desktop, mobile) |
| Viewing an unchanged copy saves no draft | Browser |
| Edits persist after reload; the original text is unchanged | Browser |
| Restore asks first; "Conservar" keeps edits; restore resets the editor only | Browser |
| L2–L5 editors start empty, no restore action | Browser |
| Submitted answers keep their revision | `test_submission_keeps_the_revision_it_answered` |
| Revisions traceable, validated, idempotent; invalid revision refused | Tests; live run (second run "present") |
| Tutor references absent from student responses (all revisions) | Tests; live check of the three exercises |
| Live app | Serves revision 2 of all three; 0 drafts and 0 submissions in the student database |
| Suite | 472 passed |
| Browser | 319/319 |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Screenshots: [L1 editor (mobile)](screenshots/T024/mobile-writing-l1.png),
[L1 editor (desktop)](screenshots/T024/desktop-writing-l1.png).

---

## Limitations

- Hand-written revisions get deterministic checks only, not a model review.
- W13 covers common tú forms, not every verb; W14 does not detect poetic or
  vague sentences (the review's `natural_text` does).
- New generations under prompt 1.1 were not run live in T024.
