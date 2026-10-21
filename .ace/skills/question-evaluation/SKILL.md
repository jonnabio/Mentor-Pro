---
name: question-evaluation
description: Benchmarks PNE question generation over fixed evaluation datasets by subject, difficulty, evidencia and model, measuring correctness, curricular alignment, distractor quality, validation acceptance, regeneration rate, latency and cost, and compares free versus paid models in reproducible reports. Use before changing prompts or models and on a regular schedule.
---

# Skill: Question Evaluation

> Domain specialization of generic model evaluation.
> Methodology base: `.ace/skills/model-evaluation/SKILL.md`.

---

## Purpose

Decide with evidence whether a model, prompt or routing change improves the
engine, and catch regressions.

---

## Activation

Use when:

- adding, removing or re-ordering models in routing;
- changing a generation, solve or rubric prompt version;
- changing checker rules or thresholds;
- on the scheduled benchmark (recommended weekly while developing).

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `dataset` | Yes | Versioned list of coverage-plan requests (see Procedures 1) |
| `candidates` | Yes | Model + prompt-version pairs to compare |
| `records` | Yes | Curriculum records version (spec + checksum) |
| `budget_usd` | Yes | Maximum spend for the run (0 for free-only) |
| `seed` | Yes | Seed for sampling and ordering |

---

## Outputs

`docs/progress/evaluations/EVAL-<yyyymmdd>-<nn>.md` containing the metrics table,
configuration and a machine-readable JSON block:

```json
{
  "eval_id": "EVAL-20261021-01",
  "dataset_version": "evalset-1.0",
  "records_checksum": "804dbb9f…",
  "candidates": [
    { "model": "example/free-model:free", "prompt_version": "1.0.0",
      "acceptance_rate": 0.62, "key_error_rate": 0.04, "alignment_mean": 1.7,
      "distractor_mean": 1.4, "regeneration_rate": 0.31,
      "latency_p50_ms": 38000, "cost_per_accepted_usd": 0.0 }
  ]
}
```

---

## Procedures

### 1. Build the dataset

```markdown
1. Stratify by subject × application × difficulty; at least 5 evidencias per subject.
2. Include hard cases: Español passages, math with fractions and money,
   evidencias needing a stimulus, evidencias that should abstain.
3. Store under tests/ or docs/ with a version; never change a released version.
```

### 2. Run

```markdown
1. Generate via openrouter-model-routing with routing fixed to the candidate.
2. Validate with question-quality-review (deterministic + independent solve + rubric).
3. Record every call with llm-cost-observability.
```

### 3. Metrics

| Metric | Definition |
|--------|-----------|
| Acceptance rate | accepted / generated |
| Key error rate | items whose key failed M03 or solve disagreement / generated |
| Alignment, distractor, language means | Rubric means (0–2) |
| Regeneration rate | slots needing ≥ 1 regenerate / slots |
| Abstention correctness | Expected abstentions that abstained |
| Latency p50 / p95 | Per generation call |
| Cost per accepted item | Total USD / accepted items |

Report each metric by subject and difficulty.

### 4. Human spot check

Sample 10 % of accepted items (minimum 10) for a teacher-style review; record
disagreements as a separate metric. LLM rubric scores are not ground truth.

### 5. Decide

A candidate replaces the current default only if key error rate does not
increase and acceptance rate or cost per accepted item improves.

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `model-evaluation` | Generic methodology |
| `question-quality-review` | Produces verdicts and rubric scores |
| `openrouter-model-routing` | Executes calls with fixed routing |
| `llm-cost-observability` | Supplies tokens, cost and latency |
| `evidence-coverage-planning` | Expands dataset requests into slots |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| Budget reached mid-run | Stop; report partial results labelled `incomplete` |
| Rate limits | Back off per routing policy; record the delay separately from latency |
| Missing usage records | Mark cost metrics `unknown`; never assume zero |
| Dataset or records changed | New eval ID; results not comparable to older runs |

---

## Examples

Comparing two free models on 40 Matemáticas slots: model A accepts 62 % with
4 % key errors, model B 70 % with 9 % key errors → keep A (correctness first).

---

## Common Pitfalls

1. **Judging by acceptance alone**: key errors outrank volume.
2. **Same model generating and judging**: inflates scores.
3. **Unpinned datasets**: results are not reproducible.

---

## Invocation

```markdown
"Apply the question-evaluation skill from .ace/skills/question-evaluation/SKILL.md
to benchmark the current free models on evalset-1.0 with a $0 budget."
```
