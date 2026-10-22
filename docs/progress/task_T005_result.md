# Task T005 Result: OpenRouter API Integration

> **Date:** 2026-10-21
> **Status:** Implemented and verified with mocks — live connectivity not run
> **Decision:** [ADR-009](../adr/ADR-009-openrouter-integration.md)

---

## Summary

`app/llm/` adds OpenRouter settings, model discovery, free-first routing with
an explicit paid gate, timeouts and limited retries, and per-attempt usage
records (model, tokens, USD cost, latency) in PostgreSQL. A developer-only
CLI performs the connectivity check. No question generation; curriculum and
student interface unchanged.

---

## Live Connectivity Test

| Item | Result |
|------|--------|
| Command | `.venv/Scripts/python.exe -m app.llm.connectivity` |
| Outcome | `not_configured`: no `.env` / `OPENROUTER_API_KEY` on this machine |
| Model used, tokens, cost, latency | **Not available** — no live call was made |

To run it: `.venv/Scripts/python.exe scripts/dev/setup_secrets.py`, then the
command above. It prints `model_used`, `tokens_in`, `tokens_out`, `cost_usd`,
`cost_source` and `latency_ms`, and stores one row per attempt in
`llm.usage_record`.

---

## Tests

| Suite | Result |
|-------|--------|
| `tests/app/test_openrouter.py` (mocked transport, 28 tests) | Pass |
| Full suite (`tests/ace`, `tests/curriculum`, `tests/app`) | 211 passed, 0 skipped |
| ACE gate | `VERIFY_RESULT=pass gate=all` |
| Mutation check | Removing the paid gate or USD budget check fails 3 tests; code restored |
| Secret scan | No OpenRouter key in tracked files |

Covered by mocks: settings and validation; discovery and free detection;
configured-model priority and auto-selection; usage capture
(`provider_reported`, `generation_endpoint`, `missing` → NULL); `model_used`
from the response; 429 with `Retry-After`; retry limit then next model;
timeouts; non-retryable 400; invalid body; 401 on chat and discovery; 402;
paid disabled, enabled within budget, blocked by $0 cap or unknown paid cost;
daily request cap; schema-valid records without the key; PostgreSQL usage
store; key absent from all frontend and OpenAPI responses.

---

## Limitations

| Topic | Note |
|-------|------|
| Live call | Pending owner credentials |
| Free model default | Empty = auto-select top 3 free models; set `OPENROUTER_FREE_MODELS` to pin |
| Usage store | `llm.usage_record` created on first use in the target database |
