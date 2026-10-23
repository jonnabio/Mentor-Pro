# ADR-012: Controlled Parallel Question Generation

> **Status:** Accepted (Product Owner task T008)
> **Date:** 2026-10-23

---

## Context

T007 generated practice-set slots sequentially (about 4–5 minutes per
question on free models). T008 requires bounded concurrency without changing
curriculum, schemas, validation rules or the student interface, with budgets
enforced atomically, set-wide duplicate detection, isolated slot histories
and deterministic ordering.

Two weaknesses of the sequential design surfaced while planning:

- The router checked the request budget once per model, then the client
  could retry up to `OPENROUTER_MAX_RETRIES` times, so a limit could be
  exceeded by up to two calls even sequentially; concurrent workers could
  also pass the same check together.
- Each slot's duplicate bank is a snapshot taken when its request starts, so
  two slots generating at once cannot see each other's items.

---

## Decision

### Concurrency model

A `ThreadPoolExecutor` with `QUESTION_GENERATION_CONCURRENCY` workers
(default 2, allowed 1–8) runs slots. Threads, not `asyncio`: the OpenRouter
client (`httpx.Client`) and PostgreSQL access (`psycopg`) are synchronous,
and the work is I/O bound, so a bounded pool gives the same overlap without
rewriting the client. The catalog connection is not shared with workers:
every slot is grounded before the pool starts.

### Atomic budgets (`app/llm/budget.py`)

`BudgetGate.acquire(tier)` runs under one lock before **every HTTP attempt**
(the client calls a `before_attempt` hook, including on retries). It refuses
when persisted usage plus reservations in flight reaches the daily request
budget, when the per-set call cap is reached, or — for paid calls — when the
daily USD budget is spent or another paid call is in flight (its cost is not
yet known). Reservations are settled after the usage records are stored. A
refused attempt is recorded as `budget_blocked`. All workers of a set share
one gate; the single-question endpoint uses a private one.

### Set-wide duplicate detection

Workers still pass the committed items as D01 bank. In addition, an accepted
item is committed only after `duplicate_reason` (D01) against all committed
items under a lock; a duplicate becomes a rejected attempt
(`stage: set_commit`) and the slot retries within its limits.

### Isolation and ordering

Each slot keeps its own requests, attempt history, usage records (by request
ID) and retries. Results and outcomes are ordered by slot position, not by
completion; persisted attempt rows carry `slot`.

### Retries

Unchanged and bounded: client retries 429/5xx/timeouts with exponential
backoff and `Retry-After`; truncated or invalid responses fail the attempt;
the slot retries up to `max_requests_per_slot`.

---

## Consequences

### Positive

- Budgets are exact under concurrency (and sequentially, which was not true
  before).
- Wall-clock time drops roughly with concurrency while validation is
  unchanged.

### Negative

- Concurrency raises the request rate against free models (more 429s).
- A duplicate found at commit wastes the calls that produced it.

### Neutral

- Calls per accepted question are unchanged in expectation.

---

## Related

- [ADR-009](ADR-009-openrouter-integration.md),
  [ADR-011](ADR-011-validated-practice-sets.md)
- Report: `docs/progress/task_T008_result.md`
