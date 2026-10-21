# Curriculum Ingestion Assessment: PNE Tracker 2026 Workbook

> **Date:** 2026-10-21
> **Role:** Architect (`curriculum-data-ingestion` skill, assessment only)
> **Status:** Awaiting approval — nothing imported or implemented

---

## Overview

Read-only assessment of worksheets `07 Catálogo` and `06 Evidencias` in
the PNE Tracker 2026 workbook (generic reference `PNE-Tracker-2026-workbook.xlsx`
in `references/MANIFEST.sha256`).
The workbook was opened with openpyxl and never saved. Curricular text is quoted
in its original Spanish.

| Property | Value |
|----------|-------|
| SHA-256 | `cce57db40afacdb2f6d2492c39ba9df6c1bc398941c1c7fb9cff8ec28bcc19d3` |
| Sheets | 9 (`01 Panel` … `09 Configuración`); 2 assessed |
| Formulas, merged cells, hidden rows/columns, validations | None in either sheet |

---

## 1. Workbook Structure

Both sheets: rows 1–2 are a title and a note, row 3 is blank, row 4 holds
headers, data starts at row 5.

### `07 Catálogo` — 98 rows, one per afirmación

| Col | Header | Type | Nulls | Distinct | Meaning |
|-----|--------|------|-------|----------|---------|
| A | `Código` | text | 0 | 98 | Workbook key (`EL01`, `M07`, …) |
| B | `Materia` | text | 0 | 4 | Subject |
| C | `Bloque MEP` | text | 0 | 17 | Bloque temático (or rubric criterion) |
| D | `Numeración` | text | 0 | 22 | `Afirmación n`; restarts per bloque |
| E | `Afirmación / criterio` | text | 0 | 98 | Afirmación text |
| F | `Conceptos detallados` | text | 0 | 98 | Didactic content (bulleted, multi-line) |
| G | `Actividad de comprobación` | text | 0 | 98 | Practice activity |
| H | `Fuente / página` | text | 0 | 19 | Source citation (free text) |
| I | `Cantidad evidencias` | number (float) | 0 | 12 | Evidence count |
| J | `Ítems previstos` | text | 0 | 9 | `n ítem(s) previsto(s)` or `criterio de rúbrica` |

### `06 Evidencias` — 344 rows, one per evidencia

| Col | Header | Type | Nulls | Distinct | Meaning |
|-----|--------|------|-------|----------|---------|
| A | `Objetivo` | text | 0 | 98 | Foreign key → `Código` |
| B | `N.º` | number (float) | 0 | 15 | Ordinal within objective (1…n) |
| C | `Evidencia / criterio verificable` | text | 0 | 344 | Evidencia text |
| D | `Materia` | text | 0 | 4 | Copy of catalogue `Materia` |
| E | `Logrado ✓` | boolean | 0 | 1 (all `False`) | **Student progress checkbox** |
| F | `Afirmación asociada` | text | 0 | 98 | Copy of catalogue column E |
| G | `Bloque temático` | text | 0 | 17 | Copy of catalogue column C |
| H | `Fuente` | text | 0 | 19 | Copy of catalogue column H |

### Relationship

```text
07 Catálogo.Código  1 ──── n  06 Evidencias.Objetivo
```

Columns D, F, G, H of `06 Evidencias` are denormalized copies of the catalogue.

---

## 2. How Concepts Are Represented

| Concept | Representation |
|---------|----------------|
| Subject | `Materia` text: `Español`, `Matemáticas`, `Ciencias`, `Estudios Sociales` |
| Objective | Not a separate entity: one `Código` = one afirmación |
| Bloque temático | `Bloque MEP` text; Español escritura embeds a weight, e.g. `Cohesión y coherencia discursiva (40 %)` |
| Afirmación | `Afirmación / criterio` + `Numeración` (unique per subject + bloque) |
| Evidencia | `06 Evidencias` rows, ordered by `N.º` |
| Curricular content | `Conceptos detallados`, `Actividad de comprobación` (workbook-authored) |
| Source | Free text: `Tabla 3, marco sumativo MEP 2026; pág. PDF n.` or `rúbrica MEP 2026; pág. PDF n.` |
| Assessment mode | Implicit in `Ítems previstos`: item count vs `criterio de rúbrica` |

