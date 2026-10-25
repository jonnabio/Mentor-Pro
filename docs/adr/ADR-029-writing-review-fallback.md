# ADR-029: Writing Reviewer Qualification and Fallback

> **Status:** Accepted (Product Owner task T031)
> **Date:** 2026-10-25

---

## Context

The independent review W08 (ADR-020) and the revalidation of quarantined
exercises (ADR-027) route over `OPENROUTER_FREE_MODELS`, the list multiple
choice also uses. The generator is excluded (RCA-004). On 2026-10-25 the
only listed model other than the generator was
`nvidia/nemotron-3.5-super-vl:free`: `minimax/minimax-m3.1-flash:free` is
still configured but no longer listed by OpenRouter. That reviewer often
answers HTTP 502 or truncates, and its outage blocks new exercises and
revalidations. Self-review was detected by exact id equality, so a variant
id of the generator (`:free`, `:beta`) would not match.

---

## Decision

### Routing

- `OPENROUTER_WRITING_REVIEW_MODELS`: the ordered writing-review list,
  primary first, then qualified fallbacks. It is used only by
  `generation.review_route()`, the review call of L1, L2–L4 and
  revalidation. Empty keeps the earlier behavior (the free list).
  Multiple-choice routing and generation settings are unchanged.
- `route(models=…)` uses exactly the listed models that OpenRouter
  currently lists as free text models, in order; an unlisted model is
  skipped, never replaced by another one.
- The generator is excluded by model identity (`same_model`: the id
  without its variant suffix), in `route` and in the second defense
  `same_model_review`, which checks both the requested and the reported
  model. Self-review is never accepted.
- Retries stay bounded (`OPENROUTER_MAX_RETRIES` per reviewer). Every
  attempt reserves the shared `BudgetGate`; a budget refusal during the
  fallback stops with `daily_budget` and stores nothing. The revalidation
  call cap rises from 4 to 6 (3 attempts per reviewer, primary and
  fallback); daily request and USD budgets are unchanged.
- The model that answered is stored with the review
  (`review.reviewer_model` in `writing.generation_attempt`; the validation
  row already stores it) and in every `llm.usage_record`.

### Qualification

A model is added only after `scripts/dev/benchmark_writing_reviewers.py`
shows, on its 12 fixed cases (4 stored L1–L4 exercises, 8 in-memory copies
with one seeded defect each: wording, ambiguous correction, paragraph
mismatch, incomplete instructions), all of the following:

| Criterion | Threshold |
|-----------|-----------|
| Valid structured review | at least 11 of 12 cases |
| Truncation | at most 10 % of cases |
| HTTP errors | at most 25 % of attempts |
| Seeded defects flagged (any score below 2) | at least 7 of 8, every category at least once |
| Stored valid exercises passed | at least 3 of 4 |

Candidates come from the live model listing by a stated rule (free text
model; not a generator, the primary reviewer, a router or a specialist
model; structured output; context of at least 32 000 tokens; one per vendor,
other vendors than the generator's first, then the longest context), never
from a fixed list. Connectivity alone never qualifies a model. If none
qualifies, the list keeps only the primary reviewer and the result says so.

### Result (2026-10-25)

No candidate qualified. `dots-studio/dots-3-note-preview:free` answered
12/12 with no errors but flagged 4 of 8 seeded defects; the other two
were rate limited (HTTP 429). The list keeps only the primary reviewer.
Details: [task_T031_result.md](../progress/task_T031_result.md).

---

## Consequences

- A second qualified reviewer lets reviews continue during a primary
  outage; an unqualified one is never used.
- Re-qualification is needed when a model leaves the listing or a review
  prompt changes; the benchmark is repeatable and stores its report.
- Seeded defects are few and partly keyword-like; the benchmark shows a
  minimum, not a full measure of review quality.
