# ADR-036: Question Bank Phase B (Reliability, Sizes, Inventory, Replenishment)

> **Status:** Accepted (PO authorization PO-QUESTION-BANK-PHASE-B-2026-11-09,
> fast track). Amends [ADR-009](ADR-009-openrouter-integration.md),
> [ADR-034](ADR-034-question-bank-foundation.md) and
> [ADR-035](ADR-035-bank-only-configurable-practice.md).
> **Date:** 2026-11-09

---

## Context

Production evidence, 2026-11-05 to 2026-11-09 (`llm.usage_record`):

- The fallback free model answered HTTP 429 to all 31 generation calls and
  never succeeded. Every request, slot and seeding cell still called it, with
  retries.
- The primary free model returned 18 truncated outputs and 11 timeouts.
- 3 practices ended `partial` and 2 `failed` because of exhausted slot retries.

Inventory is small: the Matemáticas batch has 9 of 100 cells filled, and no
other subject has a batch. The PO asked for four things:

- reliable free generation (T064);
- quiz sizes 5–30 offered only when the bank can serve them (T063);
- a larger approved inventory for all four subjects (T062);
- replenishment driven by inventory and performance (T061).

## Decision

### T064: free-generation reliability

1. **Back-off.** The existing back-off is kept: bounded exponential with
   jitter (2^(n-1) s plus up to 0.5 s, capped at 30 s) and `Retry-After`
   honoured. A `Retry-After` longer than 30 s is no longer slept through. The
   attempt records it and the model is cooled down instead.
2. **Model cooldown** (`app/llm/cooldown.py`):
   - A free model that is still rate limited after its retries is skipped by
     the router for `OPENROUTER_RATE_LIMIT_COOLDOWN_S` (default 300 s, at
     most 3600 s), or for longer when `Retry-After` asks for it.
   - The registry is process-wide and sends nothing.
   - If every candidate model is cooling, the route returns `rate_limited`
     with no request sent.
   - The paid model is never added by this path (T055 unchanged).
3. **Truncation recovery.** A truncated generation output (`finish_reason`
   length, or output at the limit) is retried once on the same model with
   twice the output limit, capped at 16,000 tokens and counted through the
   same budget gate. Fallback to the next model follows as before. Truncated
   content is never parsed or returned.
4. **Set stop.**
   - A practice set (and a seeding run) stops with
     `provider_rate_limited` when every model is cooling, instead of spending
     slot retries.
   - Whole-session (T059) practices end `failed` with a Spanish message,
     never partial.
5. **Unchanged:**
   - Validation: schema, D01, blind solve and rubric.
   - The daily request budget and the per-set call cap.
   - Idempotent session creation and the seeding advisory lock.
   - No paid call without an adult approval.

### T063: sizes offered only when they start

- `POST /api/practice/availability` (read-only) takes the student's current
  choice (subject, scope, objectives, difficulty). It returns:
  - `bank_counts`: the configured sizes that the real composer fills now,
    checked in ascending order and stopping at the first size that fails;
  - `question_counts`: `bank_counts` plus 5, which is always kept because a
    size-5 shortage is generated (T059).
  - It creates nothing and calls no model.
- `BankComposer` first checks the stock counts per objective and level, so a
  hopeless size fails at once instead of running the search.
- The student UI shows only 5 until the server answers for the current
  choice, then shows only the returned sizes. Changing the choice re-checks;
  choosing a size does not. Server-side refusals (409 or 422) are unchanged,
  so a race can never create a short practice.
- Live generation stays at 5 questions.

### T062 and T061: inventory and replenishment (`app/practice/replenishment.py`)

**Inventory** is measured per objective and difficulty:

| Count | Meaning |
| ----- | ------- |
| Eligible | Questions practices can serve now, by the composer's own rule |
| Pending review | Seeder candidates never reviewed by the tutor; held from practices |
| Quarantined | Questions whose latest tutor verdict is quarantined |
| Rejected | Automated validation rejections |
| Performance | Served, answered, correct and accuracy, from real practices only (T060 analytics) |

**Triggers.** Each trigger records its evidence:

- `coverage`: no eligible question and nothing awaiting review;
- `low_inventory`: eligible plus awaiting review is below
  `MENTOR_PRO_REPLENISH_LOW_INVENTORY` (default 3);
- `performance`: at least `MENTOR_PRO_REPLENISH_MIN_ANSWERED` answers
  (default 10) and accuracy at or above `MENTOR_PRO_REPLENISH_MASTERY`
  (default 0.80).

Coverage and inventory triggers never wait for accuracy. These defaults are
configurable starting values, not validated mastery measures.

**Requests.**

- `generation.replenishment_request` holds at most one pending request per
  cell. A unique partial index on `open` and `candidates_generated` enforces
  this.
- `assess` stores an inventory snapshot (`generation.inventory_snapshot`) and
  opens requests. It closes a request when its cell no longer triggers
  (`satisfied`), or when its candidates have been reviewed (`reviewed`); a new
  request may follow.
- A pending request is never generated twice.

**Run** (`python -m app.practice.replenish run --subject S --max-calls N`):

- It generates candidates for open requests with the existing seeder
  (`seeding.run --objective`): fixed-plan gap cells only, the advisory lock,
  free models only and the shared daily budget.
- It stops at `MENTOR_PRO_REPLENISH_MAX_BATCH` candidates (default 100, at
  most 100) or `N` calls, and keeps the requests open on a budget, rate-limit
  or call-limit stop.
- An objective with no remaining planned gap closes as `no_planned_gap`.
  Adding cells beyond the fixed 100-cell plan is a PO decision.

**Review.**

- Candidates are held until a human tutor approves them through the existing
  `seed_bank item-review-sample` and `item-review-record` workflow. This code
  never records a verdict.
- Approved questions become eligible through the existing rules.
  Quarantined questions never do.

**Tutor view.** `GET /api/tutor/practice/bank` (tutor token, read-only)
returns the latest snapshot per subject plus pending and recently closed
requests, as counts and codes only. The tutor page shows it under "Banco de
preguntas y reposición".

## Consequences

- A rate-limited fallback model costs at most one call cycle per 5 minutes
  instead of a cycle on every request. Truncation gets one larger attempt
  before any fallback.
- Students see only sizes that start. Larger sizes appear by themselves as
  approved inventory grows, with no configuration change beyond permitting
  the sizes in `MENTOR_PRO_BANK_ONLY_SUBJECTS`.
- Inventory growth is bounded by the free daily budget (about 2–3 calls per
  candidate) and by the tutor's review time. The 100-per-subject target takes
  many days.
- Two additive tables are created `IF NOT EXISTS`. There is no versioned
  migration, and no existing row changes.

## Related

- Reports: `docs/progress/task_T061_result.md`, `task_T062_result.md`,
  `task_T063_result.md`, `task_T064_result.md`
- [RCA-006](../rca/RCA-006-bank-only-shortage-dead-end.md) (every offered
  option must start)
