# ADR-020: Writing Exercise Generation

> **Status:** Accepted (Product Owner task T021)
> **Date:** 2026-10-24

---

## Context

ADR-019 defined the Producción escrita contracts and the `writing` schema.
T021 generates one exercise with the existing OpenRouter stack (ADR-009,
ADR-010): free models only, budgets, usage records.

---

## Decision

### Inputs and grounding

`generate_exercise(level, difficulty, criteria)`: level `L1`–`L5` (or its
code), `easy | medium | hard`, EE codes. The request is rejected before any
call if the criteria do not fit the level (core and allowed criteria,
ADR-019). Grounding comes from two sources and must agree:

- the baseline catalog (`list_rubric_criteria`, read-only): assertion ID,
  statement, content notes and suggested activity;
- the rubric file: statement and the five official descriptors.

### What the model writes, and what code writes

The model returns only student-facing text: `topic_es`,
`communicative_situation_es`, `suggested_ideas_es`, `instructions_es`,
`deliverable_description_es` (plus `source_text_es` for L1 editing and
`scaffolding_es` for L4). Code sets the ID, level, type, difficulty,
deliverable limits (from the level), target criteria, evaluation
parameters (rubric references, never descriptor text) and provenance.
Invented criteria or altered descriptors therefore cannot enter the
record; validation also rejects student text that cites EE codes, points
or rubric descriptors.

The prompt follows the MEP model test (topic, communicative situation,
"puede considerar las siguientes ideas", numbered instructions) and gives
the 4-point descriptor of each target criterion as the quality goal.
Model topics from the MEP model test and the preparation guide are
excluded, so every exercise has an original topic.

### Validation (prompt version `writing-1.0`, checks `W01`–`W08`)

| Check | Rule |
|-------|------|
| W01 | Model output has every required field with the right type |
| W02 | The assembled record passes `validate_exercise` (schema and level contract) |
| W03 | Student text has no EE codes, points, rubric wording or rubric descriptors |
| W04 | Deliverable fits the level: unit and range named in the instructions; for EE04 an introduction paragraph with a main idea and at least two complementary ideas; for EE05/EE06 the matching paragraphs |
| W05 | Age-appropriate length: 3–7 instructions of at most 220 characters, sentences of at most 30 words, situation 60–700 characters, topic at most 90 characters |
| W06 | Original topic: not a topic of the source models |
| W07 | Language: Spanish with accents; no English instructions |
| W08 | Independent review by another free model (clarity, age suitability, completeness, alignment, Costa Rican Spanish), each 0–2; all must be 2 |

Up to 3 generation requests per exercise, each through `route()` (its
retries and model fallback, one shared `BudgetGate`). Paid fallback stays
governed by `OPENROUTER_ALLOW_PAID` (off).

### Storage

`writing.generation_attempt` keeps one row per generation request:
request ID, level, difficulty, criteria, status, verdict, models, calls,
tokens, provider-reported cost (and whether it is complete), prompt version,
check results, review scores and reasons. An accepted exercise is stored in
`writing.exercise` with `generation_request_id`. Usage records go to
`llm.usage_record` as for questions.

---

## Amendment (T025)

Composed paragraphs add checks W13 (voseo), W14 (repeated instructions),
W16 (ideas outside the paragraph type), W17 (no model text: ideas of at most
15 words, situation of at most 3 sentences) and W18 (topic word overlap ≥ 0.6
or topic-and-situation overlap ≥ 0.4 with a stored exercise). The review adds
`paragraph_scope` and `no_model_text`. Introduction and conclusion exercises
are exactly one paragraph. Prompt versions `writing-1.1` and `writing-1.2`
(sentences of at most 25 words).

---

## Consequences

- Exercises enter the store only after deterministic checks and an
  agreeing review; a human still evaluates student writing (ADR-019).
- Keyword checks for W04 are heuristic; the review is the second line.

---

## Related

- [ADR-009](ADR-009-openrouter-integration.md),
  [ADR-010](ADR-010-single-question-generation.md),
  [ADR-019](ADR-019-produccion-escrita-foundation.md)
- `docs/progress/task_T021_result.md`
