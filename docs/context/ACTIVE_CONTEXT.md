# Active Context: Session Handoff 2026-10-25

## Session Metadata

- **Last Updated:** 2026-10-25
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING
- **Session span:** 2026-10-22 to 2026-10-25 (T006 completion through T028)

## Current Objective

No task in progress. Wait for the next Product Owner task; plan it with an
ADR first. Do not start L4/L5 generation, 10–30 question sets or new
features without approval.

## Handoff Summary

### Completed

Baseline before this session: ACE 2.7.0 reset, T001 skills and checker
(ADR-005), T002 baseline `PNE2026-SUM-v1.0` (ADR-006), T003 PostgreSQL
catalog (ADR-007), T004 configuration API and UI (ADR-008), T005 OpenRouter
client and budgets (ADR-009).

This session (reports in `docs/progress/task_T0xx_result.md`):

Multiple choice and learning data

- **T006** — single grounded question for M02, C01, EL01, ES01
  ([ADR-010](../adr/ADR-010-single-question-generation.md)).
- **T007** — validated 5-question practice sets, checker 1.5.0
  ([ADR-011](../adr/ADR-011-validated-practice-sets.md)).
- **T008** — bounded parallel slots, atomic `BudgetGate`
  ([ADR-012](../adr/ADR-012-controlled-parallel-generation.md)).
- **T009** — checker 1.6.0 maths proofs; RCA-002 and guard.
- **T010** — student practice in the web page; `practice_e2e.py`
  ([ADR-013](../adr/ADR-013-student-practice-sessions.md)).
- **T011–T012** — generation token limit 4000, truncation detection, menu
  navigation, Super VL excluded from generation.
- **T013** — validated question bank
  ([ADR-014](../adr/ADR-014-validated-question-bank.md)).
- **T014** — learning dashboard, six statuses
  ([ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)).
- **T015** — "Salir de la práctica" with confirmation.
- **T016** (PO T014.1) — automation uses only `mentor_pro_test`
  ([ADR-016](../adr/ADR-016-test-database-isolation.md)).
- **T017** — historical test sessions classified out of learning metrics
  ([ADR-017](../adr/ADR-017-session-classification.md)).
- **T018** — dashboard click race fixed; gate keeps per-gate logs
  ([RCA-003](../rca/RCA-003-intermittent-gate-and-browser-failures.md)).
- **T019** — "Practicar / Repasar este objetivo" from the dashboard
  ([ADR-018](../adr/ADR-018-dashboard-driven-practice.md)).

Producción escrita (Español, written rubric EE01–EE20)

- **T020** — verbatim MEP 2026 rubric, five levels, contracts, `writing`
  schema ([ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)).
- **T021** — OpenRouter generation of one exercise (L2)
  ([ADR-020](../adr/ADR-020-writing-exercise-generation.md)).
- **T022** — student writing screen: drafts, one submission
  ([ADR-021](../adr/ADR-021-student-writing-practice.md)).
- **T023** — Nivel 1 correction exercises with tutor-only references
  ([ADR-022](../adr/ADR-022-nivel-1-correction-exercises.md)).
- **T024** — L1 editor prefilled with the text; versioned editorial
  revisions; checks W13–W15
  ([ADR-023](../adr/ADR-023-l1-editor-and-editorial-revisions.md)).
- **T025** — L2 and L3 inventory; checks W13–W18 for composed paragraphs;
  ADR-020 amended.
- **T026** — tutor review at `/tutor` with official descriptors, partial
  save, single completion; student feedback
  ([ADR-024](../adr/ADR-024-tutor-writing-evaluation.md)).
- **T027** — Producción escrita as the fifth tab of "Mi progreso":
  activity, coverage, per-criterion latest/best, dimension averages from
  evaluated criteria only
  ([ADR-025](../adr/ADR-025-writing-learning-dashboard.md)).
- **T028** — Nivel 4 guided composition: one real L4 exercise, five-stage
  editor with section drafts, tutor review with optional EE07–EE18
  ([ADR-026](../adr/ADR-026-guided-composition-l4.md)); writing reviews by
  the generator are refused
  ([RCA-004](../rca/RCA-004-writing-review-not-independent.md)).

### Current State

- `main` committed and pushed to `origin/main`; working tree clean; no task
  in progress, no lock files; no server or generation job left running.
- Multiple choice: free models only (paid disabled), checker 1.6.0, prompts
  generation 1.3.0 / rubric 1.1.0, generation limit 4000 tokens, daily
  request budget 1000 (`.env`), 5 questions per practice, concurrency 2.
- Student database: 381 multiple-choice answers (dashboard counts only the
  2 `student` sessions, T017); writing inventory L1 3, L2 3, L3 3, L4 2 (L5
  none in the real database); 0 writing drafts, submissions and
  evaluations.
