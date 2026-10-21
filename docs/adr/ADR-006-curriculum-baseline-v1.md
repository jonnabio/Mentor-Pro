# ADR-006: Curriculum Baseline v1.0 and Approved-Baseline Grounding

> **Status:** Accepted (Product Owner decision)
> **Date:** 2026-10-21

---

## Context

The curriculum ingestion assessment
(`docs/requirements/2026-10-21-curriculum-ingestion-assessment.md`) found the
PNE Tracker 2026 workbook internally consistent (98 objectives, 344
evidencias) but not verifiable against official MEP 2026 documents, which are
not held. Under ADR-005 rules only `official` records could ground items, so
generation would abstain for every objective.

---

## Decision

### 1. Baseline authority

- The workbook is the definitive application curriculum baseline
  **`PNE2026-SUM-v1.0`**. Extraction is not repeated; MEP 2026 PDFs are not
  required to proceed.
- Objective codes, subjects, bloques, afirmación text, evidencias and their
  numbering, concepts, activities, source citations and planned item counts
  are stored verbatim. No rewriting, merging or reinterpretation.

### 2. Two independent labels

| Label | Values | Meaning |
|-------|--------|---------|
| `provenance` | `official` \| `secondary` | Where the wording comes from. Workbook records stay `secondary`. |
| `baseline_status` | `approved` \| `withdrawn` | Product Owner approval for use as grounding. |
| `verification_status` | `unverified` \| `verified` \| `discrepancy` | Comparison with official MEP wording. |

A multiple-choice record may ground items if it is `official` **or**
`baseline_status = approved`. Items record `grounding_basis`
(`official` \| `approved_baseline`); `approved_baseline` content must never be
presented as official MEP wording.

### 3. Revisions

Discrepancies found by future official verification are handled by a new
baseline version (e.g. `PNE2026-SUM-v1.1`). A baseline version is immutable:
re-importing a different workbook under the same version is refused.

### 4. Practice scope vs assessment type

- **Practice scopes:** `single_objective`, `selected_objectives`,
  `subject_simulation` (all objectives or a subset of one subject).
- **Assessment types:** `multiple_choice`, `written_rubric`.
- Only `multiple_choice` objectives are selectable. The 20 Español `EE`
  written-production criteria are imported as `written_rubric` (ID application
  code `PE`) and excluded from generation and simulation.
- Workbook codes (`EL01`, `M07`, `C01`, `ES01`) are the stable user-facing
  identifiers; every objective is individually selectable.

### 5. Privacy

`Logrado ✓` and all student progress are excluded. Public manifests use
generic file names. Git history is not rewritten without separate approval.

### 6. Storage

v1.0 catalog: SQLite (`curriculum/schema.sql`), five tables `source_document`,
`subject`, `block`, `assertion`, `evidence`, rebuilt by
`python -m curriculum.importer`. The catalog is read-only reference data; the
PostgreSQL direction in ADR-004 for application data is unchanged.

---

## Alternatives Considered

### Alternative 1: Wait for official MEP 2026 documents

- **Pros:** Every item officially grounded.
- **Cons:** Blocks all generation indefinitely.
- **Why rejected:** Product Owner decision.

### Alternative 2: Relabel workbook records as `official`

- **Pros:** No rule changes.
- **Cons:** Misrepresents provenance.
- **Why rejected:** Violates honest labelling.

---

## Consequences

### Positive

- All 78 multiple-choice objectives become practisable.
- Provenance stays truthful and auditable.

### Negative

- Items grounded on paraphrased evidencias may diverge from official wording
  until verified.

### Neutral

- `.ace/standards/question-engine.md` sections 3, 4 and 6 amended by this ADR.
- Schemas: curriculum-record 1.1, coverage-plan 1.1, item `grounding_basis`;
  checker 1.1.0.

---

## Related

- [ADR-004](ADR-004-web-app-stack.md), [ADR-005](ADR-005-question-engine-skill-suite.md)
- Import report: `docs/progress/task_T002_result.md`
