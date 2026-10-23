# Active Context: Session Handoff 2026-10-22

## Session Metadata

- **Last Updated:** 2026-10-22
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING

## Current Objective

T006 is complete. Next: plan the next Product Owner task (practice sessions)
after approval. Do not start T007 without it.

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

### Current State

- `main` pushed to `origin/main`; working tree clean; no task locks; no
  background servers.
- `.env` exists (git-ignored) with `OPENROUTER_API_KEY`, pinned free models,
  `OPENROUTER_MAX_REQUESTS_PER_DAY=1000` (account not free tier) and
  `MENTOR_PRO_DEV_ENDPOINTS=true`.
- Tables: `curriculum.*`, `llm.usage_record`, `generation.question_attempt`.
- Tests: 254 passing; ACE gate `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. Plan the next PO task (practice session generation) with an ADR first.
2. Human spot checks of rubric scores (`question-evaluation`); M02 accepted
   1 in 7 requests, so maths prompt tuning is a candidate.
3. `scripts/pubs/check_lane.py` (session start prompt) does not exist here.

### Blockers/Issues

- Free models: Gemma 429 (upstream), Nemotron Super 404, Inkling 403 for this
  account; only Nemotron 3 Ultra, MiniMax M3.1 Flash, Nemotron 3.5 Super VL
  pinned.
- Rubric is model-scored by one free model; it missed awkward M02 wording.
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Automated browser checks fail on this machine (Edge under automation).
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
  [ADR-010](../adr/ADR-010-single-question-generation.md)
