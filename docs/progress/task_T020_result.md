# Task T020 Result: Producción Escrita Foundation

> **Date:** 2026-10-24
> **Status:** Done (data model only; no generation, no writing screen)
> **Decision:** [ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)
> **Mapping:** [2026-10-24-produccion-escrita-mapping.md](../planning/2026-10-24-produccion-escrita-mapping.md)

---

## Deliverables

| Deliverable | Location |
|-------------|----------|
| Rubric (verbatim, 20 criteria × 5 descriptors, weights, counting note, pages, SHA-256) | `curriculum/writing/MEP-RUBRICA-PE-2026.json` |
| Five levels and criterion mapping | `curriculum/writing/exercise-levels.json`; mapping document |
| Contracts (JSON Schema): rubric, levels, exercise, human evaluation | `.ace/schemas/writing/*.schema.json` |
| Examples: L2 introduction paragraph (typed), L5 full composition (handwritten), one evaluation each | `.ace/schemas/writing/examples/` |
| Cross-record rules | `app/writing/contracts.py` |
| Progress (separate from mastery) | `app/writing/progress.py` |
| PostgreSQL schema `writing` and store (not wired into the app) | `app/writing/store.py` |
| Tests | `tests/app/test_writing.py` (22) |

---

## Findings

- The baseline already holds EE01–EE20 as `written_rubric` assertions
  (`PNE2026-PRI-ESP-PE-B1-A1` … `B5-A20`), with statements but no 0–4
  descriptors; the source document is marked `cited_not_held`. The local
  rubric PDF matches the manifest checksum.
- 19 statements match the PDF exactly; EE05 differs ("…desarrollo y cada
  uno…" in the PDF, "…desarrollo, cada uno…" in the baseline). Both are
  kept; the curriculum was not modified.
- The source has two typos ("rrr" in EE13 at 4 points; "al inicio y final"
  in EE17 at 1 point), kept verbatim with a transcription note.

---

## Acceptance

| Criterion | Evidence |
|-----------|----------|
| All 20 EE criteria mapped | Every criterion is core in at least one level; union of allowed criteria = EE01–EE20 (test) |
| Evaluation parameters traceable | Each parameter's `rubric_ref` resolves to a criterion; descriptors carry PDF pages; rubric checksum checked against the manifest and the local PDF |
| Five levels defined | Codes, types, deliverables, core and allowed criteria (test) |
| Handwritten criteria | EE19/EE20 must be `not_evaluable` on typed work in exercise and evaluation (tests) |
| 78 objectives unchanged | Subjects API 8/22/19/29; existing baseline tests pass; no curriculum or practice code changed |
| Examples validate | Schema and cross-record checks pass; 11 negative cases are rejected |
| Storage | Round trip in `mentor_pro_test` (schema `writing`); CHECK constraints reject inconsistent rows |
| Existing tests and gate | Suite 408 passed; browser 259/259; `VERIFY_RESULT=pass gate=all` |

---

## Observations

- Suite duration rose from about 42 s to about 160 s during this session,
  for existing tests too (`test_practice_api.py` takes 52 s with or without
  the T020 changes). The test database is small; one PostgreSQL connection
  takes about 110 ms. Cause not investigated in T020.
- The writing store is not created at app start; nothing student-facing
  changed.
