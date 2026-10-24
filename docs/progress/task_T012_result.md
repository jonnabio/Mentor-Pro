# Task T012 Result: Navigation Fix and OpenRouter Generation Optimization

> **Date:** 2026-10-23
> **Status:** Done
> **Decisions:** [ADR-013](../adr/ADR-013-student-practice-sessions.md),
> [ADR-010](../adr/ADR-010-single-question-generation.md) (T012 note)

---

## A. Student Navigation

| Screen | Actions |
|--------|---------|
| Results (complete or partial practice) | "Nueva práctica" (form with the previous configuration) and "Volver al menú principal" (initial screen: no subject, no objectives) |
| Failed or budget-blocked generation (0 questions) | Same two actions; heading "No se pudo preparar la práctica"; progress bar and wait hint hidden |
| Partial or budget-blocked with questions | Practice the available questions, then the results screen above |

Both actions are client-side only: no request is sent, no generation job is
created, the stored session token is cleared (a reload does not resume the
old practice), and the practice, items and answers stay in PostgreSQL.

Defect found and fixed: the failed state kept the title "Preparando su
práctica", a full progress bar and "Puede dejar esta página abierta…".

## B. Generation Configuration

| Setting | Default | Behaviour |
|---------|---------|-----------|
| `OPENROUTER_GENERATION_MAX_TOKENS` | **4000** (restored) | Generation only; solve 2000 and review 3000 unchanged |
| `OPENROUTER_GENERATION_EXCLUDED_MODELS` | `nvidia/nemotron-3.5-super-vl:free` | Removed from generation routing only; still used for blind solve and review |
| `OPENROUTER_GENERATION_REASONING_EFFORT` | empty (off) | `minimal`, `low`, `medium` or `high` → `reasoning: {"effort": …}` on generation calls, only for models listing `reasoning` |

### Investigation (OpenRouter `/models`, 2026-10-23)

| Pinned model | Listed | Reasoning parameters |
|--------------|--------|----------------------|
| `nvidia/nemotron-3-ultra-550b-a55b:free` | Yes | `reasoning`, `reasoning_effort`, `include_reasoning` |
| `nvidia/nemotron-3.5-super-vl:free` | Yes | `reasoning`, `include_reasoning` |
| `minimax/minimax-m3.1-flash:free` | **No** (skipped by routing) | — |

OpenRouter's unified control is the `reasoning` object (`effort`,
`max_tokens`, `exclude`); support is advertised per model in
`supported_parameters`. The router reads the cached model list and adds the
field only when supported, so unsupported models get the unchanged request.
Reasoning is never altered for blind solve or review.

**Consequence:** with Super VL excluded and MiniMax unlisted, Nemotron 3
Ultra is the only generation model. A generation failure is now retried
(client retries, then the request and slot retries) but has no model
fallback. Adding another free text model to `OPENROUTER_FREE_MODELS` restores
one.

Retry, fallback order, usage logging, request limits and monetary budgets are
unchanged; paid models stay disabled. No live benchmark was run (not
requested); the reasoning setting is off until enabled.

---

## Changed Files

| File | Change |
|------|--------|
| `app/static/index.html`, `app.js`, `styles.css` | Result and failed actions; main-menu reset; failed-state heading |
| `app/llm/settings.py` | Default 4000; excluded models; reasoning effort with validation |
| `app/llm/router.py` | Generation exclusion; `reasoning_body` only for generation and supported models |
| `app/llm/client.py` | `extra_body` merged into the request |
| `scripts/dev/practice_e2e.py` | Navigation checks |
| `tests/app/test_openrouter.py`, `tests/app/test_generation.py` | Default 4000; routing by purpose; reasoning sent only when supported |
| `.env.example`, ADR-010 | Settings documented |

---

## Tests

| Check | Result |
|-------|--------|
| Full suite | 332 passed |
| Browser (Chrome, mocked generator) | 114/114: results → menu (Matemáticas, Ciencias, mobile), results → new practice (Español, Estudios Sociales), failed → menu, partial (budget) → results → new practice; no job started, session cleared, practice still stored, no overflow |
| Routing | Excluded model never generates, still solves and reviews; fallback skips it |
| Reasoning | Sent as `{"effort": "low"}` only to the model that supports it, only for generation; absent when the setting is empty |
| Validation rules | Unchanged (checker 1.6.0; all checker tests pass) |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

Restart the local server to apply the new defaults.
