# Active Context: Session Handoff 2026-10-23

## Session Metadata

- **Last Updated:** 2026-10-23
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING

## Current Objective

T015 (practice cancellation) is complete. Next: the next Product
Owner task after approval (not 10–30 question sets, answering or frontend
without it).

## Handoff Summary

### Completed

- Repository reset to an ACE 2.7.0 baseline; MEP sources kept out of Git
  (checksums in `references/MANIFEST.sha256`, generic names).
- PostgreSQL 17: role `mentor_pro_admin` owns `mentor_pro` and
  `mentor_pro_test`.
- T001 — nine question-engine skills, standard, schemas, deterministic checker,
  skill validator ([ADR-005](../adr/ADR-005-question-engine-skill-suite.md)).
- T002 — curriculum baseline `PNE2026-SUM-v1.0` (98 objectives, 344
  evidencias) ([ADR-006](../adr/ADR-006-curriculum-baseline-v1.md)).
- T003 (PO T002.1) — catalog in PostgreSQL schema `curriculum`
  ([ADR-007](../adr/ADR-007-postgresql-curriculum-catalog.md)).
- T004 (PO T003) — practice configuration API and Spanish UI
  ([ADR-008](../adr/ADR-008-practice-configuration-api.md)).
- T005 — OpenRouter client, free-first routing, paid gate, budgets, usage
  records ([ADR-009](../adr/ADR-009-openrouter-integration.md)); live
  connectivity verified ($0).
- T006 — single grounded question: grounding, prompt 1.1.0, checker 1.3.0
  (math `select`, M04 operand grounding), blind solve, rubric, dev endpoint
  ([ADR-010](../adr/ADR-010-single-question-generation.md)). Final (checker
  1.4.0, prompt 1.2.0): M02, C01, EL01, ES01 each accepted; $0.00 over 82
  calls. C09 now rejects material key-length cues (PO decision). Seven live
  defects fixed (`docs/progress/task_T006_result.md`).
- T007 — practice sets ([ADR-011](../adr/ADR-011-validated-practice-sets.md)):
  `generate_set`, limits 5 questions / 3 requests per slot / 80 calls per set,
  checker 1.5.0 (L01–L03, M04 property selection), prompts generation 1.3.0
  and rubric 1.1.0, tables `generation.practice_set` and `practice_set_item`,
  `POST /api/dev/practice-sets/generate`. Live: complete 5/5, 31 calls, $0.00,
  22 min (`docs/progress/task_T007_result.md`).
- T008 — parallel slots ([ADR-012](../adr/ADR-012-controlled-parallel-generation.md)):
  `QUESTION_GENERATION_CONCURRENCY` (default 2), `BudgetGate` reserves budget
  before every HTTP attempt, commit-time D01, slot-ordered results. Live 5/5
  in 628 s (T007: 1 342 s), $0.00 (`docs/progress/task_T008_result.md`).
- T009 — checker 1.6.0: a maths proof counts only if it establishes what the
  stem asks (number properties or extra conditions → blind solve required);
  [RCA-002](../rca/RCA-002-math-proof-not-establishing-question.md) and guard
  (`docs/progress/task_T009_result.md`).
- T010 — student practice ([ADR-013](../adr/ADR-013-student-practice-sessions.md)):
  schema `practice` (session, item, answer), in-process job queue with
  polling, server-side evaluation, one question at a time, feedback, summary;
  `scripts/dev/practice_e2e.py` (Playwright + Chrome). Live: 5/5 in 366 s,
  $0.00 (`docs/progress/task_T010_result.md`).
- T011 — `OPENROUTER_GENERATION_MAX_TOKENS` (default 6000), explicit
  truncation detection. Live probe: no measured reliability gain, higher
  latency (`docs/progress/task_T011_result.md`).
- T012 — results/failed screens: "Nueva práctica" and "Volver al menú
  principal" (no new job). Generation default 4000; Super VL excluded from
  generation only; optional `OPENROUTER_GENERATION_REASONING_EFFORT` (off)
  (`docs/progress/task_T012_result.md`).
- T013 — question bank ([ADR-014](../adr/ADR-014-validated-question-bank.md)):
  practices reuse eligible accepted questions by slot (current checker or
  recorded revalidation in `generation.bank_revalidation`); only missing slots
  are generated. Live: bank-only practice in 1.9 s with 0 calls
  (`docs/progress/task_T013_result.md`).
- T014 — learning dashboard ([ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)):
  six configurable statuses from first attempts on distinct questions,
  `GET /api/dashboard`, "Ver mi progreso"; bank freshness from global history
  (`docs/progress/task_T014_result.md`).
- T015 — "Salir de la práctica" with confirmation; `practice.session.cancelled_at`;
  answers kept and counted (`docs/progress/task_T015_result.md`).

### Current State

- `main` pushed to `origin/main`; working tree clean; no task locks; no
  background servers.
- `.env` exists (git-ignored) with `OPENROUTER_API_KEY`, pinned free models,
  `OPENROUTER_MAX_REQUESTS_PER_DAY=1000` (account not free tier) and
  `MENTOR_PRO_DEV_ENDPOINTS=true`.
- Tables: `curriculum.*`, `llm.usage_record`, `generation.question_attempt`,
  `generation.practice_set`, `generation.practice_set_item`,
  `generation.bank_revalidation`, `practice.session`, `practice.item`,
  `practice.answer`.
- Tests: 365 passing; ACE gate `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. Plan the next PO task with an ADR first. Only Nemotron 3 Ultra generates
   now (MiniMax unlisted, VL excluded): no generation model fallback. The
   reasoning-effort setting is untested live.
2. Property cues are keyword heuristics (T009 limitations); a typed
   property check (divisibility, parity) would make such keys provable.
3. Human spot checks of rubric scores (`question-evaluation`).
4. `scripts/pubs/check_lane.py` (session start prompt) does not exist here.

### Blockers/Issues

- Mocked browser tests write to the same database as the single student:
  275 of 343 stored answers are test data (`Q-mock-…`); decision pending.

- Free models: Gemma 429 (upstream), Nemotron Super 404, Inkling 403 for this
  account; only Nemotron 3 Ultra, MiniMax M3.1 Flash, Nemotron 3.5 Super VL
  pinned.
- Rubric is model-scored by one free model; it missed awkward M02 wording.
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Edge cannot start under automation; browser tests use installed Chrome.
- Docker not installed; `docker-compose.yml` untested.
- Student first name in pushed commit `42adbe7`; rewrite needs approval.
- Remote branch `origin/copilot/clean-repository` (merged PR #1) remains.
- Framework markdown lint debt (`docs/TODO-markdown-lint.md`).

### Notes

- Tracker IDs `^T[0-9]{3}$`; PO labels kept in task names/notes.
- App: `.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
  (reads `.env`).
- Connectivity: `.venv/Scripts/python.exe -m app.llm.connectivity`.
- Dev generation: `POST /api/dev/questions/generate` (only with
  `MENTOR_PRO_DEV_ENDPOINTS=true`).
- Gate: `bash .ace/scripts/verify.sh` (tests need `mentor_pro_test`).
- Never expose keys or student data; `approved_baseline` items are not official
  MEP wording.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)
