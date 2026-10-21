# ADR-008: Practice Configuration API, UI and Allocation Policy

> **Status:** Accepted (Product Owner task T003)
> **Date:** 2026-10-21
> **Amends:** [ADR-004](ADR-004-web-app-stack.md) (frontend choice)

---

## Context

Students must configure a practice session — subject, objectives, difficulty,
question count — over baseline `PNE2026-SUM-v1.0` before question generation
exists. The Product Owner asked for FastAPI and plain HTML/CSS/JavaScript, no
accounts and no frontend framework.

---

## Decision

### API (`app/main.py`)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/subjects` | Four subjects with multiple-choice objective counts |
| `GET /api/objectives?subject=` | Objectives of one subject, verbatim `text_es`, bloque, evidence count |
| `POST /api/practice/configure` | Validate a configuration and return the allocation |

- Reads the catalog read-only through `curriculum/catalog.py`.
- Only `multiple_choice` objectives are listed or accepted; `EE` rubric
  criteria are rejected.
- Errors return `{"error": code, "message_es": ...}` with HTTP 422; codes and
  field names are English, messages Costa Rican Spanish.
- Request contract: `scope` (`single_objective` \| `selected_objectives` \|
  `subject_simulation`), `objective_codes`, `difficulty`
  (`easy` \| `medium` \| `hard` \| `mixed`), `question_count` (5, 10, 20, 30).

### Allocation (`app/allocation.py`)

1. Objectives are sorted by workbook code (selection order does not matter).
2. `n ≥ k`: each objective gets `⌊n / k⌋`; the first `n mod k` get one more.
3. `n < k`: objectives at indices `⌊i·k / n⌋` (evenly spread) get one each;
   the rest are reported in `uncovered_codes`.
4. Within an objective, questions cycle through evidencias by ordinal.
5. `mixed` cycles easy → medium → hard over the whole set.

Subject simulation uses the same balanced rule. The planned-item-weighted
strategy (`proportional_planned_items`, coverage-plan schema 1.1) remains
available for a later decision.

### UI (`app/static/`)

Single page, no build step, served by FastAPI. UI labels: Fácil, Intermedia,
Difícil, Mixta; Un objetivo, Varios objetivos, Todos los objetivos. Curricular
text is inserted with `textContent` (never HTML). A notice states the content
is the approved Mentor Pro catalog, not official MEP material (ADR-006).

---

## Alternatives Considered

### Alternative 1: React + Vite (ADR-004 proposal)

- **Pros:** Component model for later screens.
- **Cons:** Build tooling for one form.
- **Why rejected:** Product Owner constraint for T003; revisit with more screens.

### Alternative 2: Random sampling of objectives

- **Pros:** Variety across sessions.
- **Cons:** Not reproducible; harder to test and audit.
- **Why rejected:** Determinism required.

---

## Consequences

### Positive

- Allocation is reproducible and testable without a database.
- Generation (later) receives slots already tied to evidencias.

### Negative

- With few questions, the same subset of objectives is chosen every time for
  the same selection.

### Neutral

- No authentication or student data in this step.

---

## Related

- [ADR-006](ADR-006-curriculum-baseline-v1.md), [ADR-007](ADR-007-postgresql-curriculum-catalog.md)
- Report: `docs/progress/task_T004_result.md`