- Writing app: Producción escrita card on the main menu → levels →
  exercises → editor (L1 prefilled with the text; L2–L5 empty) → one
  submission → "Pendiente de revisión del tutor" → tutor review at `/tutor`
  → "Revisado por el tutor" with scores and feedback. Tutor-only
  references in `writing.reference_correction` and
  `writing.exercise_revision.reference`, never in student responses.
- Writing generation: prompts `writing-1.3` (composed, L4 plan) and
  `writing-edit-1.1` (L1); checks W01–W19; correction exercises use 8000
  output tokens; seeding commands generate only missing exercises.
- PostgreSQL schemas: `curriculum`, `llm`, `generation`, `practice`
  (`session_classification`), `writing` (`exercise`, `exercise_revision`,
  `reference_correction`, `generation_attempt`, `draft`, `submission`,
  `evaluation`, `criterion_score`).
- Tests: 507 passing; browser (mocked, `mentor_pro_test`) 433/433; ACE gate
  `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. Receive and plan the next Product Owner task (ADR first). Candidates
   named so far: L5 examination simulation, reopening or correcting a
   completed evaluation. Decide on the four self-reviewed exercises
   (RCA-004): `PE-L4-uso-responsable-redes-f9acfc` and the three T023 L1.
2. Restore a generation fallback model: only
   `nvidia/nemotron-3-ultra-550b-a55b:free` generates and it often truncates
   (writing L1 needed several seeding runs). Add another free text model to
   `OPENROUTER_FREE_MODELS` and test on a small sample.
3. Run one live L1 generation with prompt `writing-edit-1.1` and one L2/L3
   with `writing-1.2` to confirm the T024/T025 rules on new output.
4. Follow-up from T018: `fail_interrupted()` fails every queued or running
   practice in the shared test database on app start.
5. Investigate the suite slowdown (about 42 s → about 160–200 s since T020;
   about 110 ms per PostgreSQL connection).

### Blockers/Issues

- **Single generating model** (Next Steps 2); free models truncate or
  return 502 often; review quality inherits free models (missed one
  ambiguity in T023 and one paragraph-count error in T025, both fixed
  manually).
- Writing checks are partly keyword-based (W04, W13 voseo list, W16 scope);
  instructions of one paragraph type share the same structure.
- Tutor boundary is a local code, not authentication (ADR-024); a completed
  evaluation cannot be reopened.
- The unexplained T016 `gate=test` failure was never reproduced
  (RCA-003); full logs are kept if it recurs.
- 14 quarantined sessions await an optional human review (T017). Backup:
  `%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T017_2026-10-24.dump`;
  rollback `scripts/dev/classify_sessions.py --rollback T017-2026-10-24`.
- Property detection (T009) is keyword-based.
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Edge cannot start under automation; browser tests use installed Chrome.
- Docker not installed; `docker-compose.yml` untested.
- Student first name in pushed commit `42adbe7`; rewrite needs approval.
- Remote branch `origin/copilot/clean-repository` (merged PR #1) remains.
- Framework markdown lint debt (`docs/TODO-markdown-lint.md`).

### Notes

- App: `.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
  (student database; reads `.env`). Restart after code changes. A server
  start marks `queued`/`running` practices as interrupted.
- Tutor review: `http://127.0.0.1:8000/tutor`, code `MENTOR_PRO_TUTOR_TOKEN`
  in the local `.env` (git-ignored; empty disables review).
- Browser tests: `.venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR`
  (mocked; includes writing and tutor scenarios; resets the test
  database's `writing` schema) and `--live`. Both use only
  `TEST_DATABASE_URL`. Never create artificial submissions in the student
  database; delete any acceptance-test draft created live.
- Writing commands: `scripts/dev/seed_writing_l1.py`,
  `scripts/dev/seed_writing_l2_l3.py` (`--inventory` read-only),
  `scripts/dev/revise_writing_l1.py [--specs FILE] [--dry-run]`,
  `scripts/dev/generate_writing_exercise.py`.
- Other live helpers: `generate_examples.py`, `generate_practice_set.py`,
  `.venv/Scripts/python.exe -m app.llm.connectivity`.
- Gate: `bash .ace/scripts/verify.sh`; check its exit code (not a piped
  `tail`) before committing; logs in `.ace/logs/verify/<run>/`.
- Key settings: `OPENROUTER_GENERATION_MAX_TOKENS`,
  `OPENROUTER_GENERATION_EXCLUDED_MODELS`,
  `OPENROUTER_GENERATION_REASONING_EFFORT`, `QUESTION_GENERATION_CONCURRENCY`,
  `MENTOR_PRO_SET_MAX_*`, `MENTOR_PRO_MASTERY_*`, `MENTOR_PRO_TUTOR_TOKEN`
  (see `.env.example`).
- Tracker IDs `^T[0-9]{3}$`; PO labels kept in task names and notes.
- Never expose keys, student data or tutor references; never put the
  student's name in code, tests or commits; `approved_baseline` items are
  not official MEP wording; learning statuses and writing indicators are
  not official MEP grades.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-026](../adr/ADR-026-guided-composition-l4.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-004)
