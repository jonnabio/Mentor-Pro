# Task T022 Result: Student Writing Practice Interface

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-021](../adr/ADR-021-student-writing-practice.md)

---

## Changed Files

| File | Change |
|------|--------|
| `app/writing/routes.py` (new) | `/api/writing`: levels, exercises per level, student view, draft, submit |
| `app/writing/store.py` | `writing.draft`; `submission.client_request_id`; one submission per exercise; `exercises()`, `draft()`, `save_draft()`, `submit_typed()` |
| `app/main.py` | Writing router (stored exercises only) |
| `app/static/index.html` | Main-menu card "Producción escrita · Español"; writing view; submit dialog |
| `app/static/app.js` | Levels → exercises → exercise; editor, word counter, draft save and resume, submit once, save on leave |
| `app/static/styles.css` | Level and exercise choices, editor, submitted text |
| `scripts/dev/fixtures/writing-exercise-T021.json` (new) | The T021 exercise (content only) for test-database runs |
| `scripts/dev/practice_e2e.py` | `scenario_writing` (desktop and mobile) |
| `tests/app/test_writing_api.py` (new) | 8 API tests |

Unchanged: multiple-choice subjects, objectives and metrics; generation;
budgets; rubric and criteria. No grading and no tutor interface.

---

## Browser Acceptance (`mentor_pro_test`, desktop 1280 px and mobile 390 px)

| Step | Result |
|------|--------|
| Open Producción escrita from the main menu | Five levels with Spanish descriptions and counts |
| Empty level (L3) | "Todavía no hay ejercicios en este nivel" |
| L5 | Official conditions (paper, pen, one letter type, 90 minutes); no typed editor |
| Select L2, open "La alimentación saludable y el rendimiento escolar" | Topic, situation, ideas, 5 instructions, deliverable; no criteria or descriptors on the page |
| Editor | `spellcheck=false`, `autocorrect=off`, `autocapitalize=off`; counter "36 palabras" |
| Save draft, reload | Draft restored in the same exercise |
| Submit (dialog; "Seguir escribiendo" keeps editing; double click) | One request, one row |
| After submission | "Pendiente de revisión del tutor. Entregado el … (36 palabras)."; reload keeps it |
| Leave another exercise with unsaved text to the main menu | Draft saved; main menu with the four subjects |
| Layout | No horizontal overflow; no JavaScript errors |

Screenshots: [levels](screenshots/T022/desktop-writing-levels.png),
[draft (mobile)](screenshots/T022/mobile-writing-draft.png),
[submitted](screenshots/T022/desktop-writing-submitted.png),
[L5 (mobile)](screenshots/T022/mobile-writing-l5.png).

### Persisted records (test database, last run)

| Table | Row |
|-------|-----|
| `writing.submission` | `SUB-L2-alimentacion-saludable-rendimiento-9c16b3ba`, exercise `PE-L2-alimentacion-saludable-rendimiento-19a72a`, typed, 36 words, 1 paragraph |
| `writing.draft` | the same exercise (36 words, frozen after submission); `PE-L2-ambiente-intro-001` (6 words, saved on leaving) |
| `writing.evaluation` | none |

The student database was not used for the demonstration; the generated
exercise there stays unanswered.

---

## Verification

- Suite 435 passed (427 + 8); browser 295/295 (two runs);
  `VERIFY_RESULT=pass gate=all`.

## Limitations

- One submission per exercise; no resubmission.
- L5 has no image upload; the sheet goes to the tutor outside the app.
- The local server on port 8000 must be restarted to serve T022.
