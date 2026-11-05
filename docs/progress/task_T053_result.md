# T053 Result: Question Generation Provider Fallback

- **Date:** 2026-11-05
- **Role:** Developer
- **Status:** Done (PO authorization 2026-11-05). Not merged, released or
  deployed. No production configuration change, no live generation call.
- **Decision record:** [ADR-009](../adr/ADR-009-openrouter-integration.md)
  (amendment T053). Evidence: [T052 result](task_T052_result.md).

## Change

- `app/llm/settings.py`: `OPENROUTER_QUESTION_GENERATION_MODELS`
  (`question_generation_models`), ordered primary then fallbacks; empty by
  default; duplicates and excluded generation models refused.
- `app/generation/pipeline.py`: the generation route passes that list as
  `models=` (one argument). Blind solve, review and the RCA-002 proof
  rules are unchanged.
- `app/llm/router.py`: explicitly listed models that are not currently
  free are named in the failure message instead of disappearing.
- `.env.example`: the new setting.

## Fallback selection

From the public OpenRouter listing (2026-11-05, metadata only; no
provider request was made): `google/gemma-4-26b-a4b-it:free` is listed
and free, from Google (a different provider from Nvidia), 262,144
context, with `response_format` and `reasoning`. It is the PO's
candidate; `google/gemma-4-31b-it:free` is listed too. Neither has been
tested live: quality and latency need a measured run. Generation prompts
carry curriculum text only, no student data.

## Verification

- `tests/app/test_question_generation_fallback.py` (11, mocked
  OpenRouter): primary ok (no fallback generation); primary timeout, 502
  or 429 → three bounded attempts then the fallback, provenance names it;
  both failing → `unavailable` after 6 calls, no third model; fallback
  output rejected by validation → no model switch; every sent request
  recorded and counted, and the daily budget stops the fallback too;
  blind solve and review avoid the generating fallback; without the
  setting, earlier behavior; an unlisted fallback is named, not
  substituted; settings load and refusals.
- Regression: `test_generation.py` and `test_item_checker.py` (RCA-002),
  writing reviewer tests (RCA-004): pass.
- Full gate `bash .ace/scripts/verify.sh`: `VERIFY_RESULT=pass gate=all`
  (944 passed, 9 skipped; lint passed), logs
  `.ace/logs/verify/20261105-082450-1920`.
