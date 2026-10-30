# ADR-032: Guided Writing Revision with Student Attempts

> **Status:** Accepted for T036 (data foundation) and T037/T038 (student revision API, tutor re-evaluation; amendments approved 2026-10-28); principles approved 2026-10-28; T036 merged to `dev`; production migration, deployment, GHCR publication, merge to `main` and infrastructure changes NOT authorized
> **Date:** 2026-10-28
> **Scope:** Producción escrita L1–L4; separate from editorial exercise revisions
> **First ACE task:** T036 (registered 2026-10-28, data foundation only)

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

## T036 implementation (physical design, 2026-10-28)

Implemented on `feature/T036-guided-writing-revision-design`; see
[T036 result](../progress/task_T036_result.md). Within the decision above.

Product Owner decisions (2026-10-28):

1. **APPROVED** — the application refuses to start on an unmigrated
   writing schema.
2. **APPROVED** — `uq_submission_exercise` replaced by attempt-level
   uniqueness.
3. **APPROVED** — attempt 1 keeps ADR-023 editorial revision behaviour
   until submission; later attempts stay pinned to the revision they
   improve.
4. **CONDITIONALLY APPROVED** — merge PR #11 into `dev` after review and
   CI gates pass.
5. **NOT AUTHORIZED** — production migration, deployment, merge to `main`
   or production infrastructure changes.

Schema (`app/writing/migrations.py`, migration `0001_student_attempts`):

- `writing.student_attempt` as proposed, with `uq_attempt_exercise_number
  (exercise_id, attempt_number)`, `uq_attempt_exercise (attempt_id,
  exercise_id)` (target of the composite FKs), `uq_attempt_previous`
  (linear chain, no fork), `ck_attempt_first_has_no_previous` and
  `fk_attempt_previous_same_exercise (previous_attempt_id, exercise_id)`.
  "Predecessor is the immediately earlier attempt" is enforced in the store
  transaction (an FK cannot express `attempt_number - 1`) and tested.
- `writing.draft`: `attempt_id NOT NULL`, primary key `attempt_id`;
  `exercise_id` kept (FK to the exercise, indexed);
  `fk_draft_attempt (attempt_id, exercise_id)`.
- `writing.submission`: `attempt_id NOT NULL`, `uq_submission_attempt`
  replaces `uq_submission_exercise`; `fk_submission_attempt (attempt_id,
  exercise_id)`. `uq_evaluation_submission`, evaluation and criterion score
  keys unchanged; no new evaluation identity.
- Attempt IDs: `ATT-<exercise suffix>-<n>-<8 hex>`, random for new
  attempts, derived from `md5(exercise_id)` for the backfill (deterministic).
- Backfill revision: submission, else draft, else current (as above);
  `created_at` is the earliest recorded timestamp of that work.
- Ledger `writing.schema_migration (migration_id, applied_at, mode,
  report)`; reports hold counts and MD5 digests, never student text.

Migration mechanism (decides the deferred point above):

- `python -m app.writing.migrate status | apply [--dry-run] | rollback`.
  One transaction under the `bootstrap:writing` advisory lock with the
  student tables locked exclusively; preconditions (one submission per
  exercise, no orphans); digests of `draft`, `submission`, `evaluation`,
  `criterion_score` (all columns but `attempt_id`) must match before and
  after; any failure rolls everything back. Re-running reports
  `already_applied`.
- `rollback` restores the old schema only while no attempt above 1 exists;
  otherwise refused (restore the pre-migration backup, as above).
- **PO 1 — startup (approved):** `WritingStore` never migrates existing
  tables. A database without writing tables is created directly at the
  current version (tests, CI smoke, new installs). The store is created
  lazily, so both apps check the schema at startup
  (`WritingService.check_schema()` in the FastAPI lifespan; also before
  uvicorn in `python -m app.tutor_main`, exit 78): an unmigrated schema
  (`legacy`) or a drifted one (below) **refuses startup**
  (`SchemaMigrationRequired`). An unreachable or unconfigured database is
  left to the first request (503 `database_unavailable`, unchanged; CI
  smoke tests run without a database). If the schema changes after
  startup, writing requests answer 503 `schema_migration_required`. A
  future release must run the migration before starting the new image
  (runbook section K). The old image keeps working on the unmigrated
  database.
