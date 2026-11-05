# ADR-009: OpenRouter Integration (Connectivity, Routing, Usage)

> **Status:** Accepted (Product Owner task T005)
> **Date:** 2026-10-21. Amended by T053 (2026-11-05).

---

## Context

Question generation (next phase) needs an LLM gateway. ADR-004 and the
`openrouter-model-routing` and `llm-cost-observability` skills define the
policy: free models first, paid only when explicitly allowed, budgets
enforced, and every call recorded in USD without student data.

---

## Decision

### Modules (`app/llm/`)

| Module | Responsibility |
|--------|----------------|
| `settings.py` | Settings from environment or `.env`; key excluded from `repr` |
| `client.py` | `GET /models`, `POST /chat/completions`, timeouts, retries, usage parsing |
| `router.py` | Candidate order, paid gate, request and USD budgets |
| `usage.py` | Usage records; PostgreSQL table `llm.usage_record` |
| `connectivity.py` | Developer-only CLI check |

### Configuration (`.env`, never committed)

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — (required) | Server-side only |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Must be https |
| `OPENROUTER_FREE_MODELS` | empty | Ordered free models; empty = top 3 discovered free models by context length |
| `OPENROUTER_PAID_MODEL` | empty | Optional fallback |
| `OPENROUTER_ALLOW_PAID` | `false` | Paid fallback switch |
| `OPENROUTER_MAX_USD_PER_DAY` | `0` | Paid spend cap (UTC day) |
| `OPENROUTER_MAX_REQUESTS_PER_DAY` | `50` | All sent calls |
| `OPENROUTER_TIMEOUT_S` | `60` | Per request |
| `OPENROUTER_MAX_RETRIES` | `2` | Per model, for 429 / 5xx / timeout / connection |
| `OPENROUTER_MAX_TOKENS` | `1024` | Per request |

### Behaviour

- Free = prompt and completion price both zero in `/models` (cached 1 h).
- Configured free models that are missing or not free are skipped; if none
  remain, routing does not silently pick arbitrary models.
- Paid fallback runs only if `ALLOW_PAID=true`, daily paid spend is below the
  cap, and no paid call today has unknown cost.
- 401/403 stop routing; 402 skips the model; 400/404 move to the next model
  without retry; 429/5xx/timeouts retry with exponential backoff (cap 30 s)
  honouring `Retry-After`.
- Requests set `usage: {include: true}`; cost is `usage.cost`, else
  `GET /generation?id=`, else `NULL` with `cost_source = missing`.
- `model_used` is the response `model` field.
- Usage rows hold IDs and metrics only — no prompts, responses or keys.

### Amendment T053 (2026-11-05): question generation fallback

Context: in the T052 pilot, every question-generation call (11 of 11)
timed out at 60 s on `nvidia/nemotron-3-ultra-550b-a55b:free`. The
configured fallback `minimax/minimax-m3.1-flash:free` had been delisted,
and the router drops unlisted models silently, so generation had one
model.

- `OPENROUTER_QUESTION_GENERATION_MODELS`: an explicit ordered list for
  question generation only (`app/generation/pipeline.py`). The first model
  is the primary; the next ones are fallbacks. Empty (default) keeps the
  earlier behavior (`OPENROUTER_FREE_MODELS`). Duplicates and models in
  `OPENROUTER_GENERATION_EXCLUDED_MODELS` are refused at load.
- Routing is the existing `route()` with `models=`. The fallback is
  called only when the primary's final attempt is not a usable response
  (timeout, HTTP 429 or 5xx after the bounded retries, connection error,
  402, other 4xx, empty or truncated output). Educational validation runs
  after routing, so a rejected question never switches models; a revision
  round routes from the primary again.
- Bound per generation request: models × (`OPENROUTER_MAX_RETRIES` + 1)
  calls, then `unavailable`. Every attempt reserves the shared daily
  budget before it is sent and is recorded (`model_requested`, `status`,
  `error_kind`, `latency_ms`, `is_fallback`). Timeout and retry settings
  are unchanged.
- A listed model that is not currently free is skipped, never
  substituted, and named in the failure reason ("not listed as free").
- Blind solve and review keep their own routing and still avoid the model
  that generated the item. Writing generation is unchanged.
- Fallback chosen for production (configuration, separately authorized):
  `google/gemma-4-26b-a4b-it:free` (Google, distinct from Nvidia;
  262,144 context; listed with `response_format` and `reasoning`). Not yet
  tested live.

---

## Alternatives Considered

### Alternative 1: OpenRouter server-side fallback (`models` array)

- **Pros:** One request.
- **Cons:** Per-attempt usage and the paid gate become opaque.
- **Why rejected:** Budget enforcement and auditing need per-model attempts.

### Alternative 2: OpenAI SDK pointed at OpenRouter

- **Pros:** Familiar API.
- **Cons:** Extra dependency; less control over usage fields and retries.
- **Why rejected:** httpx is already a dependency and sufficient.

---

## Consequences

### Positive

- Paid spend is impossible unless explicitly enabled and budgeted.
- Every attempt is auditable in USD.

### Negative

- Auto-selected free models may change as OpenRouter's catalogue changes.

### Neutral

- Usage-record schema gains purpose `connectivity_test` and `error_kind`.

---

## Related

- [ADR-004](ADR-004-web-app-stack.md), [ADR-008](ADR-008-practice-configuration-api.md)
- Report: `docs/progress/task_T005_result.md`
