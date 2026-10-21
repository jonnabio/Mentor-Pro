# Implementation Plan: Question Engine ACE Skills

> **Date:** 2026-10-21
> **Role:** Architect
> **Status:** Approved by product owner (2026-10-21)
> **Decision record:** [ADR-005](../adr/ADR-005-question-engine-skill-suite.md)

---

## Objective

Extend ACE with the specialized skills needed to build a curriculum-grounded
question generation engine for the sixth-grade *Pruebas Nacionales
Estandarizadas* (PNE). This plan covers skills only. It excludes database,
API and UI design.

---

## Inputs Inspected

| Input | Finding |
|-------|---------|
| `.ace/skills/` | 27 generic skills; none is domain-specific |
| `.aceconfig` `skill_triggers` | Discovery is keyword → `SKILL.md` path |
| Skill format | Frontmatter `name`, `description`; sections Purpose, Prerequisites, Procedures, Common Pitfalls, Invocation |
| `.ace/standards/documentation.md` | Skills in `.ace/skills/`, standards in `.ace/standards/`, domain context in `.ace/knowledge/` |
| Validation tooling | No skill validator; `verify.sh` `test_cmd` pointed at a missing `cli/` |
| `references/original/Marco-de-especificaciones-de-Primaria-2025.pdf` | Hierarchy: componente → bloque temático → afirmación → evidencias; per-component infinitivos verbales; aplicación diagnóstica and sumativa |

---

## Skill Gap Assessment

| # | Skill | Existing coverage | Missing capabilities | Action | Priority |
|---|-------|-------------------|----------------------|--------|----------|
| 1 | `mep-curriculum-grounding` | None | Hierarchy mapping, official vs secondary sources, traceability, invented-link detection, spec versions | Create | P0 |
| 2 | `mep-question-design` | `prompt-engineering` (generic) | Evidence-linked items, cognitive-demand difficulty, distractor rules, es-CR language, output contract | Create; reference `prompt-engineering` | P0 |
| 3 | `question-quality-review` | None (`code-review` is code only) | Alignment, key, ambiguity, distractor, duplicate checks; verdict rules | Create; owns the deterministic checker | P0 |
| 4 | `math-answer-verification` | `testing-strategy` (generic) | Exact arithmetic, fractions, units, es-CR number formats, unique key | Create; uses the shared checker | P0 |
| 5 | `evidence-coverage-planning` | None | Allocation across evidencias, repetition limits, insufficient coverage | Create | P1 |
| 6 | `question-evaluation` | `model-evaluation` (generic methodology) | Domain datasets, per-subject/model benchmarks, acceptance and regeneration rates | Create as specialization | P1 |
| 7 | `openrouter-model-routing` | `error-handling`, `standards/security.md` | Model discovery, free-first routing, paid escalation gate, budgets | Create | P1 |
| 8 | `llm-cost-observability` | `standards/observability.md` (generic) | USD cost records, unit economics, alerts, missing-usage detection | Create; reference standard | P1 |
| 9 | `curriculum-data-ingestion` | `data-pipeline-design` (generic) | PDF/DOCX/XLSX extraction, stable IDs, source vs AI interpretation, review | Create; reference `data-pipeline-design` | P2 |

No generic skill is modified.

---

## Skill Architecture

```text
curriculum-data-ingestion ──► curriculum records (.ace/schemas/question-engine)
            │
            ▼
mep-curriculum-grounding ──► grounding bundle (records + verbatim excerpts)
            │
            ▼
evidence-coverage-planning ──► coverage plan (slots)
            │
            ▼
mep-question-design ──► question items ──► openrouter-model-routing
            │                                      │
            ▼                                      ▼
question-quality-review ◄── math-answer-verification   llm-cost-observability
   (deterministic checker,                          ▲
    independent solve, rubric)                      │
            │                                       │
            ▼                                       │
question-evaluation ─────────────────────────────────┘
```

### Responsibility boundaries

| Concern | Sole owner |
|---------|-----------|
| Turning documents into records | `curriculum-data-ingestion` |
| Deciding whether a curricular link is supported | `mep-curriculum-grounding` |
| Choosing which evidencias a set covers | `evidence-coverage-planning` |
| Writing items | `mep-question-design` |
| Accept / revise / regenerate / reject | `question-quality-review` |
| Proving math answers | `math-answer-verification` |
| Choosing models and enforcing budgets | `openrouter-model-routing` |
| Recording usage and cost | `llm-cost-observability` |
| Benchmarking over time | `question-evaluation` |

Shared rules live once in `.ace/standards/question-engine.md`. Domain vocabulary
lives in `.ace/knowledge/mep-pne-curriculum.md`.

---

## Deliverables

1. Standard: `.ace/standards/question-engine.md`
2. Knowledge: `.ace/knowledge/mep-pne-curriculum.md`
3. Schemas and examples: `.ace/schemas/question-engine/`
4. Nine skills under `.ace/skills/<name>/SKILL.md`
5. Deterministic checker (all four subjects):
   `.ace/skills/question-quality-review/scripts/`
6. Skill validator: `.ace/scripts/validate_skills.py`
7. Tests: `tests/ace/`
8. `.aceconfig` triggers and verify gate
9. ADR-004 (stack, proposed) and ADR-005 (skill suite)
10. Validation report: `docs/progress/task_T001_result.md`

---

## Verification

```bash
.venv/Scripts/python.exe -m pytest -q tests/ace
.venv/Scripts/python.exe .ace/scripts/validate_skills.py
bash .ace/scripts/verify.sh
```

---

## Risks

| Risk | Mitigation |
|------|-----------|
| Non-math answers cannot be proven deterministically | Checker proves structure and grounding only; independent solve is mandatory |
| Sample items in the Marco are images; option count unverified | Option count configurable (3–5), default 4 marked as an assumption |
| OpenRouter catalogue and limits change | Skills require runtime discovery; nothing hardcoded |
| MEP PDFs not in Git | Checksum manifest in `references/MANIFEST.sha256` |