- **PO 2 — `uq_submission_exercise` (approved)** is no longer created by startup DDL
  (it would otherwise be recreated after the migration on every boot).

Compatibility and revision pinning:

- Exercise-level store methods and all current routes address attempt 1
  only; they never select or write a later attempt (tested: an old client
  cannot write into an open revision). Attempt-scoped
  `save_attempt_draft`, `submit_attempt` and `start_revision` exist in the
  store only; no route exposes them (T037).
- **PO 3 — revision pinning (approved):** attempt 1 keeps today's behaviour (ADR-023):
  until submitted it follows the latest editorial revision and its
  `exercise_revision` is updated with each save; at submission it is fixed.
  A revision attempt is pinned at creation to the revision of the
  submission it revises and is never upgraded. Pinning attempt 1 at its
  creation would change the current student experience.

### Old image against a migrated database (incompatibility)

Observed by running the pre-T036 `store.py` (`origin/dev` `1f2fcfd`) on
migrated `mentor_pro_test` databases:

| Situation | Old image behaviour |
| --- | --- |
| Only attempt 1 exists | Starts; its startup DDL **recreates `uq_submission_exercise`**; reads, listing, tutor queue and progress work; saving an existing draft fails (`ON CONFLICT (exercise_id)` has no matching constraint); a first submission fails (`attempt_id` NOT NULL); retries of existing submissions return them |
| A revision submission exists | Startup DDL fails (`UniqueViolation` creating `uq_submission_exercise`): every writing request fails; its listing would duplicate rows per attempt |
| New image after the old one ran | The recreated index would block revision submissions; the new code reports state `drifted` and refuses to start until `python -m app.writing.migrate repair` drops that index (digests unchanged) |

Rules: never start a pre-T036 image on a migrated database. To go back,
first `migrate rollback` with the new image (possible only while no
revision attempt exists), then start the old image; otherwise restore the
pre-migration backup (above). No student data is lost by the failures
above (writes are refused, nothing is overwritten), but student writing is
unavailable while it lasts.

## Lifecycle and workflows

- Student may create attempt 2 only after attempt 1 has a **completed** human evaluation. First increment allows at most two attempts; schema is future-safe for more. Reject a second in-progress revision or concurrent duplicates; concurrent creation returns the already-existing attempt 2.
- The revision draft is initialized once from the previous submitted `text_es` and L4 `sections`, not from a live or stale draft. For L1 use the submitted correction, **not** the exercise's original source text. For L4 copy `plan`, `introduction`, `development_1`, `development_2`, `conclusion` intact; retain both assembled text and section structure.
- On reload, select the existing draft attempt and use its `client_seq`; the copy operation must never reset a saved revision. Per-attempt ordered autosave rejects stale sequence numbers and a submitted attempt is frozen. A retry of submit returns the same submission, guarded by a stable request ID, row locking and unique attempt constraint.
- Tutor queue labels revision attempt number, shows prior response and **student-visible completed feedback** in context, and evaluates the current submission with the existing rubric/contract, without changing the prior evaluation. Tutor-only reference correction stays on the tutor service.
- Student labels: `Mejorar mi respuesta`, `Mi primera respuesta`, `Comentarios del tutor`, `Mi nueva versión`, `Entregar mi mejora`. Keep unchanged exercise selection and editor controls; do not introduce AI grading or new infrastructure.
- For editorial revisions after attempt 1, continue pinning the original answered exercise revision for attempt 2; if current eligibility or revision policy would prohibit this, fail closed and resolve as an explicit product decision rather than silently change the task.

## API compatibility approach

Continue supporting existing exercise endpoints for attempt 1 and introduce attempt-scoped endpoints (exact paths/response shape to be decided in API review). New writes must identify the target attempt; never infer the newest attempt for a write in a way that could redirect an in-flight autosave. Keep existing student responses compatible with first-attempt users. Tutor APIs remain behind ADR-031's dedicated service, SSH tunnel, exact-host checks and token; student endpoints cannot return tutor-only references.

### T037 amendment: student revision API (PO approved 2026-10-28)

Approved as proposed in
[the T037 plan](../planning/2026-10-28-T037-student-revision-plan.md),
student service only, additive:

