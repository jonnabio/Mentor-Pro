# Active Context: Session Handoff 2026-10-24

## Session Metadata

- **Last Updated:** 2026-10-24
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING
- **Session span:** 2026-10-22 to 2026-10-24 (T006 completion through T020)

## Current Objective

No task in progress. Wait for the next Product Owner task; plan it with an
ADR first. Do not start 10–30 question sets or new features without approval.

## Handoff Summary

### Completed

Baseline before this session: ACE 2.7.0 reset, T001 skills and checker
(ADR-005), T002 baseline `PNE2026-SUM-v1.0` (ADR-006), T003 PostgreSQL
catalog (ADR-007), T004 configuration API and UI (ADR-008), T005 OpenRouter
client and budgets (ADR-009).

This session (reports in `docs/progress/task_T0xx_result.md`):

- **T006** — single grounded question completed for M02, C01, EL01, ES01; C09
  rejects material key-length cues; per-attempt reasons recorded
  ([ADR-010](../adr/ADR-010-single-question-generation.md)).
- **T007** — validated 5-question practice sets, checker 1.5.0 (L01–L03
  linguistic checks), `generation.practice_set(_item)`
  ([ADR-011](../adr/ADR-011-validated-practice-sets.md)).
- **T008** — bounded parallel slots (`QUESTION_GENERATION_CONCURRENCY`=2),
  atomic `BudgetGate` per HTTP attempt, commit-time duplicate check; 53 %
  faster ([ADR-012](../adr/ADR-012-controlled-parallel-generation.md)).
- **T009** — checker 1.6.0: maths proofs count only if they establish what
  the stem asks; RCA-002 and regression guard
  ([RCA-002](../rca/RCA-002-math-proof-not-establishing-question.md)).
- **T010** — student practice in the web page: server-managed jobs with
  polling, server-side evaluation, feedback, summary, keys never sent early;
  `scripts/dev/practice_e2e.py` (Playwright + Chrome)
  ([ADR-013](../adr/ADR-013-student-practice-sessions.md)).
- **T011** — configurable generation token limit and explicit truncation
  detection; 6000 gave no measured gain.
- **T012** — "Volver al menú principal" / "Nueva práctica" on results and
  failed screens; generation default 4000; Nemotron 3.5 Super VL excluded
  from generation only; optional `OPENROUTER_GENERATION_REASONING_EFFORT`.
- **T013** — validated question bank: reuse eligible accepted questions by
  slot, revalidation records, generate only missing slots
  ([ADR-014](../adr/ADR-014-validated-question-bank.md)).
- **T014** — learning dashboard: six configurable statuses from first
  attempts on distinct questions, repeat-aware metrics, "Ver mi progreso"
  ([ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)).
- **T015** — "Salir de la práctica" with confirmation;
  `practice.session.cancelled_at`; answers kept and counted.
- **T016** (PO T014.1) — automated tests and browser runs use only
  `TEST_DATABASE_URL` (`mentor_pro_test`); `require_test_database` refuses
  the student database (pytest exit 4, `practice_e2e.py` exit 2); read-only
  report of historical test records, nothing deleted
  ([ADR-016](../adr/ADR-016-test-database-isolation.md)).
- **T017** — `practice.session_classification`: 103 sessions
  `automated_test`, 14 `quarantined`, 2 `student` (audit `T017-2026-10-24`);
  dashboard and exposure history use student sessions only; nothing deleted
  ([ADR-017](../adr/ADR-017-session-classification.md)).
- **T018** — intermittent browser failure fixed ("Ver mi progreso" before
  subjects load); `verify.sh` keeps per-gate logs; T016 gate failure not
  reproduced ([RCA-003](../rca/RCA-003-intermittent-gate-and-browser-failures.md)).
- **T019** — dashboard "Practicar / Repasar este objetivo" presets the
  practice form (one objective, Intermedia, 5); explicit start; "Necesita
  refuerzo" highlighted ([ADR-018](../adr/ADR-018-dashboard-driven-practice.md)).
- **T020** — Producción escrita foundation: verbatim rubric, five levels
  mapped to EE01–EE20, exercise and human-evaluation contracts, `writing`
  schema, separate progress; no generation or UI
  ([ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)).

