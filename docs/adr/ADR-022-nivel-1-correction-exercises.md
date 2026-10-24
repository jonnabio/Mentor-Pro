# ADR-022: Nivel 1 Correction Exercises and Tutor-Only References

> **Status:** Accepted (Product Owner task T023)
> **Date:** 2026-10-24

---

## Context

Nivel 1 (Convenciones de escritura) had no exercises. The Product Owner
asked for short text-correction exercises, one per group of convention
criteria, each with a tutor-only reference correction, generated with the
existing OpenRouter pipeline (ADR-020) and shown in the existing screen
(ADR-021).

---

## Decision

### Exercise type and categories

L1 exercises use `conventions_editing`: an original expository text of
40–120 words with deliberate errors. The inventory plan is one exercise per
category:

| Category | Criteria |
|----------|----------|
| `capitalization_punctuation` | EE16, EE17, EE18 |
| `spelling` | EE09, EE11, EE15 |
| `agreement` | EE07, EE08 |

Criteria statements come from the baseline catalog and descriptors from
`curriculum/writing/MEP-RUBRICA-PE-2026.json`, joined as in ADR-020; no new
rubric table. The exercise record references the rubric by ID and checksum.

### Tutor-only reference correction

The model returns the corrected text, the exact corrections (error, fix,
criterion) and documented ambiguities. Code removes them from the exercise
record and stores them in `writing.reference_correction` (and in the
generation attempt row for audit). No student endpoint reads that table;
the contract rejects exercise records that contain reference fields; the
student view adds only `title_es` and `source_text_es`. The reference is
never shown after submission and does not grade.

### Validation

Shared checks W01–W07 (ADR-020) plus:

| Check | Rule |
|-------|------|
| W09 | 40–120 words, 3–8 sentences, 3–8 corrections; each error occurs once, differs from its fix and has a target criterion; every target criterion has an error |
| W10 | Applying the corrections to the text yields exactly the reference text |
| W11 | Each fix is the kind of change its criterion covers (letters for EE09–EE14, accents for EE15, punctuation for EE16–EE17, case for EE18, a few words for EE07–EE08) |
| W12 | Word overlap with every stored L1 text below 0.5 |
| W08 | Independent review adds `errors_genuine`, `reference_correct`, `unambiguous`; all eight scores must be 2 |

### Generation limits

Correction exercises use their own output limit (`EDIT_MAX_TOKENS` = 8000)
because the first live request was truncated at 4000 tokens by reasoning.
A truncated or failed model response counts as one of the three bounded
requests. Daily request and USD budgets, free-only routing and the
multiple-choice settings are unchanged.

### Seeding

`scripts/dev/seed_writing_l1.py` (logic in `app/writing/seeding.py`) reads
the stored inventory, generates only missing categories, never overwrites
exercises or touches drafts and submissions, and reports attempts, calls,
tokens, cost and the remaining gap. A budget stop ends the run.

### Student screen

The existing view shows the title, the text to correct above the editor and
"El texto completo, ya corregido" as the deliverable. The editor starts
empty; the student writes the corrected text.

---

## Consequences

- Tutor evaluation (future) reads `writing.reference_correction`.
- W11 accepts any letter-level change for its letters; the review judges
  whether the error is real.

---

## Related

- [ADR-019](ADR-019-produccion-escrita-foundation.md),
  [ADR-020](ADR-020-writing-exercise-generation.md),
  [ADR-021](ADR-021-student-writing-practice.md)
- `docs/progress/task_T023_result.md`
