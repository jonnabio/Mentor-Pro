---
name: openrouter-model-routing
description: Designs and validates the OpenRouter LLM gateway integration - runtime model discovery, free versus paid identification, qualified free-first routing, bounded retry and repair, fallback, paid escalation only when permitted, structured output, rate-limit handling, request and token budgets, and recording the model actually used. Use for any code or config that calls an LLM.
---

# Skill: OpenRouter Model Routing

> Provider integration only. Domain logic never calls OpenRouter directly.

---

## Purpose

Get a valid response at the lowest acceptable cost, or stop cleanly.

Shared rules: `.ace/standards/question-engine.md` (sections 7–8).
Retry patterns: `.ace/skills/error-handling/SKILL.md`.

---

## Activation

Use when writing or changing code, configuration or prompts that send requests
to an LLM, or when a model becomes unavailable or too slow.

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `purpose` | Yes | `generation`, `repair`, `independent_solve`, `review`, `evaluation`, `ingestion` |
| `messages` | Yes | Curriculum-only prompt (no student data) |
| `response_schema` | No | JSON Schema for structured output |
| `policy` | Yes | Routing policy (below), loaded from configuration |
| `validate` | Yes | Function returning valid / invalid for the parsed output |

Environment: `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL`
(from `.env`, never in code).

---

## Outputs

```json
{
  "status": "ok",
  "content": { "items": [] },
  "model_requested": "example/free-model:free",
  "model_used": "example/free-model:free",
  "provider": "example-provider",
  "tier": "free",
  "attempts": 2,
  "usage_record_ids": ["call-0001", "call-0002"]
}
```

`status`: `ok`, `exhausted` (all candidates failed), `budget_blocked`.

---

## Procedures

### 1. Policy (configuration, not code)

```yaml
routing:
  free_candidates: [model-id-a:free, model-id-b:free]   # ordered, qualified by question-evaluation
  paid_candidates: [model-id-c]                         # empty = paid disabled
  allow_paid: false
  max_attempts_per_model: 2          # includes one repair
  request_timeout_s: 300
  retry_statuses: [429, 500, 502, 503, 504]
  max_tokens: 16384
  require_structured_output: true
  data_collection: deny              # provider preference; may exclude some free models
budgets:
  max_requests_per_day: 50
  max_tokens_per_request: 20000
  max_usd_per_day: 0.00
  max_usd_per_month: 0.00
```

### 2. Discover models at runtime

```markdown
1. GET {OPENROUTER_BASE_URL}/models; cache ≤ 24 h.
2. Free = prompt and completion pricing both "0" (ids usually end in ":free").
3. Drop candidates that are missing, lack required parameters
   (response_format / structured outputs) or have too small a context_length.
4. Never hardcode prices, limits or availability; read them here.
```

### 3. Route

```text
for model in free_candidates (+ paid_candidates if allow_paid):
    check budgets → if exceeded: return budget_blocked
    attempt = call(model)            # retry 429/5xx with exponential backoff + jitter, honour Retry-After
    if output parses and validate(output): return ok
    attempt = repair(model, errors)  # once, sends validator messages only
    if valid: return ok
return exhausted
```

- Escalate to paid only when `allow_paid: true` and all free candidates failed.
- Record every attempt (success or failure) through `llm-cost-observability`.
- `model_used` comes from the response `model` field, never from the request.

### 4. Request details

| Concern | Rule |
|---------|------|
| Structured output | `response_format` with JSON Schema when supported; always re-validate locally |
| Usage | Request usage accounting so the response includes tokens and cost |
| Headers | `Authorization: Bearer $OPENROUTER_API_KEY`; optional `HTTP-Referer`, `X-Title` |
| Logs | Status, model, IDs, latency; never the key or full prompts |

### 5. Error mapping

| HTTP / condition | Handling |
|------------------|----------|
| 401 / 403 | Stop; configuration error |
| 402 | Paid credit exhausted; treat as `budget_blocked` |
| 429 | Back off; after retries move to next candidate |
| 5xx, timeout | Retry within limit; then next candidate |
| Invalid JSON / schema | One repair; then next candidate |

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `llm-cost-observability` | Records every call; supplies spend for budget checks |
| `question-evaluation` | Qualifies and orders candidates |
| `error-handling` | Generic retry and degradation patterns |
| `security-audit` | Key handling review |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| No qualified free model available | `exhausted` (or paid if permitted); surface a clear message |
| Budget unknown (usage store down) | Fail closed: block the call |
| Response model differs from requested | Accept, but record `model_used`; flag if it is paid while `allow_paid` is false |
| Prompt contains student data | Refuse to send; this is a bug |

---

## Examples

Free model A returns 429 twice → free model B returns valid JSON → `ok`,
`attempts: 3`, three usage records, `is_fallback: true` on the B record.

Paid disabled and both free models fail validation → `exhausted`; no paid call.

---

## Common Pitfalls

1. **Hardcoded model lists in code**: keep them in configuration.
2. **Trusting `response_format`**: always validate locally.
3. **Unbounded retries**: count retries against budgets.
4. **Assuming free means private**: free providers may log prompts; set
   `data_collection: deny` when content requires it.

---

## Invocation

```markdown
"Apply the openrouter-model-routing skill from
.ace/skills/openrouter-model-routing/SKILL.md to implement the generation
call with free-first routing and a $0 daily budget."
```