### Current State

- `main` committed and pushed to `origin/main`; working tree clean; no task
  locks; no running servers or generation jobs.
- Generation: free models only (paid disabled), checker 1.6.0, prompts
  generation 1.3.0 / rubric 1.1.0, generation limit 4000 tokens, daily
  request budget 1000 (`.env`), 5 questions per practice, 80 calls per set,
  3 requests per slot, concurrency 2.
- Student app: configure → bank composition → (job for missing slots) →
  one question at a time → summary; exit with cancellation; dashboard.
- PostgreSQL tables: `curriculum.*`, `llm.usage_record`,
  `generation.question_attempt`, `generation.practice_set`,
  `generation.practice_set_item`, `generation.bank_revalidation`,
  `practice.session`, `practice.item`, `practice.answer`.
- Tests: 408 passing; browser (mocked) 259/259 and live 14/14 on
  `mentor_pro_test`; ACE gate
  `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. Optional: review the 14 quarantined sessions; reclassify with a new
   audit reference if any were real student practice.
2. Restore a generation model fallback: only Nemotron 3 Ultra generates
   (MiniMax M3.1 Flash unlisted, Super VL excluded). Add another free text
   model to `OPENROUTER_FREE_MODELS` or evaluate the reasoning-effort setting
   live (small sample).
3. Receive and plan the next Product Owner task (ADR first).
4. Follow-up from T018: shared test-database job interference
   (`fail_interrupted()` fails every active session on app start); see
   `docs/progress/task_T018_result.md`.
5. Optional quality work: typed property checks (divisibility, parity) so
   property questions become provable; human spot checks of rubric scores.

### Blockers/Issues

- Student dashboard now reflects 5 answers (Ciencias C06). Backup before
  T017: `%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T017_2026-10-24.dump`;
  rollback: `scripts/dev/classify_sessions.py --rollback T017-2026-10-24`.
- **No generation fallback model** (see Next Steps 2); free models also
  truncate or return 502 often.
- Rubric and blind solve come from free models; bank quality inherits them.
- Property detection (T009) is keyword-based; unusual phrasing can slip
  through.
- `scripts/pubs/check_lane.py` from the session-start prompt does not exist.
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Edge cannot start under automation; browser tests use installed Chrome.
- Docker not installed; `docker-compose.yml` untested.
- Student first name in pushed commit `42adbe7`; rewrite needs approval.
- Remote branch `origin/copilot/clean-repository` (merged PR #1) remains.
- Framework markdown lint debt (`docs/TODO-markdown-lint.md`).

### Notes

- App: `.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
  (reads `.env`). Restart after code changes. A server start marks
  `queued`/`running` practices of the shared database as interrupted.
- Browser tests: `.venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR`
  (mocked; seeds `e2e-bank-…` items) and `--live` (real OpenRouter; generate,
  repeat from the test bank, mixed). Both run only on `TEST_DATABASE_URL`;
  live OpenRouter usage is recorded in the test database.
- Live helpers: `scripts/dev/generate_examples.py`,
  `scripts/dev/generate_practice_set.py`; connectivity
  `.venv/Scripts/python.exe -m app.llm.connectivity`.
- Gate: `bash .ace/scripts/verify.sh` (tests need `mentor_pro_test`); logs per
  run in `.ace/logs/verify/<run>/`. Check
  the `VERIFY_RESULT` line exactly before committing.
- Key settings: `OPENROUTER_GENERATION_MAX_TOKENS`,
  `OPENROUTER_GENERATION_EXCLUDED_MODELS`,
  `OPENROUTER_GENERATION_REASONING_EFFORT`, `QUESTION_GENERATION_CONCURRENCY`,
  `MENTOR_PRO_SET_MAX_*`, `MENTOR_PRO_MASTERY_*` (see `.env.example`).
- Tracker IDs `^T[0-9]{3}$`; PO labels kept in task names and notes.
- Never expose keys or student data; `approved_baseline` items are not
  official MEP wording; learning statuses are not official MEP levels.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-003)
