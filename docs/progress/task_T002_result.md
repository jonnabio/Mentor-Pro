# Task T002 Result: Curriculum Catalog Import (PNE2026-SUM-v1.0)

> **Date:** 2026-10-21
> **Status:** Verified
> **Decision:** [ADR-006](../adr/ADR-006-curriculum-baseline-v1.md)

---

## Summary

The PNE Tracker 2026 workbook was imported into a SQLite curriculum catalog as
baseline `PNE2026-SUM-v1.0`. All curricular text is stored verbatim; student
progress is excluded. Generation rules now accept approved-baseline records as
grounding while keeping them labelled `secondary` and `unverified`.

---

## Import Report

| Item | Value |
|------|-------|
| Command | `.venv/Scripts/python.exe -m curriculum.importer --workbook <workbook.xlsx>` |
| Output | `data/curriculum.sqlite` (git-ignored, rebuildable) |
| Workbook SHA-256 | `cce57db40afacdb2f6d2492c39ba9df6c1bc398941c1c7fb9cff8ec28bcc19d3` (unchanged after import) |
| Workbook reference | `PNE-Tracker-2026-workbook.xlsx` (generic manifest name) |
| Status, second run | `unchanged` (idempotent) |
| Warnings | 0 |
| SQLite `integrity_check` / `foreign_key_check` | `ok` / no violations |

### Counts

| Component | Assessment type | Bloques | Objectives | Evidencias |
|-----------|----------------|---------|-----------|-----------|
| Español — lectura (`EL`) | multiple_choice | 1 | 8 | 53 |
| Español — escritura (`EE`) | written_rubric | 5 | 20 | 20 |
| Matemáticas (`M`) | multiple_choice | 5 | 22 | 108 |
| Ciencias (`C`) | multiple_choice | 4 | 19 | 82 |
| Estudios Sociales (`ES`) | multiple_choice | 2 | 29 | 81 |
| **Total** | | **17** | **98** | **344** |

Source documents: 3 (the workbook, `held`, `secondary`; MEP marco sumativo
2026 and rúbrica 2026, `cited_not_held`).

### Identifier examples

| Workbook code | Catalog ID |
|---------------|-----------|
| `EL01` | `PNE2026-PRI-ESP-SUM-B1-A1` |
| `M07` | `PNE2026-PRI-MAT-SUM-B1-A7` |
| `C01` | `PNE2026-PRI-CIE-SUM-B1-A1` |
| `ES01` | `PNE2026-PRI-EST-SUM-B1-A1` |
| `EE20` | `PNE2026-PRI-ESP-PE-B5-A20` |

---

## Validation Results

| Requirement | Evidence | Result |
|-------------|----------|--------|
| 98 assertions, 344 evidencias | `test_totals` | Pass |
| Counts for all five components | `test_component_counts` | Pass |
| No broken objective–evidence links | `test_relationships_and_identifiers`, `foreign_key_check` | Pass |
| No missing objective codes | Stored codes = workbook codes | Pass |
| No duplicate evidencia IDs | 344 unique | Pass |
| No student data | No `Logrado` column; generic file reference | Pass |
| Text verbatim | Every catalogue and evidence cell compared | Pass |
| Each multiple-choice objective retrievable alone | All 78 via `single_objective` | Pass |
| Multiple selection keeps evidencias | `selected_objectives` M01, M07, M14, M22 | Pass |
| All objectives of a subject together | `subject_simulation` per subject (8/22/19/29) | Pass |
| Rubric records separate | 20 `EE` via `list_rubric_criteria`; rejected by selection | Pass |
| Provenance labels | All `secondary` / `approved` / `unverified` | Pass |

Test suite: 139 passed (`tests/ace`, `tests/curriculum`), including 9
acceptance tests on the real workbook. `bash .ace/scripts/verify.sh` →
`VERIFY_RESULT=pass gate=all`. Mutation check: disabling the copy-column and
evidence-count validations made two tests fail as expected; code restored.

---

## Schema Changes

| Artifact | Change |
|----------|--------|
| `curriculum/schema.sql` | New: `subject`, `source_document`, `block`, `assertion`, `evidence` |
| `curriculum-record.schema.json` | 1.1: `baseline_version`, `baseline_status`, `verification_status`, `workbook_code`, `assessment_type`; `PE` IDs; `produccion_escrita` |
| `question-item.schema.json` | Optional `grounding_basis` |
| `coverage-plan.schema.json` | 1.1: `scope` replaces `mode`; `baseline_version`, `objective_codes`, `coverage_strategy` |
| `item_checker.py` | 1.1.0: approved-baseline grounding; rubric records never ground |
| `.ace/standards/question-engine.md` | Sections 2–4, 6 amended per ADR-006 |

---

## Warnings and Limitations

| Topic | Note |
|-------|------|
| Acceptance tests need the workbook | Skipped with an explicit reason when `references/original/` lacks it (e.g. CI) |
| Bloque ordinals | Derived from first appearance in `07 Catálogo` |
| `EE` numbering | Workbook numbers rubric criteria 1–20 across five bloques; kept as is |
| Student name in Git history | Present in pushed commit `42adbe7`; history not rewritten (needs separate approval) |
| Storage | SQLite catalog only; application database per ADR-004 later |

---

## Files

- Created: `curriculum/` (`schema.sql`, `importer.py`, `catalog.py`),
  `tests/curriculum/`, `tests/ace/ace_paths.py`, `requirements.txt`,
  `docs/adr/ADR-006-curriculum-baseline-v1.md`, this report.
- Modified: `references/MANIFEST.sha256`, assessment document, standard,
  knowledge file, 5 skills, 3 schemas, checker, `.aceconfig`, `.gitignore`,
  `requirements-dev.txt`, `tests/ace/*`, `docs/progress/tasks.json`,
  `docs/context/ACTIVE_CONTEXT.md`.
