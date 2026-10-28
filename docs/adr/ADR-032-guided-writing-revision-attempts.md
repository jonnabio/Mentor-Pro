# ADR-032: Guided Writing Revision with Student Attempts

> **Status:** Proposed — architecture principles approved by Product Owner 2026-10-28; physical schema, migration and implementation NOT authorized
> **Date:** 2026-10-28
> **Scope:** Producción escrita L1–L4; separate from editorial exercise revisions
> **First proposed ACE task:** T036 (planning only; tracker registration at implementation approval)

## Context and learning objective

A student can write, autosave, submit once, receive a completed human tutor evaluation and read feedback (ADRs 019, 021, 024, 025, 028 and 031). The next learning objective is to apply that feedback in a guided second attempt, obtain new human feedback and compare matched rubric criteria. Preserve the first submission and its completed evaluation as evidence. Real-user production acceptance of T032/T033 is **pending**; no evidence here closes it.

## Verified current implementation

- `app/writing/store.py`: `writing.draft.exercise_id` is the primary key; `uq_submission_exercise` permits only one submission per exercise; `uq_evaluation_submission` permits one evaluation per submission. `writing.submission` has stable `submission_id`, `exercise_revision`, typed `text_es` and L4 `sections`; `writing.draft` has `client_seq`, `exercise_revision` and `sections`.
- `app/writing/routes.py`: student exercise detail and `PUT /exercises/{exercise_id}/draft`, `POST /exercises/{exercise_id}/submit` work at exercise granularity; they cannot yet select an attempt.
- `app/writing/tutor.py`: queue, submission detail and evaluation operate by `submission_id` (suitable identity for multiple attempts); `app/tutor_main.py` retains ADR-031 separate secured service.
- `app/writing/progress.py`: completed evaluations are aggregated by rubric criterion (latest/best) and activity counts submission rows; it does not compare attempt pairs.
- `writing.exercise_revision` describes **editorial exercise content revisions**, not student attempts. `writing.generation_attempt` refers to model generation, also unrelated.

## Decision proposed for physical implementation

Create `writing.student_attempt` (name deliberately distinct from `generation_attempt`) with:
- `attempt_id TEXT PRIMARY KEY` (generated opaque unique identifier)
- `exercise_id TEXT NOT NULL REFERENCES writing.exercise(exercise_id)`
- `attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1)`
- `previous_attempt_id TEXT NULL` referencing an earlier attempt for the same exercise, enforced transactionally (and with a composite FK if practical)
- `exercise_revision INTEGER NOT NULL` pinned at attempt creation, never silently upgraded
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `UNIQUE(exercise_id, attempt_number)`, plus indexing for history lookup.

Add `attempt_id` foreign keys to `writing.draft` and `writing.submission`. Backfill attempt 1 for every pre-existing draft or submission, keyed by exercise, preserving existing draft, submission and evaluation IDs, texts, sections, revisions, timestamps, scores, references and feedback. For an exercise with a submitted record, the pinned revision comes from that submission; otherwise use the draft revision if available, or resolve current exercise revision without editing the exercise.

After validated backfill, make `attempt_id` non-null for active student rows, replace the old draft `exercise_id` PK with a primary key on `attempt_id` (retain exercise_id FK for compatibility if useful), replace `uq_submission_exercise` with `UNIQUE(attempt_id)`, retain `uq_evaluation_submission` and existing evaluation/criterion keys. Add consistency constraints or transactional checks that each draft/submission's exercise matches its attempt. Keep existing submission IDs; do not introduce an alternative evaluation identity. A second attempt has its own draft, submission and evaluation; the first stays immutable.

**Migration mechanism decision deferred:** `WritingStore.__init__` currently executes `SCHEMA_SQL` during application startup under `bootstrap:writing` advisory lock. Do not place destructive index/PK changes into unguarded startup DDL. Implement an explicitly versioned, separately invoked migration with an audit/check table or equivalent controlled revision state. Startup schema initialization must remain safe on both fresh and migrated test databases; no implicit production migration during app startup.

## Lifecycle and workflows

- Student may create attempt 2 only after attempt 1 has a **completed** human evaluation. First increment allows at most two attempts; schema is future-safe for more. Reject a second in-progress revision or concurrent duplicates; concurrent creation returns the already-existing attempt 2.
- The revision draft is initialized once from the previous submitted `text_es` and L4 `sections`, not from a live or stale draft. For L1 use the submitted correction, **not** the exercise's original source text. For L4 copy `plan`, `introduction`, `development_1`, `development_2`, `conclusion` intact; retain both assembled text and section structure.
- On reload, select the existing draft attempt and use its `client_seq`; the copy operation must never reset a saved revision. Per-attempt ordered autosave rejects stale sequence numbers and a submitted attempt is frozen. A retry of submit returns the same submission, guarded by a stable request ID, row locking and unique attempt constraint.
- Tutor queue labels revision attempt number, shows prior response and **student-visible completed feedback** in context, and evaluates the current submission with the existing rubric/contract, without changing the prior evaluation. Tutor-only reference correction stays on the tutor service.
- Student labels: `Mejorar mi respuesta`, `Mi primera respuesta`, `Comentarios del tutor`, `Mi nueva versión`, `Entregar mi mejora`. Keep unchanged exercise selection and editor controls; do not introduce AI grading or new infrastructure.
- For editorial revisions after attempt 1, continue pinning the original answered exercise revision for attempt 2; if current eligibility or revision policy would prohibit this, fail closed and resolve as an explicit product decision rather than silently change the task.

