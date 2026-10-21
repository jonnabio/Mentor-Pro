---
name: llm-cost-observability
description: Records every LLM call with tokens, provider-reported USD cost, model and provider, latency and purpose (generation, validation, retries, fallbacks), computes cost per generated item, per accepted item and per practice set, tracks free-model use, paid fallback rate and daily and monthly spend, detects missing usage records and defines budget alerts and enforcement. Use for any LLM call or cost question.
---

# Skill: LLM Cost Observability

> If a call is not recorded, its cost is unknown — never zero.

---

## Purpose

Make spend and operational health measurable and enforce budgets in USD.

Generic logging and metrics practice: `.ace/standards/observability.md`.

---

## Activation

Use when adding an LLM call, building cost reports or dashboards, setting
budgets, or investigating unexpected spend.

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| Call metadata | Yes | From `openrouter-model-routing` for every attempt |
| Response `usage` | Yes when available | Tokens and cost |
| Generation ID | No | For later lookup when cost is missing |
| Review outcomes | No | Item verdicts for cost-per-accepted metrics |

---

## Outputs

- One LlmUsageRecord per call:
  `.ace/schemas/question-engine/llm-usage-record.schema.json`
  (examples: `.ace/schemas/question-engine/examples/llm-usage-records.json`).
- Aggregates (below) and alert events.

---

## Procedures

### 1. Record

```markdown
1. Create the record before the call (status pending in memory), finish it after.
2. cost_usd = provider-reported cost; cost_source = provider_reported.
3. If absent, query the generation stats endpoint by generation_id;
   cost_source = generation_endpoint.
4. If still absent: cost_usd = null, cost_source = missing. Never estimate as 0.
5. Store IDs only: request, practice set, items. No prompts, no student data.
```

### 2. Attribute

| `purpose` | Counts toward |
|-----------|---------------|
| `generation` (attempt 1) | Generation |
| `repair`, `generation` (attempt > 1) | Retries |
| any with `is_fallback: true` | Fallbacks |
| `independent_solve`, `review` | Validation |
| `evaluation`, `ingestion` | Separate budgets |

### 3. Aggregate

| Metric | Formula |
|--------|---------|
| Cost per generated item | Σ cost (generation + retries) / items generated |
| Cost per accepted item | Σ cost (all purposes for the set) / items accepted |
| Cost per practice set | Σ cost where `practice_set_id` = set |
| Free utilization | calls with `tier = free` / all calls |
| Paid fallback rate | paid calls with `is_fallback` / requests |
| Daily / monthly spend | Σ cost_usd by UTC day / month |
| Missing usage rate | sent calls with `cost_source = missing` / sent calls (excludes `budget_blocked`) |

Round only for display (4 decimals USD); store full precision.

### 4. Budgets and alerts

| Level | Trigger | Action |
|-------|---------|--------|
| Warn | 80 % of daily or monthly USD or request budget | Alert developer |
| Block | 100 % | Routing returns `budget_blocked` |
| Integrity | Missing usage rate > 5 % in a day | Alert; block paid escalation |
| Anomaly | A single call > 10× median cost for its purpose | Alert |

Budgets are configuration values; the free-only default is $0.

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `openrouter-model-routing` | Emits calls; reads spend to enforce budgets |
| `question-evaluation` | Uses aggregates in reports |
| `question-quality-review` | Supplies verdicts for cost per accepted item |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| Usage store unavailable | Routing fails closed (no calls) |
| Record fails schema | Keep raw event in an error log; alert |
| Duplicate `call_id` | Reject second write; alert |
| Currency other than USD reported | Do not convert silently; mark `missing` and alert |

---

## Examples

Set `ps-0001`: one free generation call ($0, provider reported) and one paid
fallback blocked before sending (`budget_blocked`, cost null) → cost per set
$0.0000, paid fallback rate 0. Blocked calls never reached the provider, so
they are excluded from the missing usage rate.

A completed call whose cost cannot be obtained (`status: ok`,
`cost_source: missing`) counts as missing and can trigger the integrity alert.

---

## Common Pitfalls

1. **Treating null cost as zero**: hides paid usage.
2. **Logging prompts for debugging** and forgetting retention.
3. **Estimating cost from a hardcoded price table**: prices change.

---

## Invocation

```markdown
"Apply the llm-cost-observability skill from
.ace/skills/llm-cost-observability/SKILL.md to add usage recording and a
daily budget check to the generation worker."
```