Code prefixes: `EL` Español lectura, `EE` Español escritura (written-production
rubric), `M` Matemáticas, `C` Ciencias, `ES` Estudios Sociales.

The sheet's own note (A2) states: *"las afirmaciones siguen las matrices MEP,
las evidencias son paráfrasis didácticas."*

---

## 3. Record Counts

| Subject | Prefix | Bloques | Objectives (afirmaciones) | Evidencias | Ítems previstos |
|---------|--------|---------|---------------------------|------------|-----------------|
| Español — lectura | `EL` | 1 | 8 | 53 | 60 |
| Español — escritura (rubric) | `EE` | 5 | 20 | 20 | rubric |
| Matemáticas | `M` | 5 | 22 | 108 | 60 |
| Ciencias | `C` | 4 | 19 | 82 | 60 |
| Estudios Sociales | `ES` | 2 | 29 | 81 | 60 |
| **Total** | | **17** | **98** | **344** | **240** |

Evidencias per objective: min 1, max 15, mean 3.51.

### By bloque

| Subject | Bloque | Objectives | Evidencias |
|---------|--------|-----------|-----------|
| Español | Comprensión lectora | 8 | 53 |
| Español | Extensión y organización (20 %) | 2 | 2 |
| Español | Unidad temática (20 %) | 1 | 1 |
| Español | Cohesión y coherencia discursiva (40 %) | 3 | 3 |
| Español | Convenciones lingüísticas (15 %) | 12 | 12 |
| Español | Legibilidad y uniformidad (5 %) | 2 | 2 |
| Matemáticas | Números | 7 | 41 |
| Matemáticas | Geometría | 6 | 33 |
| Matemáticas | Medidas | 2 | 9 |
| Matemáticas | Relaciones y Álgebra | 4 | 12 |
| Matemáticas | Estadística y Probabilidad | 3 | 13 |
| Ciencias | Cuerpo humano | 5 | 17 |
| Ciencias | Biodiversidad | 5 | 19 |
| Ciencias | Energía | 3 | 24 |
| Ciencias | Geofísica | 6 | 22 |
| Estudios Sociales | Costa Rica: un espacio sociogeográfico de integración | 7 | 20 |
| Estudios Sociales | Costa Rica: su construcción histórica, geográfica y ciudadana | 22 | 61 |

---

## 4. Data Quality Findings

### Integrity checks — all passed

| Check | Result |
|-------|--------|
| Missing values (all 18 columns) | 0 |
| Duplicate `Código` | 0 |
| Duplicate (`Objetivo`, `N.º`) | 0 |
| Duplicate evidencia text (within or across objectives) | 0 |
| Orphan evidencias / objectives without evidencias | 0 / 0 |
| `N.º` contiguous from 1 per objective | Yes |
| `Cantidad evidencias` = actual evidence rows | 98 / 98 |
| Denormalized columns equal catalogue values | 344 / 344 |
| Title count (`344 REGISTROS`) = actual rows | Yes |
| Leading/trailing/double spaces | 0 |
| Code sequences without gaps | Yes |

### Issues to resolve

| # | Severity | Issue | Impact |
|---|----------|-------|--------|
| I1 | **High** | Evidencias are didactic paraphrases (sheet note A2), not MEP text | Must be labelled `secondary`; cannot satisfy the `official` grounding rule |
| I2 | **High** | Cited source *"marco sumativo MEP 2026"* and *"rúbrica MEP 2026"* are not in `references/original/` | Afirmación wording and page numbers cannot be verified yet |
| I3 | **High** | `Logrado ✓` is per-student progress; the file name contains a student's first name, which also appears in the committed `references/MANIFEST.sha256` (public repo) | Exclude from curriculum import; review manifest naming |
| I4 | Medium | `EE` rows are written-production rubric criteria, not selected-response afirmaciones | Separate assessment mode; not usable for multiple-choice generation |
| I5 | Medium | Prefix `ES` = Estudios Sociales, while `EL`/`EE` = Español | Ambiguous; do not reuse as subject codes |
| I6 | Medium | `Numeración` restarts per bloque; bloques have no ordinal | Natural key is (subject, bloque, numeración); bloque order must be derived |
| I7 | Low | Bloque weight embedded in name (`(40 %)`) | Split into name + weight |
| I8 | Low | `Ítems previstos` is text; numbers stored as floats | Parse to integer / null |
| I9 | Low | Source is free text (table + page) | Parse into document, table, page |
| I10 | Low | Activities use voseo (*Leé*, *Explicá*; 21 rows) | Fine as study content; items follow the standard's register |
| I11 | Info | Workbook year is 2026 (sumativa); existing standard and examples use `PNE2025` | Spec version `PNE2026` needed |