## API compatibility approach

Continue supporting existing exercise endpoints for attempt 1 and introduce attempt-scoped endpoints (exact paths/response shape to be decided in API review). New writes must identify the target attempt; never infer the newest attempt for a write in a way that could redirect an in-flight autosave. Keep existing student responses compatible with first-attempt users. Tutor APIs remain behind ADR-031's dedicated service, SSH tunnel, exact-host checks and token; student endpoints cannot return tutor-only references.

## Progress semantics

Maintain ADR-025's criterion-based coverage, latest/best and dimension indicators based **only on completed evaluations**; distinguish attempts from unique exercises and avoid treating attempts as additional coverage. Add an exercise-level comparison:
- first: completed attempt 1;
- latest: most recently **completed** evaluation;
- best: highest observed points **per comparable criterion**, not an invented total;
- improvement: latest minus first for criteria scored in both using the same official rubric ID/checksum and a comparable assessment scope. Show changes as `+1 punto en EE07`, not an official grade.
A revision pending tutor review contributes to pending activity, but does not replace latest evaluated or count as improvement. Exclude not-evaluable and missing scores from numeric comparisons; distinguish submissions count, distinct exercises and completed evaluations. Retain the existing dashboard for unrelated multiple-choice objectives.

## Alternatives considered

1. Overwrite/reopen original submission/evaluation: rejected; erases learning evidence and violates ADR-024.
2. Reset or reuse one draft per exercise: rejected; stale saves can overwrite revision, lifecycle ambiguous.
3. Clone exercise for each attempt: rejected; confuses editorial content, eligibility, activity and scores.
4. Separate attempt identity with one submission per attempt: **preferred**; smallest coherent additive structure.
5. New standalone service/identity system: rejected as excessive for single-student application.

## Security and boundaries

Preserve ADR-031 unchanged: only the tutor service on loopback port 8081, via SSH tunnel and strong tutor token, may write evaluations. No additional network ports, secrets, accounts or containers. Student responses never include tutor-only reference correction, evaluation drafts, or hidden rubric metadata. Use parameterized SQL, bounded input sizes, validated attempt ownership/exercise consistency, and no student text in routine logs. No L5 or bank regeneration.

## Migration, validation and rollback (proposal only)

1. After separate implementation approval, capture a fresh verified PostgreSQL backup with restore rehearsal in isolation; preserve `mentor-pro_postgres_data`. Do not use `docker compose down -v`.
2. Test versioned migration against empty `mentor_pro_test`, historical single-attempt fixtures, and an isolated restored representative backup (never a disposable production database).
3. Record pre/post counts and stable IDs/checksums for draft, submission, evaluation and criterion_score, plus L1/L4 sections and timestamps. Backfill deterministically and idempotently under a transaction/advisory lock, fail on anomalies, and verify constraints before removing the exercise-level unique index.
4. Validate startup on migrated database and fresh database. Keep old production app/image and volume untouched while preparing the release.
5. A downgrade after new attempts are created **cannot safely restore the old unique-per-exercise schema**. Preferred rollback is restore the pre-migration backup in a separately approved maintenance window, after exporting and preserving post-migration attempts for recovery; do not silently delete second attempts. Document the forward-fix option and recovery limits before deployment.

## Acceptance criteria

- Existing completed submissions, rubric scores, comments and IDs remain byte-for-byte equivalent after migration.
- Existing single-submission users retain functional access, and legacy requests cannot overwrite original or revision data.
- Attempt 2 may start only after completed evaluation; two simultaneous starts yield one attempt.
- L1 starts from student's submitted correction; L4 preserves all five sections and assembled text.
- Save/reload, ordered autosave, stale-write protection, submit idempotency, restart persistence.
- Tutor can distinguish and review revision; scoring attaches only to new submission, historical evaluation remains immutable.
- Dashboard first/latest/best and matched-criterion improvements are correct; pending revision is not improvement.
- Student/tutor isolation, token enforcement, generated bank/eligibility safeguards, multiple-choice and full ACE gates pass.
- Production real-user acceptance is recorded only on observed student/parent evidence.

## Approval boundary

The Product Owner approved the architecture principles, **not** migration execution, production changes, deployment or release. T036 is a proposed first implementation task, contingent on separate approval of physical migration/API details. Maintenance T034/T035 and CI trigger for `dev` remain separate.
