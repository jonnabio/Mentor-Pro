# ADR-009: OpenRouter Integration (Connectivity, Routing, Usage)

> **Status:** Accepted (Product Owner task T005)
> **Date:** 2026-10-21. Amended by T053 and T055 (2026-11-05).

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
| `OPENROUTER_PAID_MODEL` | empty | Paid model, used only under an approval (T055) |
| `OPENROUTER_ALLOW_PAID` | `false` | Enables paid approval requests; never switches by itself (T055) |
| `OPENROUTER_PAID_MAX_USD_PER_OPERATION` | `0` | Highest ceiling an adult may approve (T055) |
| `OPENROUTER_MANAGEMENT_KEY` | empty | Optional, read-only `GET /credits` (T055) |
| `OPENROUTER_MAX_USD_PER_DAY` | `0` | Paid spend cap (UTC day) |
| `OPENROUTER_MAX_REQUESTS_PER_DAY` | `50` | All sent calls |
| `OPENROUTER_TIMEOUT_S` | `60` | Per request |
| `OPENROUTER_MAX_RETRIES` | `2` | Per model, for 429 / 5xx / timeout / connection |
| `OPENROUTER_MAX_TOKENS` | `1024` | Per request |

### Behaviour

- Free = prompt and completion price both zero in `/models` (cached 1 h).
- Configured free models that are missing or not free are skipped; if none
  remain, routing does not silently pick arbitrary models.
- Paid calls need an adult's approval for one operation (amendment T055),
  daily paid spend below the cap, and no paid call today with unknown cost.
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
  262,144 context; listed with `response_format` and `reasoning`. Not yet
  tested live.

### Amendment T055 (2026-11-05): paid generation only with adult approval

Context: in T054, Gemma returned HTTP 429 on all 6 requests and Nemotron
truncated or timed out, so free generation alone is unreliable. Paying is
acceptable only with a parent's or administrator's explicit, bounded
consent.

- Routing never adds the paid model by itself, even with
  `OPENROUTER_ALLOW_PAID=true`. It is tried after the free models only
  when the caller passes a claimed `PaidGrant`. Without one, an exhausted
  route reports `paid_available`, and a seeding run reports
  `run.paid_option`. Student practice never passes a grant, so it stays
  free-only.
- Operator CLI `python -m app.llm.paid`: `estimate` stores a `pending`
  authorization in `llm.paid_authorization` (at most 3 pending, expiring
  after 24 h). `approve --max-usd X --approver parent|administrator` and
  `decline` follow. `seed_bank run --objective O --paid-authorization ID`
  runs it. There is no HTTP endpoint and no student-facing path.
- Estimate: current `/models` prices (input, output, per-request and
  reasoning tokens), observed token history (30 days, input × 1.25), the
  whole workflow (generation and revision, independent solve, review,
  bounded retries), and an expected and a maximum USD figure with the
  price timestamp. With no prices or no history it returns
  `estimate_unavailable`, and nothing can be approved.
- Approval is refused when the ceiling is above
  `OPENROUTER_PAID_MAX_USD_PER_OPERATION` or the daily USD budget, below
  the expected cost, or above a verified balance or key allowance.
- Execution claims the approval once (`approved` → `in_use`, one paid
  operation at a time), for the approved subject and objective only. It
  re-checks prices (any rise stops the run) and the balance. Every paid
  HTTP attempt first reserves its worst-case cost against the ceiling and
  the daily budget in one conditional `UPDATE`. A cost that is not
  reported is counted at its full reservation. The approval ends
  `consumed` or `stopped` and never carries over to another operation.
- Balance: `GET /key` (application key) gives the key's limit and
  remaining allowance, which is not the account balance. `GET /credits`
  is read only with the separate `OPENROUTER_MANAGEMENT_KEY`. Without it,
  or on any error, the status is `balance_unknown`, with the reason.
- Failure categories, which never come from message text: 402 with error
  code 402 is `insufficient_credits` (otherwise `payment_required`); 429
  is `rate_limited`; 401 `auth_invalid`; 403 `forbidden`; timeouts,
  connection errors and 5xx are `provider_failure`. A 402 on the paid
  model stops paid execution. Credits are never bought.
- Usage records gain nullable `subject`, `objective_code`,
  `reasoning_tokens`, `failure_category` and `authorization_id`. A
  401/402 response is now recorded as a sent `error`, not as
  `budget_blocked`.
- `python -m app.llm.costs report [--credits]`: shows today and this
  month, by model, subject, purpose, batch and failure. It gives actual
  USD, calls with unknown cost, calls never sent, budget left and
  credits. `reconcile` fills missing costs from `GET /generation` and
  lists mismatches; recorded costs are never overwritten.

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
