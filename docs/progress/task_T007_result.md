# Task T007 Result: Validated Practice Set Generation

> **Date:** 2026-10-23
> **Status:** Done — acceptance set complete (5/5)
> **Decision:** [ADR-011](../adr/ADR-011-validated-practice-sets.md)

---

## Summary

A practice set is generated from a practice configuration by reusing the
ADR-008 allocation and the ADR-010 single-question engine, slot by slot, with
bounded retries, an in-set duplicate bank, new linguistic checks and
per-set persistence. The live acceptance set (Matemáticas M02, M04, M05;
medium; 5 questions) completed with 5 accepted questions at $0.00.

---

## Implementation

| Area | Change |
|------|--------|
| `app/generation/practice_set.py` | `generate_set`, `SetLimits` (5 questions, 3 requests/slot, 80 calls/set; env overridable), `SetBudgetStore` (hard per-set call cap via the router's budget check), coverage |
| Checker 1.5.0 | L01 announced content not shown; L02 unit named but options unitless; L03 unpaired `¿…?`; M04 property-selection stems need a blind solve |
| Prompts | Generation 1.3.0 (show announced data, units, `¿…?`); rubric 1.1.0 (`clarity` 0 for missing data/units, inconsistency) |
| Pipeline | `practice_set_id` on every usage record; bank stems passed to the prompt; `item_id` includes the request ID |
| PostgreSQL | `generation.practice_set`, `generation.practice_set_item`; `question_attempt.practice_set_id`, `slot` |
| Dev API | `POST /api/dev/practice-sets/generate` (`question_count` 5 only) |
| Live script | `scripts/dev/generate_practice_set.py` |

Defects found while building and fixed:

1. `item_id` was a content hash and D01 skips bank items with the same ID,
   so a byte-identical regeneration escaped the duplicate check. The ID now
   includes the request ID.
2. First live run: one truncated generation (`unavailable`) aborted the whole
   set. Model failures now count as a failed request and are retried; only
   budget limits stop a set.
3. L01 first searched the stem, rejecting "¿Cuál de los siguientes
   números…?", which refers to the displayed options. It now searches only
   the stimulus.
4. Second live run: `3 * 6` was accepted as proof that 18 is "múltiplo de 3 y
   par". An expression cannot prove a property selection; M04 now requires a
   blind solve for such stems. The set was regenerated under the final rules.

---

## Acceptance Run — `set-d5c125f283384f38`

Configuration: `matematicas`, `selected_objectives` M02, M04, M05, `medium`,
5 questions. Limits: 5 / 3 / 80. Daily budget unchanged (1000).

| Metric | Value |
|--------|-------|
| Status | **complete**, 5/5 accepted |
| Requests / generation attempts | 8 requests / 10 attempts (5 rejected) |
| OpenRouter calls | 31 (19 ok; 12 failed: HTTP 502, truncated, invalid response) — within the 80 cap |
| Tokens | 15 669 in / 46 124 out |
| **Provider-reported cost** | **$0.00** (no successful call with missing cost) |
| Generation time | 1 342 s (22.4 min) |
| Models | `nvidia/nemotron-3-ultra-550b-a55b:free` (generation), `nvidia/nemotron-3.5-super-vl:free` (blind solve, rubric) |

### Evidence coverage (planned = accepted)

| Slot | Objective | Evidencia | Validation | Key |
|------|-----------|-----------|------------|-----|
| 1 | M02 | B1-A2-E1 compara naturales | M04 warn → blind solve B agrees | B |
| 2 | M02 | B1-A2-E2 compara fracciones | Proven (`select: max`) | D |
| 3 | M04 | B1-A4-E1 múltiplos y pares | M04 warn → blind solve A agrees | A |
| 4 | M04 | B1-A4-E2 criterios de divisibilidad | M04 warn (property) → blind solve A agrees | A |
| 5 | M05 | B1-A5-E1 divisiones | Proven (`1236 / 12`) | A |

All five: checks C01–C09, G01–G02, D01, L01–L03 pass; rubric 2 on all five
criteria; Spanish (Costa Rica); objective and evidencia references match the
allocation; five distinct items.

Independent verification of the keys (by hand):

1. 450 000 < x < 500 000 among 440 000, 475 000, 500 000, 520 000 → 475 000.
2. 3/5 = 0,6; 4/7 ≈ 0,571; 5/8 = 0,625; 2/3 ≈ 0,667 → 2/3.
3. Even divisor of 84 among 6, 7, 9, 11 → 6 (84 ÷ 6 = 14).
4. Between 200 and 230, divisible by 2, 3, 5 and 10 → 210 (215, 225 odd;
   220 digit sum 4).
5. 1 236 ÷ 12 = 103.

### Rejection reasons

| Slot | Request | Reason |
|------|---------|--------|
| 2 | `req-232f7371` | unavailable: both models failed (502 / truncated) — retried |
| 2 | `req-1f87682c` | unavailable: both models failed — retried |
| 2 | `req-3035395f` #1 | L02: text names `litro`, options unitless (attempt 2 accepted) |
| 3 | `req-a59b5a71` #1 | rubric 1 for `alignment` (attempt 2 accepted) |
| 5 | `req-5e18527d` | pending: independent solve unavailable |

---

## All Live Runs

| Set | Code state | Result | Calls | Tokens in/out | Cost | Time |
|-----|------------|--------|-------|---------------|------|------|
| `set-ac1bacbc` | before fixes 2–3 | partial (`llm_unavailable`), 0/5 | 11 | 8 358 / 27 989 | $0 | 465 s |
| `set-50cb62d7` | before fix 4 | complete 5/5 (slot 3 hollow proof) | 25 | 17 092 / 45 093 | $0 | 1 112 s |
| `set-d5c125f2` | final | **complete 5/5** | 31 | 15 669 / 46 124 | $0 | 1 342 s |

Total T007 live usage: 67 calls, $0.00.

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 276 passed |
| New tests | Set completion and allocation, in-set duplicate, invalid items never fill a set, per-set call cap, daily budget stop, model failure retried, PostgreSQL persistence, dev endpoint and validation; L01–L03, property-selection M04 |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

---

## Open Items

1. Generation is sequential: about 4–5 minutes per question on free models;
   10–30 question sets need parallel slots or faster models.
2. Free models fail often (12 of 31 calls): 502s and 4000-token truncation.
3. Slot 2 wording ("cuatro grupos midieron la parte…") does not say which
   fraction belongs to which group; correct but weak. Rubric scored it 2.
4. Rubric scores remain model-assigned; human spot checks are pending.
