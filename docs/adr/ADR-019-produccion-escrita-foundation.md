# ADR-019: Producción Escrita Foundation

> **Status:** Accepted (Product Owner task T020)
> **Date:** 2026-10-24

---

## Context

The baseline holds EE01–EE20 as `written_rubric` assertions (ADR-006,
ADR-007), which the multiple-choice practice never offers (ADR-008). The
Product Owner wants written production as a fifth student-facing practice
component under Español. This task defines its data model only: no
generation, no writing screen.

---

## Decision

### Separate component, separate records

Producción escrita is not a multiple-choice objective. It gets its own
reference data, contracts and PostgreSQL schema (`writing`), and its own
progress. `curriculum.*`, `practice.*`, the 78 objectives and the mastery
calculation (ADR-015) are unchanged; `app/writing/` neither imports
`app.practice` nor queries those tables.

### Reference data (`curriculum/writing/`)

- `MEP-RUBRICA-PE-2026.json`: the official rubric transcribed verbatim
  (dimensions, weights, 20 statements, 100 descriptors, counting note,
  PDF pages, source SHA-256). The rubric is the authority for descriptors;
  baseline records stay the authority for curriculum IDs. One wording
  difference (EE05) is recorded, not corrected.
- `exercise-levels.json`: five levels with exercise types, deliverable
  range, core and allowed criteria. A level never scores part of a
  criterion; every targeted criterion uses its full official descriptors.

| Level | Core criteria |
|-------|---------------|
| L1 `writing_conventions` | one or more of EE07–EE18 |
| L2 `idea_development` (introduction paragraph) | EE03, EE04 |
| L3 `paragraph_writing` (development or conclusion) | EE03 + EE05 or EE06 |
| L4 `guided_composition` | EE01–EE06 |
| L5 `full_composition` | EE01–EE20 |

The criteria mapping is in
`docs/planning/2026-10-24-produccion-escrita-mapping.md`.

### Contracts (`.ace/schemas/writing/`, JSON Schema 2020-12)

- **Exercise:** ID and type, level, difficulty, `es-CR`, topic and
  communicative situation, instructions, deliverable (unit, range, words,
  time, evidence mode), target criteria, evaluation parameters (one per
  target, `rubric_ref` `MEP-RUBRICA-PE-2026#EEnn`, `scored` or
  `not_evaluable`), provenance (baseline version, assertion IDs, source
  documents with checksums, authorship).
- **Evaluation (human):** submission reference and evidence mode, evaluator
  role (no names), status `pending | in_progress | completed | voided`, one
  score per target criterion (`scored` with 0–4 points, `not_evaluable`,
  `pending`), optional `non_normative_uses`, feedback in Spanish. No
  student-identifying fields are allowed.
- `app/writing/contracts.py` checks what the schemas cannot: level fit, core
  criteria, rubric references and checksum, assertion IDs, evidence rules,
  and points agreeing with counted uses.

### Handwritten evidence

EE19 and EE20 are scored only from handwritten evidence. For typed work they
must be `not_evaluable` (`handwritten_evidence_required`), in both the
exercise and the evaluation. L5 under exam conditions is handwritten; a
typed L5 rehearsal is allowed and records them as not evaluable.

### Storage (`app/writing/store.py`, schema `writing`)

`exercise`, `submission` (typed text or a handwritten-image reference),
`evaluation` (full JSON record plus columns) and `criterion_score`, with
CHECK constraints mirroring the contracts. Single student; no student ID.
Records are validated before insert. The store is not wired into the app.

### Progress (`app/writing/progress.py`)

From completed evaluations only: per criterion the latest and best points,
number of scored evaluations and not-evaluable count; per dimension the
average of latest points with coverage (criteria with evidence of the
total). No weighted grade and no mapping to the six multiple-choice
statuses; a Spanish notice says these are not official MEP grades.

---

## Risks

- Typed input with autocorrection hides convention errors (EE07–EE18); the
  writing screen must disable it.
- The rubric text is a manual transcription; the PDF checksum and page
  references make it checkable.
- Human evaluation is the only evaluator; consistency between evaluators is
  not measured yet.

---

## Consequences

- Generation (future) must emit records that pass `validate_exercise`.
- A writing screen and an evaluation workflow are separate future tasks.

---

## Related

- [ADR-006](ADR-006-curriculum-baseline-v1.md),
  [ADR-008](ADR-008-practice-configuration-api.md),
  [ADR-015](ADR-015-repeat-aware-learning-status.md)
- `docs/progress/task_T020_result.md`
