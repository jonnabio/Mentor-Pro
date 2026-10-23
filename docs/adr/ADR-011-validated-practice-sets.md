# ADR-011: Validated Practice Set Generation

> **Status:** Accepted (Product Owner task T007)
> **Date:** 2026-10-23

---

## Context

T007 requires a practice set (at most 5 questions for now) from an existing
practice configuration, using the ADR-008 allocation and the ADR-010
single-question engine. Every question must pass the existing validation plus
a linguistic clarity check; duplicates inside the set are rejected; retries
are bounded; nothing bypasses validation to reach the count; attempts, usage
and cost are persisted per set; budget exhaustion yields a partial result.

---

## Decision

### Orchestration (`app/generation/practice_set.py`)

1. Selection and allocation reuse `select_objectives` and `allocate`
   unchanged; each allocation slot names an objective, evidencia and
   difficulty.
2. Slots are generated in order with `generate_one`. Each slot gets up to
   `max_requests_per_slot` requests (each request already allows two
   generation attempts). A slot without an accepted item is `failed`; the set
   is never padded with other objectives.
3. The duplicate bank for D01 is the set's accepted items plus recent accepted
   items for the same evidencia, so in-set near duplicates are rejected.
4. Limits (`SetLimits`, environment overridable): `max_questions` 5,
   `max_requests_per_slot` 3, `max_calls_per_set` 80. The daily request and
   USD budgets of ADR-009 still apply; a `budget_blocked` call stops the set.
   Model errors and truncated replies count as a failed request of the slot
   and are retried within `max_requests_per_slot`.
5. Set status: `complete` (all slots accepted), `partial` with
   `stop_reason` (`set_call_limit`, `daily_budget`, `slot_retries_exhausted`,
   or `llm_unavailable` when every request of a failed slot was unavailable).

### Linguistic clarity (checker 1.5.0, prompts generation 1.3.0, rubric 1.1.0)

Deterministic checks for every subject:

- **L01** the stimulus must not end with `:` (announces content that is not
  shown); in Matemáticas a stimulus announcing data ("los siguientes", "a
  continuación", "estos datos") must contain a number. The stem is not
  searched: "¿Cuál de los siguientes…?" refers to the displayed options.
- **L02** in Matemáticas, if the text names a unit (metros, kilogramos,
  litros, colones…) the options must carry a unit.
- **L03** the stem uses paired Spanish question marks (`¿…?`).
- **M04** (tightened): when the stem selects an option by a property
  ("¿Cuál de los siguientes…?", "podría"), an expression that evaluates to
  the key is not a proof; the blind solve decides.

The rubric `clarity` criterion now scores 0 for incomplete wording,
references to information not shown, missing units or inconsistency between
stimulus, stem and options.

### Persistence (schema `generation`)

- `practice_set`: configuration, allocation, status, stop reason, counts
  (accepted, rejected attempts), calls, tokens, cost, cost completeness and
  duration.
- `practice_set_item`: approved item per slot with objective, evidencia,
  request ID and item JSON.
- `question_attempt` gains `practice_set_id` and `slot`; its `validation`
  keeps every attempt's reasons. `llm.usage_record.practice_set_id` is filled.

### API

`POST /api/dev/practice-sets/generate` (dev endpoints only) takes the
practice configuration with `question_count` 5. No student interface change.

---

## Consequences

### Positive

- Sets inherit every single-question guarantee; totals are auditable from
  PostgreSQL per set.

### Negative

- Sequential generation: a 5-question set takes minutes on free models.
- L01–L03 are heuristics; the rubric remains the second line of defence.

### Neutral

- 10–30 question sets need the same code with higher limits (later task).

---

## Related

- [ADR-008](ADR-008-practice-configuration-api.md),
  [ADR-009](ADR-009-openrouter-integration.md),
  [ADR-010](ADR-010-single-question-generation.md)
- Report: `docs/progress/task_T007_result.md`
