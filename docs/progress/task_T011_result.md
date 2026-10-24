# Task T011 Result: Reduce OpenRouter Generation Truncation

> **Date:** 2026-10-23
> **Status:** Done — implemented; no measured reliability improvement
> **Decision:** [ADR-010](../adr/ADR-010-single-question-generation.md) (T011 note)

---

## Summary

The question-generation output limit is now configurable
(`OPENROUTER_GENERATION_MAX_TOKENS`, default 6000, allowed 1000–16000);
blind-solve (2000) and review (3000) limits are unchanged. Truncation
detection is explicit. A small live sample at 6000 shows **no reliability
improvement**: three successful replies needed more than 4000 tokens and were
rescued, but runaway outputs simply ran to the new limit, the truncation rate
did not fall, and latency rose.

---

## Implementation

| Area | Change |
|------|--------|
| `app/llm/settings.py` | `generation_max_tokens` (env `OPENROUTER_GENERATION_MAX_TOKENS`, default 6000, bounds 1000–16000) |
| `app/generation/pipeline.py` | Generation uses the setting; `SOLVE_MAX_TOKENS` 2000 and `RUBRIC_MAX_TOKENS` 3000 unchanged |
| `app/llm/client.py` | `reached_output_limit`: `finish_reason == "length"`, a length `native_finish_reason` (`length`, `max_tokens`, `max_output_tokens`, `model_length`), or no reason with output tokens ≥ limit → `invalid_output` / `truncated`; blank content → `invalid_output` / `empty` |
| Recording | Unchanged schema: each attempt's `status`, `error_kind` and `tokens_out` already record whether it hit the limit |
| `.env.example` | Setting documented |

Retry, fallback, validation and budget policies are unchanged: a truncated
reply fails that attempt, the router moves to the next model, and the
request retries within existing limits. Paid models stay disabled.

Tests (mocked): default 6000 and override; boundaries 999 / 1000 / 16000 /
16001 / non-numeric; seven detection cases (length, native reason, no reason
at and below the limit, explicit stop at the limit, empty content); truncated
generation falls back and is recorded; per-purpose limits sent to OpenRouter
(generation 6000 or configured, solve 2000, review 3000).

---

## Comparison

Baseline: every generation call since the T006 final runs (limit 4000; T006
to T010, single questions and sets). New: 10 single-question requests at
6000 on the evidencias where truncation occurred (M02 E1/E2, M04 E1/E2,
M05 E1, two rounds), medium difficulty.

| Metric (generation calls) | 4000 (baseline) | 6000 (probe) |
|---------------------------|-----------------|--------------|
| Calls | 104 | 19 |
| Successful | 78 (75 %) | 10 (53 %) |
| Truncated | 21 (20.2 %) | 7 (36.8 %) |
| Other errors (502, connection, invalid) | 5 | 2 |
| Mean output tokens, successful | 2 047 | 3 245 |
| Successful replies above 4 000 tokens | 0 (impossible) | 3 |
| Median latency, successful | 38.7 s | 60.6 s |
| Mean latency, truncated | 81.2 s | 89.6 s |

| Metric (requests) | 4000 | 6000 |
|-------------------|------|------|
| Requests | 61 | 10 |
| Unavailable (all models failed) | 13 (21 %) | 4 (40 %) |
| Accepted | — (mixed set/single runs) | 4 |

Probe usage: 31 calls, 22 374 / 90 349 tokens, **$0.00**.

Fisher exact tests: truncation 7/19 vs 21/104, p = 0.14; unavailable 4/10 vs
13/61, p = 0.24. The sample is small; the data do not show a difference in
either direction at conventional levels.

By model, truncation at 6000: Nemotron 3 Ultra 4 of 15, Nemotron 3.5 Super
VL 3 of 4 (baseline 11 of 88 and 10 of 16). Every truncated call at 6000 used
exactly 6000 tokens.

---

## Conclusion

The change **does not measurably improve reliability**; it mainly increases
output length and latency. It rescues the minority of replies that finish
between 4000 and 6000 tokens (3 of 10 successes here), but most truncations
are runaway reasoning that consumes any limit. The fallback model (Nemotron
3.5 Super VL) truncates most of the time at either limit.

Levers more likely to help (not implemented; need approval):

1. Limit or exclude reasoning tokens through OpenRouter's `reasoning`
   parameter for generation, where the model supports it.
2. Remove Nemotron 3.5 Super VL from the generation fallback (keep it for
   blind solve and review, where it works).
3. Keep 4000–6000 as the default; going higher adds latency for little gain.

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 328 passed |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Note: the local server started before this change keeps the 4000 limit until
it is restarted.
