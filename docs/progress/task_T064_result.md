# T064 Result: Free-Generation Reliability

- **Role:** Developer (PO authorization PO-QUESTION-BANK-PHASE-B-2026-11-09)
- **Status:** implemented and tested; production pending deployment

## Evidence that drove the change (production, read-only, 2026-11-05..09)

- Fallback model `google/gemma-4-26b-a4b-it:free`: 31 generation calls,
  all HTTP 429, no success.
- Primary model `nvidia/nemotron-3-ultra-550b-a55b:free`: 128 ok, 18
  truncated, 11 timeouts, 2 HTTP 502.
- Practices: 10 complete; 3 partial and 2 failed (`slot_retries_exhausted`);
  1 partial (`llm_unavailable`).

## Change (ADR-036)

- `app/llm/cooldown.py` (new): process-wide per-model cooldown.
- `app/llm/client.py`: records `Retry-After`; a wait over 30 s is not slept
  through.
- `app/llm/router.py`:
  - Skips cooling models and cools a model still rate limited after its
    retries.
  - Returns `rate_limited` with no request when every model is cooling.
  - Retries one truncated generation on the same model with twice the
    output limit (at most 16,000 tokens).
- `app/llm/settings.py`: `OPENROUTER_RATE_LIMIT_COOLDOWN_S` (default 300,
  0 to 3600).
- `app/generation/practice_set.py` and `app/practice/seeding.py`: stop with
  `provider_rate_limited` instead of spending slot retries.
- `app/practice/routes.py`: Spanish message for that stop.

## Tests

`tests/app/test_generation_reliability.py` (21) covers:

- Bounded exponential back-off with jitter; short `Retry-After` honoured;
  long `Retry-After` not slept.
- Cooldown start, bounds and expiry; skipped on the next request; all models
  cooling sends nothing; a longer `Retry-After` extends the cooldown.
- The paid model is never added by rate limits.
- The setting is validated.
- Truncation retry happens once, is bounded, applies to generation only,
  stays within the daily budget, and is recovered by the larger limit.
- A rate-limited whole set stops early with no items.
- Malformed output never enters a set.

`tests/app/test_openrouter.py`: the truncation test was updated for the new
same-model retry.

## Operational limitations

- Free model capacity is outside our control. With every model cooling, a
  size-5 shortage practice fails with "El servicio de generación de
  preguntas está saturado" instead of waiting.
- The cooldown lives in process memory: the app and tutor processes keep
  separate cooldowns, and a restart clears them.
- The daily request budget still bounds everything. A truncation retry
  costs one extra call.

## Release

- PR #66 merged into `dev` as `f207de4` (dev CI 42750606976, green).
  Authorization `PO-PHASE-B-PROD-2026-11-09`.
