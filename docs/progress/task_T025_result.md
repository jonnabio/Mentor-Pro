# Task T025 Result: Populate L2 and L3 Writing Exercises

> **Date:** 2026-10-24
> **Status:** Done
> **Decisions:** [ADR-020](../adr/ADR-020-writing-exercise-generation.md)
> (generation, amended),
> [ADR-023](../adr/ADR-023-l1-editor-and-editorial-revisions.md) (revisions)

---

## Changes

| File | Change |
|------|--------|
| `app/writing/generation.py` | Checks W13 voseo, W14 repeated instructions, W16 ideas outside the paragraph type, W17 model text, W18 near-duplicate topic or situation; review adds `paragraph_scope`, `no_model_text`; prompt `writing-1.1` (scope, no model text), `writing-1.2` (sentences of at most 25 words); introduction and conclusion exercises are exactly one paragraph |
| `app/writing/contracts.py` | Introduction and conclusion exercises must be exactly one paragraph |
| `app/writing/seeding.py`, `scripts/dev/seed_writing_l2_l3.py` (new) | Composed-paragraph plan and idempotent seeding |
| `app/writing/revisions.py`, `scripts/dev/revise_writing_l1.py` | Revisions of composed exercises (instructions, ideas, situation, deliverable); `--specs`; dry run skips stored revisions |
| `scripts/dev/fixtures/writing-revisions-T025.json` (new) | Two revisions |
| `scripts/dev/fixtures/writing-exercises-L2L3-T025.json` (new) | Current L2/L3 records for test-database runs |
| `scripts/dev/practice_e2e.py`, tests | L2/L3 steps; 9 new generation tests |

Unchanged: curriculum, rubric, routing, budgets, multiple choice, L1.

---

## Final Inventory (student database)

| Level | Type | Exercise | Criteria |
|-------|------|----------|----------|
| L2 | Introduction | La alimentación saludable y el rendimiento escolar (T021, revision 2) | EE03, EE04 |
| L2 | Introduction | La puntualidad en la escuela y su efecto en el aprendizaje | EE03, EE04 |
| L2 | Introduction | La importancia de la empatía en la convivencia escolar | EE03, EE04 |
| L3 | Development (2 paragraphs) | El uso seguro de la bicicleta para ir a la escuela | EE03, EE05 |
| L3 | Development (2 paragraphs) | La importancia de dormir bien para el rendimiento escolar | EE03, EE05 |
| L3 | Conclusion (1 paragraph) | El uso adecuado de los baños escolares (revision 2) | EE03, EE06 |

All six pass `validate_exercise` and W13–W18; every generated exercise had
an independent review of 2 on all seven dimensions.

### Editorial revisions

- **Healthy eating (L2):** the two ideas outside the introduction
  (consequences, actions) were removed and the repetitive instructions were
  replaced by five short ones. Before: W14 and W16 failed; after: all pass.
- **Bathrooms (L3 conclusion):** the generator asked for "de 1 a 2 párrafos
  de conclusión" because the conclusion deliverable took the L3 range. This
  is now fixed in the generator and the contract, and the exercise was
  revised to one paragraph; "colegio" became "escuela". The review had not
  caught it.

---

## Generation (two seeding runs, free models)

| Run | Prompt | Requests | Accepted | Calls | Tokens in / out | Cost |
|-----|--------|----------|----------|-------|-----------------|------|
| 1 | writing-1.1 | 13 | 3 (L3 ×3) | 16 | 16 905 / 26 103 | USD 0 |
| 2 | writing-1.2 | 2 | 2 (L2 ×2) | 4 | 3 614 / 7 570 | USD 0 |

Rejections (10, run 1): W05 one sentence over 30 words ×9 (every case a
31–44-word communicative situation), W16 out-of-scope ideas ×2 ("La
resolución pacífica de conflictos" for an introduction; "Bajo rendimiento
escolar" counted as a consequence in a development exercise; one attempt had
both). The prompt now asks for situation sentences of at most 25 words; the
check is unchanged. Models: nemotron-3-ultra (generation),
nemotron-3.5-super-vl (review). Cost is provider-reported and complete.

---

## Verification

| Check | Result |
|-------|--------|
| Live, port 8000, desktop and mobile | 27/27: L2 3 exercises, L3 3 (2 development, 1 conclusion); empty editors, no restore action; draft saved and resumed in both levels; no rubric or reference content in 35 API responses; no overflow or errors; multiple-choice API and dashboard HTTP 200 |
| Live data | Test drafts deleted; 0 drafts and 0 submissions before and after; usage records 454 → 454 (no generation from opening); multiple-choice answers 381 unchanged |
| Browser suite (test database) | 335/335 |
| Suite | 481 passed |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Screenshots: [L2](screenshots/T025/desktop-L2-list.png),
[L3](screenshots/T025/desktop-L3-list.png),
[L3 mobile](screenshots/T025/mobile-L3-list.png).

---

## Limitations

- Instructions of the same paragraph type follow nearly the same five
  steps; topics and situations are distinct (W18), the instruction pattern
  is not.
- W16 is keyword-based ("rendimiento" passed as a reason in "La puntualidad
  … y su efecto en el aprendizaje"; "Mejora del rendimiento académico" is
  arguably an effect).
- The review missed the 1–2 paragraph conclusion; it was found manually.
- Only one free model generates.
