# Task T001 Result: Question Engine ACE Skills

> **Date:** 2026-10-21
> **Status:** Verified
> **Plan:** `docs/planning/2026-10-21-question-engine-skills-plan.md`
> **Decision:** [ADR-005](../adr/ADR-005-question-engine-skill-suite.md)

---

## Summary

Nine question-engine skills were created (none existed; no generic skill was
modified). They share one standard, one knowledge file and five JSON Schemas.
One deterministic checker covers all four subjects. A new validator checks
skill structure and references, and the ACE verify gate now runs real tests.

---

## Skill Gap Assessment (Outcome)

| Skill | Action | Priority | Reuses |
|-------|--------|----------|--------|
| `mep-curriculum-grounding` | Created | P0 | — |
| `mep-question-design` | Created | P0 | `prompt-engineering` |
| `question-quality-review` | Created (owns checker) | P0 | — |
| `math-answer-verification` | Created (uses shared checker) | P0 | — |
| `evidence-coverage-planning` | Created | P1 | — |
| `question-evaluation` | Created | P1 | `model-evaluation` |
| `openrouter-model-routing` | Created | P1 | `error-handling`, `security-audit` |
| `llm-cost-observability` | Created | P1 | `.ace/standards/observability.md` |
| `curriculum-data-ingestion` | Created | P2 | `data-pipeline-design` |

Architecture and responsibility boundaries: see the plan.

---

## Validation Report

| Check | Command | Result |
|-------|---------|--------|
| Unit and contract tests | `.venv/Scripts/python.exe -m pytest -q tests/ace` | 95 passed |
| Skill structure, metadata, references, discovery | `.venv/Scripts/python.exe .ace/scripts/validate_skills.py` | pass, 36 skills, 0 problems |
| Markdown lint (question-engine docs) | `lint_cmd` in `.aceconfig` | 15 files, 0 issues |
| Full ACE gate | `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |
| Example data vs schemas | `tests/ace/test_schemas.py` | All 5 schemas have valid examples |
| Checker on examples (CLI) | `item_checker.py items-valid.json --records curriculum-records.json` | 3/3 pass; only math `math_proven` |
| Mutation check | Disabled M03 and G02 logic temporarily | 2 tests failed as expected; code restored |
| Secret scan | grep for OpenRouter keys and `PGPASSWORD=` values | None found |
| Source grounding | Example records compared with Marco 2025 PDF pages 29, 35–37 | Verbatim; SHA-256 matches manifest |

### Representative scenarios covered by tests

- Wrong math key, equal-valued options, ambiguous `1.000`, missing expression.
- Banned options, duplicate options, missing rationale, wrong option count.
- Stem referring to a missing image; image stimulus without assets.
- Paraphrased excerpt, unknown evidencia, secondary source, wrong application.
- Español without passage; key support span not verbatim.
- Ungrounded fact terms; reviewed facts grounding a term.
- Exact and near duplicates in bank and within one batch.
- Validator detects name mismatch, missing section, unknown dependency,
  broken path and missing trigger.

### Consistency review

Two contradictions were found and fixed during review:

1. Standard required an independent solve for every item; now explicitly
   exempts Matemáticas keys proven by exact arithmetic.
2. Checker set `reject` on every failure; it now sets `reject` for grounding
   failures (G01/G02) and `regenerate` otherwise, matching the review skill.

---

## Limitations Requiring Manual Intervention

| Limitation | Owner action |
|------------|--------------|
| Non-math correctness is not provable deterministically | Independent solve and human spot checks (documented in skills) |
| Option count default (4) is an assumption; Marco sample items are images | Confirm against official released items |
| OpenRouter behaviour (endpoints, usage fields, limits) not exercised live | Verify during first integration; skills require runtime discovery |
| Example records have `review.status: pending` | Human review during ingestion |
| Framework markdown has about 700 lint issues | `docs/TODO-markdown-lint.md` |
| Skills are prose; ACE has no runtime skill loader to execute them | Discovery verified via `.aceconfig` triggers and validator |
| Gate commands use `.venv/Scripts/python.exe` (Windows layout) | Adjust for Linux CI |

---

## Files

### Created

- `.ace/standards/question-engine.md`
- `.ace/knowledge/mep-pne-curriculum.md`
- `.ace/schemas/question-engine/` (5 schemas, 6 example files)
- `.ace/skills/<9 skills>/SKILL.md`
- `.ace/skills/question-quality-review/scripts/item_checker.py`, `cr_math.py`
- `.ace/scripts/validate_skills.py`
- `tests/ace/` (conftest and 4 test modules)
- `docs/adr/ADR-004-web-app-stack.md` (Proposed),
  `docs/adr/ADR-005-question-engine-skill-suite.md`
- `docs/planning/2026-10-21-question-engine-skills-plan.md`
- `docs/progress/tasks.json`, this file
- `.markdownlint-cli2.jsonc`, `package.json`, `requirements-dev.txt`

### Modified

- `.aceconfig` (standard in entry, 24 triggers, verify commands)
- `docs/context/ACTIVE_CONTEXT.md`
- `docs/TODO-markdown-lint.md` (reopened with baseline debt)

---

## Recommended Next Steps

1. Run `python scripts/dev/setup_secrets.py` privately.
2. Accept or amend ADR-004.
3. Ingest all Marco 2025 tables with `curriculum-data-ingestion`; review.
4. Build `evalset-1.0` and qualify free models with `question-evaluation`.
