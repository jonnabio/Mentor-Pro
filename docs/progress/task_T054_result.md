# T054 Result: Live Fallback Validation and M09 Pilot

- **Date:** 2026-11-05 (UTC)
- **Role:** Developer (operations)
- **Status:** Done. One run under `PO-T054-M09-2026-11-05` on
  `v2026.11.05-1`. Stopped at the call limit.
- **Command:** `seed_bank run --subject matematicas --objective M09
  --max-calls 10`, 19:54:28–19:58:32 UTC (244 s), `run_call_limit`.

## Preflight

`STATUS HEALTHY` on `c1e6ba1a…e112`; bank-only off; models Nemotron then
Gemma 4 26B, both listed free text models; 13/200 requests used today;
batch `bb-matematicas-cd792836` `open`/`pending`; no advisory lock or
seeding process; M09 0/5.

## Calls

| Purpose | Model | Calls | Outcome |
| --- | --- | --- | --- |
| generation | `nvidia/nemotron-3-ultra-550b-a55b:free` | 3 | 2 `invalid_output` (`truncated` at 4,000 tokens, about 72 s); 1 ok (81 s) |
| generation (fallback) | `google/gemma-4-26b-a4b-it:free` | 6 | all `rate_limited` (`http_429`, under 0.5 s) |
| review | `nvidia/nemotron-3.5-super-vl:free` | 1 | ok (7 s), `accept` |
| independent solve | — | 0 | key proven |

Cost $0. Daily count 13 → 23 of 200.

## Findings

- The fallback route works: after each Nemotron truncation the router
  moved to Gemma with `is_fallback=true`. Gemma returned no output (free
  tier rate limited upstream).
- Nemotron did not time out this time; its failure mode was output
  truncation at `max_tokens` 4,000.

## Questions

- 3 attempts, all cell 41 (M09 E1, medium): 1 accepted (all checks pass,
  review `accept`), 2 `unavailable` (all candidate models failed). None
  rejected by validation.
- M09 1/5 filled; the question is held from practice until a tutor
  approves it. Eligible Matemáticas inventory unchanged at 12.
- `item-review-sample --objective M09` exported 1 question with answer
  key to `~/mentor-pro-review/T054-M09-2026-11-05.json` on the server
  (mode 600, outside Git). No verdict recorded.
- Health after the run: `STATUS HEALTHY`.
