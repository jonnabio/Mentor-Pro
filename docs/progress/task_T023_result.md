# Task T023 Result: Populate Nivel 1 Writing Exercises

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-022](../adr/ADR-022-nivel-1-correction-exercises.md)

---

## Implementation

| File | Change |
|------|--------|
| `app/writing/editing.py` (new) | `conventions_editing` generation: prompt, parsing, assembly into exercise + tutor-only reference, checks W09–W12, review with `errors_genuine`, `reference_correct`, `unambiguous`; `EDIT_MAX_TOKENS` 8000; truncated output counts as one bounded request |
| `app/writing/seeding.py` (new), `scripts/dev/seed_writing_l1.py` (new) | Inventory per category; generate only missing; report attempts, calls, tokens, cost, gap |
| `app/writing/store.py` | `writing.reference_correction`; `generation_attempt.reference`; `reference_correction()`, `source_texts()` |
| `app/writing/generation.py` | Optional exercise type; shared checks cover the text to correct |
| `app/writing/contracts.py`, `writing-exercise.schema.json` | `title_es`; `conventions_editing` needs `source_text_es`; reference fields rejected in exercise records |
| `app/writing/routes.py`, `app/static/*` | Title and "Texto para corregir" above the editor; deliverable "El texto completo, ya corregido" |
| `scripts/dev/fixtures/writing-exercises-L1-T023.json` (new) | The three exercise records (no references) for test-database runs |
| `scripts/dev/practice_e2e.py` | Nivel 1 steps (desktop, mobile) |
| `tests/app/test_writing_editing.py` (new) | 32 tests |

Unchanged: rubric descriptors, curriculum baseline, multiple-choice engine,
budgets, free-only routing. No grading, no tutor interface.

---

## Approved Nivel 1 Inventory (student database)

| Exercise | Criteria | Text | Errors (tutor reference) | Review |
|----------|----------|------|--------------------------|--------|
| `PE-L1-futbol-comunidad-f136a4` — El fútbol en mi comunidad | EE07, EE08 | 79 words | las niños → los niños; se reúne → se reúnen; La entrenadores → Los entrenadores; enseña → enseñan; el valores → los valores | all 2 |
| `PE-L1-manglares-terraba-cafb78` — El manglar de Térraba | EE09, EE11, EE15 | 88 words | viodiversidad → biodiversidad; umedal → humedal; ay → hay; rapido → rápido | all 2 |
| `PE-L1-feria-ciencia-escuela-c9576f` — La feria de la ciencia | EE16, EE17, EE18 | 83 words | variados, Los → variados. Los; experimentos proyectos → experimentos, proyectos; preguntan cuál → preguntan ¿cuál; también → También; san josé → San José | all 2 |

All three pass `validate_exercise`; references are in
`writing.reference_correction` only.

**Manual review.** The feria text's indirect question admits two valid
corrections ("preguntan: ¿cuál …?" or no question marks); the model
documented no ambiguity and the review passed it. The ambiguity was added
to that exercise's tutor-only `ambiguities_es` as a human-review note. Other
observations: the manglar text has a redundant sentence ("Cada árbol es un
árbol que sostiene la vida") and a non-expository closing sentence; two
exercises say "No agregues" (tú form) instead of voseo; "stands" is an
anglicism.

---

## Generation (four seeding runs, free models, USD 0)

| Category | Requests | Accepted | Rejection reasons |
|----------|----------|----------|-------------------|
| Capitalization and punctuation | 11 | 1 | truncated output ×6 (one at 4000, five at 8000 tokens); W08 review (reference incorrect, ambiguous); W03 "rúbrica" in student text; W09/W11 no-change corrections and a repeated phrase; W10 reference mismatch; W11 rejected a valid comma-to-period fix (validator defect, fixed) |
| Spelling | 4 | 1 | W08 clarity ×2 (once also language); W11 "ambiante → ambiente" labelled as b/v |
| Agreement | 3 | 1 | truncated ×1, empty output ×1 |

Totals: 20 generation requests (3 accepted, 17 rejected), 30 OpenRouter
calls, 26 001 input and 134 502 output tokens, provider-reported cost USD 0
(complete). Models: nvidia/nemotron-3-ultra-550b-a55b:free (generation),
nvidia/nemotron-3.5-super-vl:free (review).

---

## Verification

| Check | Result |
|-------|--------|
| Live, `http://127.0.0.1:8000`, desktop and mobile | 15/15: three exercises listed; each shows its text and instructions; typing, word counter and draft save work; 15 reference strings and rubric wording absent from HTML, browser storage and every API response |
| Live data | One draft saved to prove saving, then deleted; student database has 0 drafts and 0 submissions before and after; no submission was made |
| Browser suite (test database) | 309/309, including L1 draft, resume, submission and reference absence after submission |
| Reference confidentiality (API) | Every student endpoint, `/` and `app.js` scanned in tests |
| Suite | 467 passed |
| ACE gate | `VERIFY_RESULT=pass gate=all` |
| Multiple choice | 78 objectives; dashboard served |

Screenshots: [L1 list](screenshots/T023/desktop-l1-list.png),
[exercise (desktop)](screenshots/T023/desktop-l1-1.png),
[exercise (mobile)](screenshots/T023/mobile-l1-3.png).

---

## Limitations

- Only one free model generates; it truncates often even at 8000 tokens, so
  a category may need several seeding runs.
- The review missed one ambiguity; ambiguity detection is not deterministic.
- W11 checks the kind of change, not whether the error is real; that relies
  on the review.
- The editor starts empty: the student retypes the whole text.
