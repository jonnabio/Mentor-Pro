# T031 Result: Qualify a Second Independent Writing Reviewer

- **Date:** 2026-10-25
- **Status:** Verified — routing delivered; **no candidate qualified**
- **ADR:** [ADR-029](../adr/ADR-029-writing-review-fallback.md)
- **Benchmark report:** [T031/benchmark.json](T031/benchmark.json)

## Discovery

Live OpenRouter listing: 18 free text models. `minimax/minimax-m3.1-flash:free`
(configured) is no longer listed. The ADR-029 rule chose:

| Candidate | Context | Structured outputs |
|-----------|---------|--------------------|
| `dots-studio/dots-3-note-preview:free` | 512 000 | yes |
| `xingchen-agi/xing4.0-29b-a4b:free` | 262 144 | yes |
| `google/gemma-4-26b-a4b-it:free` | 262 144 | response format only |

Excluded with reasons in the report: the generator
(`nemotron-3-ultra`), the primary reviewer, `openrouter/free` (router),
code and safety models, models without structured output.
The primary `nvidia/nemotron-3.5-super-vl:free` ran as a reference.

## Benchmark

12 fixed cases with the production review prompts: 4 stored eligible
exercises (L1–L4, current revision) and 8 in-memory copies with one seeded
defect each (2 wording, 2 ambiguous corrections, 2 paragraph mismatches,
2 incomplete instructions). Stored records hashed identical before and
after; nothing was written to the `writing` schema.

| Model | Structured | Truncated | HTTP errors | Valid passed | Defects flagged | Median latency | Tokens in/out | Cost |
|-------|-----------|-----------|-------------|--------------|-----------------|----------------|---------------|------|
| super-vl (primary, reference) | 10/12 | 1/12 | 31 % (502) | 4/4 | 4/8 (ambiguous 0) | 28.3 s | 9 043 / 29 274 | $0 |
| dots-3-note-preview | 12/12 | 0 | 0 % | 4/4 | 4/8 | 19.6 s | 10 474 / 24 145 | $0 |
| xing4.0-29b | 5/12 | 0 | 81 % (429) | 2/4 | 1/8 | 35.2 s | 4 617 / 12 153 | $0 |
| gemma-4-26b | 0/12 | 0 | 100 % (429) | 0/4 | 0/8 | — | 0 / 0 | $0 |

Defects missed by every model that answered: `ambiguous-L1-solo`
(«solo» marked as an error), `mismatch-L4` (reversed paragraph plan),
`incomplete-L4`; dots also passed `wording-L1`.

## Qualification

| Model | Decision | Failed criteria |
|-------|----------|-----------------|
| dots-3-note-preview | not qualified | defects flagged 4/8 < 7 |
| xing4.0-29b | not qualified | structured 5/12, HTTP 81 %, defects 1/8, valid 2/4 |
| gemma-4-26b | not qualified | rate limited on every attempt |

No model met the criteria; none was added. The primary reviewer would not
meet them either (4/8 defects, 31 % HTTP errors): defect detection is a
weakness of the current free reviewers, not only of the candidates.

## Routing (delivered)

- `OPENROUTER_WRITING_REVIEW_MODELS` (local `.env`):
  `nvidia/nemotron-3.5-super-vl:free` only. A model is appended only after
  it qualifies.
- `generation.review_route()` serves L1, L2–L4 and revalidation; the
  generator and its id variants are excluded; self-review refused.
- Revalidation call cap 4 → 6; budgets unchanged; reviewer stored as
  `review.reviewer_model`.
- Multiple-choice routing and generation unchanged (tested).

## Usage and cost

91 benchmark calls (purpose `evaluation`, within the 160-call cap and
the 1000-request daily budget; 50 used before). Provider-reported cost
$0.00 for every answered call. No paid model enabled.

## Verification

- New tests `tests/app/test_writing_review_fallback.py` (13): primary ok,
  primary 502, primary truncated, primary unlisted, fallback ok, all fail,
  generator in the list, generator variant, reviewer resolving to the
  generator, budget exhausted during fallback, revalidation via fallback,
  multiple choice unchanged, discovery rule.
- Full suite 536 passed; ACE gate result below in the commit.

## Recommendations

1. Rerun the benchmark when the listing changes
   (`--discover` first); the rate-limited candidates may qualify later.
2. Consider strengthening the review prompt for ambiguous corrections and
   L4 plan order (a separate, approved task: prompt change).
