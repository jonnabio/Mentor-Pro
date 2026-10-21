---
name: evidence-coverage-planning
description: Turns a practice request (subject, afirmaciones or evidencias, difficulty including mixed, question count, option count, focused or mixed mode) into a deterministic coverage plan that allocates questions across official evidencias, limits repetition, varies task formats and reports insufficient coverage. Use before any generation run.
---

# Skill: Evidence Coverage Planning

> Decides what each question in a set must assess, before any model call.

---

## Purpose

- Map every question slot to one evidencia.
- Allocate fairly across selected objectives; avoid repetition.
- Resolve `mixed` difficulty into concrete levels.
- Report targets that cannot be covered.

Shared rules: `.ace/standards/question-engine.md`.

---

## Activation

Use when a student or developer requests a practice set, or when tuning how
sets are composed.

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `request` | Yes | Fields of `request` in the coverage-plan schema |
| `grounding` | Yes | Bundle from `mep-curriculum-grounding` |
| `history` | No | Per-evidencia counts already served in this session (no student identity) |
| `task_formats` | No | Allowed formats per evidencia (default: one generic format) |

---

## Outputs

A CoveragePlan valid against
`.ace/schemas/question-engine/coverage-plan.schema.json`
(example: `.ace/schemas/question-engine/examples/coverage-plan.json`).

---

## Procedures

### 1. Expand targets

```markdown
1. Take evidencias from the grounding bundle (afirmaciones already expanded).
2. Rejected targets go to `insufficient` with the grounding reason.
3. If no evidencia remains → empty slots; generation must not start.
```

### 2. Allocate slots (deterministic)

```markdown
1. Order evidencias by record_id.
2. focused mode: round-robin over evidencias of the selected afirmación(es).
   mixed mode: round-robin over afirmaciones first, then their evidencias.
3. Prefer evidencias with the lowest `history` count (ties by record_id).
4. Repetition limit: no evidencia gets more than ceil(count / n_evidencias) + 1 slots.
5. Sumativa requests: weight afirmaciones by `item_count` when present.
```

### 3. Resolve difficulty

| Request | Per-slot levels |
|---------|-----------------|
| `easy` / `medium` / `hard` | Same level for all slots |
| `mixed` | Cycle easy → medium → hard, starting with easy |

### 4. Assign task formats

Rotate formats so consecutive slots on the same evidencia differ. A format is
allowed only if the evidencia's verb supports it (e.g. *Ubica en un mapa*
requires an image stimulus — abstain if none can be supplied).

### 5. Report coverage

`coverage` maps each evidencia to its slot count. Add to `insufficient` any
selected evidencia that received zero slots, with the reason.

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `mep-curriculum-grounding` | Supplies evidencias |
| `mep-question-design` | Consumes slots |
| `question-evaluation` | Measures coverage balance across runs |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| `question_count` > 30 | Reject request (schema maximum) |
| Fewer evidencias than slots | Repeat within the repetition limit; then shrink the set and report it |
| Required stimulus type unavailable | Move evidencia to `insufficient`, reason `stimulus_unavailable` |
| Empty grounding | Return plan with no slots; caller must abstain |

---

## Examples

Request: Matemáticas, afirmación B1-A3, `mixed`, 3 questions, 4 options →
three slots on evidencia E2 at easy / medium / hard, with three formats; E1
reported in `insufficient` because it was not in the bundle.

---

## Common Pitfalls

1. **Letting the model choose evidencias**: allocation is deterministic.
2. **Student identity in history**: use counts only.
3. **Same format repeated**: produces near-duplicates that review will reject.

---

## Invocation

```markdown
"Apply the evidence-coverage-planning skill from
.ace/skills/evidence-coverage-planning/SKILL.md to plan a 10-question mixed
Ciencias set for the selected afirmaciones."
```
