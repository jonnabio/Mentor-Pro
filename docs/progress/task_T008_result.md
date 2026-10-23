# Task T008 Result: Controlled Parallel Question Generation

> **Date:** 2026-10-23
> **Status:** Done — live set complete (5/5) at concurrency 2
> **Decision:** [ADR-012](../adr/ADR-012-controlled-parallel-generation.md)

---

## Summary

Practice-set slots now run on a bounded thread pool
(`QUESTION_GENERATION_CONCURRENCY`, default 2). Budgets are reserved
atomically before every HTTP attempt, accepted items are committed only after
a set-wide duplicate check under a lock, and results keep allocation order.
Curriculum, schemas, validation rules and the student interface are
unchanged. The live Matemáticas set (M02, M04, M05) completed 5/5 in 628 s,
53 % less wall-clock time than the T007 acceptance set, at $0.00.

---

## Implementation

| Area | Change |
|------|--------|
| `app/llm/budget.py` | `BudgetGate`: lock-protected reservation per HTTP attempt (daily requests incl. in-flight, per-set cap, paid USD with one paid call in flight); settled after records are stored |
| `app/llm/client.py` | `chat(before_attempt=…)`: asks the gate before every attempt, including retries; refusal → `budget_blocked` attempt |
| `app/llm/router.py` | Uses a shared or private gate instead of one check per model |
| `app/generation/practice_set.py` | Thread pool; grounding before workers start; commit-time D01 against committed items; per-slot histories; outcomes ordered by slot; `SetBudgetStore` removed |
| `app/generation/validation.py` | `duplicate_reason` (existing D01 check, unchanged) |
| `.env.example` | `QUESTION_GENERATION_CONCURRENCY` and set limits documented |

Pre-existing defect fixed: the router checked the daily budget once per
model, but the client could retry up to `OPENROUTER_MAX_RETRIES` times, so a
limit could be exceeded by up to two calls even without concurrency. The gate
now reserves before every attempt.

Retries are unchanged and bounded: 429/5xx/timeouts with exponential backoff
and `Retry-After` (2 retries per model), truncated or invalid responses fail
the attempt, and each slot retries up to 3 requests.

---

## Performance: T007 vs T008

Same configuration (Matemáticas M02, M04, M05; medium; 5 questions), limits
5 / 3 requests per slot / 80 calls per set, free models only, daily budget
unchanged.

| Metric | T007 `set-d5c125f2` (sequential) | T008 `set-5b7eb9ee` (concurrency 2) | Change |
|--------|----------------------------------|-------------------------------------|--------|
| Total time | 1 342 s | **628 s** | −53 % |
| Time per accepted question | 268 s | 126 s | −53 % |
| Accepted | 5/5 | 5/5 | = |
| Generation attempts (accept rate) | 10 (50 %) | 7 (71 %) | — |
| Requests | 8 | 7 | — |
| OpenRouter calls | 31 (19 ok) | 18 (13 ok) | — |
| Tokens in / out | 15 669 / 46 124 | 14 172 / 40 587 | −10 % / −12 % |
| Provider-reported cost | $0.00 | $0.00 | = |

The time reduction comes from concurrency. Differences in attempts, calls
and tokens come from free-model variability (T007 had 12 failed calls, T008
5), not from the change: one run each is not enough to claim an effect on
acceptance rate.

### Rejections (T008)

| Slot | Request | Reason |
|------|---------|--------|
| 4 | `req-51fa043b` | unavailable: both models truncated at 4000 tokens — retried, then accepted |
| 5 | `req-443f4a97` | M02: option A unit `''` ≠ `tapitas`, then the next attempt was truncated — retried, then accepted |

### Accepted questions

| Slot | Objective / evidencia | Validation | Key (verified by hand) |
|------|-----------------------|------------|------------------------|
| 1 | M02 E1 compara naturales | M04 warn → blind solve C agrees | 180 450 < 210 000 < 250 300 → C |
| 2 | M02 E2 compara fracciones | Proven (`select: min`) | 1/2 < 3/5 < 5/8 < 7/10 → A |
| 3 | M04 E1 múltiplos | Proven (`select: max`) | 24 divides 72, even, multiple of 3 → D |
| 4 | M04 E2 divisibilidad | M04 warn (property) → blind solve C agrees | 180: ends in 0, digit sum 9 → C |
| 5 | M05 E1 divisiones | Proven (`1236 / 12`) | 103 → A |

All five pass checks C01–C09, G01–G02, D01 and L01–L03, with rubric 2 on
every criterion. Usage records belong to exactly one request each.

---

## Quality

No regression: validation rules and checker are unchanged (1.5.0), and every
accepted item passed them.

**Finding (pre-existing, not changed because T008 forbids rule changes):**
slot 3 was "proven" by `select: max`, which only shows that 24 is the largest
option, not that it meets "misma cantidad … múltiplo de 3 y par". The key is
correct (checked by hand), but the proof is incomplete in the same way as the
T007 `3 * 6` case that M04 now catches for expressions. Proposed follow-up:
apply the property-selection rule to `select` when the stem adds conditions
("de modo que", "múltiplo", "par"), so the blind solve decides.

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 282 passed (3 consecutive runs without failures for the set tests) |
| New tests | 40-thread gate atomicity; concurrent daily-budget and set-cap limits never exceeded; simultaneous duplicates rejected at commit (barrier forces overlap); retries isolated per slot; output order kept when completion order differs; concurrency env validation |
| Mutation check | Disabling the commit-time D01 check fails the duplicate test |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

---

## Open Items

1. `select`-based proofs for property questions (see Quality).
2. Truncation at 4000 tokens remains the main failure mode of the free
   generator.
3. Higher concurrency is untested live; free models are limited to about 20
   requests per minute.