Positive signal: each selected-response subject totals exactly 60 *ítems
previstos*, consistent with a fixed-length summative test.

---

## 5. Proposed Minimal Normalized Model

### Entities

```text
source_document 1─n assertion
subject 1─n block 1─n assertion 1─n evidence
```

| Entity | Fields (required **bold**) | Notes |
|--------|---------------------------|-------|
| `source_document` | **id**, **title**, **kind** (`spec_table` \| `rubric` \| `workbook`), **year**, **file_name**, **sha256**, **provenance** | Workbook itself is a `secondary` document; MEP 2026 docs added when obtained |
| `subject` | **code** (`espanol`…), **name_es** | 4 fixed rows |
| `block` | **id**, **subject_code**, **ordinal**, **name_es**, **assessment_mode** (`selected_response` \| `rubric`), weight_pct | `name_es` without the `(40 %)` suffix |
| `assertion` | **id**, **block_id**, **ordinal**, **text_es**, **workbook_code**, **source_document_id**, source_table, source_page, planned_items, concepts_es, check_activity_es, **provenance**, **verification_status** | One row per `Código`; `concepts_es` / `check_activity_es` marked as workbook content |
| `evidence` | **id**, **assertion_id**, **ordinal**, **text_es**, **provenance** | All 344 rows `secondary` (paraphrase) |

### Column mapping

| Workbook | Target |
|----------|--------|
| `Código` | `assertion.workbook_code` (kept for traceability) |
| `Materia` | `subject.code` via fixed lookup |
| `Bloque MEP` | `block.name_es` + `block.weight_pct` |
| `Numeración` | `assertion.ordinal` (integer) |
| `Afirmación / criterio` | `assertion.text_es` (verbatim) |
| `Conceptos detallados` | `assertion.concepts_es` (verbatim) |
| `Actividad de comprobación` | `assertion.check_activity_es` (verbatim) |
| `Fuente / página` | `source_document_id`, `source_table`, `source_page` |
| `Ítems previstos` | `assertion.planned_items` (int) or `block.assessment_mode = rubric` |
| `Objetivo`, `N.º`, `Evidencia / criterio verificable` | `evidence.assertion_id`, `.ordinal`, `.text_es` |
| `Cantidad evidencias` | Not stored; import-time check only |
| `06` cols D, F, G, H | Not stored; import-time consistency check |
| `Logrado ✓` | **Not imported** (student data) |

### Identifiers

Stable IDs following `.ace/standards/question-engine.md`:
`PNE2026-PRI-MAT-SUM-B1-A3-E2`. Bloque ordinals follow first appearance in
the catalogue (assumption — to be confirmed against the MEP 2026 tables).
Rubric criteria need a new application code (proposed `PE`, *producción
escrita*), which requires an ADR update to the standard.

### Fit with existing contracts

The current `curriculum-record.schema.json` can hold these rows as
`bloque` / `afirmacion` / `evidencia` records with `provenance: secondary`, but
lacks `weight_pct`, `assessment_mode`, `workbook_code`, `concepts_es` and
`check_activity_es`. Minimal change: add those optional fields (schema 1.1).

---

## Decisions Needed Before Implementation

1. **Provenance policy.** Under the current standard, workbook-only records are
   `secondary` and cannot ground items, so generation would abstain for every
   objective. Options:
   - obtain the MEP 2026 marco sumativo and rúbrica, verify afirmaciones
     verbatim, then mark verified afirmaciones `official`; or
   - amend the standard (ADR) to allow a `workbook` label as a grounding basis,
     clearly shown as non-official to users.
2. **Written production (`EE`).** Import now as rubric data for future use, or
   defer.
3. **Student data.** Confirm `Logrado ✓` is excluded and approve renaming the
   source file reference in `references/MANIFEST.sha256` to remove the
   student's name.
4. **Spec versions.** Confirm `PNE2026` sumativa becomes the primary target
   (the existing examples use `PNE2025` diagnóstica).