| Method and path | Behaviour |
| --- | --- |
| `GET /api/writing/exercises/{id}` | Existing fields unchanged (attempt 1). New `revision_attempt`: `{available, attempt}`; `attempt` is `null` or `{attempt_id, attempt_number, editable, draft, submission, feedback}` |
| `POST /api/writing/exercises/{id}/revision` | 201 created, 200 existing (same `attempt_id`); 409 `revision_not_allowed` (Spanish reason); 409 `exercise_unavailable` when quarantined |
| `PUT /api/writing/attempts/{attempt_id}/draft` | Same body, `client_seq` ordering and responses as the exercise draft route; 409 `already_submitted` |
| `POST /api/writing/attempts/{attempt_id}/submit` | Same validation as the exercise route; a retry returns the first submission |

- The new block is named `revision_attempt`, not `revision` as in the plan:
  the exercise response already has `revision` (the editorial revision
  number, ADR-023), and renaming it would break existing clients.
- Writes always name the `attempt_id`. Attempt routes refuse attempt 1
  (409 `attempt_routes_are_for_revisions`); malformed IDs 422, unknown 404.
- **Quarantine (PO decision 3):** no revision starts, and an open revision
  cannot be saved or submitted, while the exercise is quarantined (409
  `exercise_unavailable`; `available` false, `editable` false). Historical
  submissions and evaluations stay readable.
- **Release (PO decision 4):** T037 and T038 are developed and verified
  independently and released together; T037 is never deployed alone.
  Without T038 the tutor sees a revision as an ordinary submission, and
  the student page does not yet show the review of the improved version.

### T038 amendment: tutor re-evaluation (PO approved 2026-10-28)

Tutor service only (ADR-031 boundary, token and loopback checks
unchanged); additive fields, no new route:

| Endpoint | Addition |
| --- | --- |
| `GET /api/tutor/queue` | `attempt_number` per submission; a revision is labelled "Mejora (versión 2)" |
| `GET /api/tutor/submissions/{id}` | `attempt_number`; `previous`: `null` for attempt 1, otherwise the previous attempt's `submission_id`, `submitted_at`, `student_text`, `sections` and its completed `evaluation` (scores with official descriptors, feedback) |
| `PUT /api/tutor/submissions/{id}/evaluation` | unchanged: the evaluation attaches to the revision submission only; the previous completed evaluation stays locked (409) |

- The revision is scored with the same rubric and the same pinned exercise
  revision as the first attempt.
- The student sees the completed review of the improved version through
  the existing feedback view (`revision_attempt.attempt.feedback`, same
  shape as `feedback`), below "Mi nueva versión".
- Progress comparison stays in T039. **Before release** (PO): T039 must
  stop repeated attempts from being counted as additional exercises.

### T039 amendment: progress and revision comparison (PO approved 2026-10-29)

Plan: [T039](../planning/2026-10-29-T039-writing-progress-plan.md).
Additive only; no schema change:

- `GET /api/writing/progress`: existing fields keep their meaning
  (submissions and evaluations). New: `activity.exercises_submitted`,
  `exercises_evaluated`, `first_attempts`, `improvements`,
  `improvements_pending`; per level `exercises_submitted`,
  `exercises_evaluated`; per criterion `exercises`,
  `improvements_pending`; `revisions` (one comparison per revised
  exercise). The dashboard shows exercises, counted once, and
  improvements apart.
- Comparison (`progress.compare`): a change per criterion only when
  both completed evaluations score it with the same rubric ID and
  checksum and the same pinned exercise revision; otherwise "No
  comparable". Not-evaluable and missing scores have no number; a
  pending, in-progress or voided improvement shows "Tu mejora está
  pendiente de revisión" and no change. No total, average or grade.
  Each row carries the official Spanish criterion statement.
- Student: "Mis mejoras" in the writing progress and
  `revision_attempt.attempt.comparison` on the exercise page; tutor:
  `comparison` in `GET /api/tutor/submissions/{id}` once both
  evaluations are completed (tutor service, ADR-031 unchanged).
- Attempt order in progress comes from the submission order per
  exercise, so the same read works on the legacy and migrated schemas
  (historical progress unchanged by migration `0001`).

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
