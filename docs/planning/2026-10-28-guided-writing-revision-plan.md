# Guided Writing Revision — Implementation Plan (Proposed)

> **Date:** 2026-10-28
> **Branch:** `feature/T036-guided-writing-revision-design` (docs only)
> **Status:** PLANNING — architecture principles approved; no code, migration or production action authorized
> **ADR:** [ADR-032](../adr/ADR-032-guided-writing-revision-attempts.md)
> **ACE:** Analyze → Discuss → Plan → Execute → Verify; `bash .ace/scripts/verify.sh` before code completion

## Current evidence

- `dev` ahead of released `main` by documentation-only commits at inspection; zero open PRs. No new ACE task registered/started yet.
- T032 and T033 verified and deployed; **real-user acceptance remains pending**. Do not mark accepted from automated tests or issue synthetic production records.
- Existing `writing.draft` PK = exercise_id; `uq_submission_exercise` = one submission per exercise; `uq_evaluation_submission` = one evaluation per submission. Editorial `writing.exercise_revision` must not be confused with student attempts.
- Existing Python startup bootstraps schema via `WritingStore.__init__`: migration must be explicit, never silently executed by app boot.
- ACE guards RCA-003 (UI handlers), RCA-004 (independent exercise review), RCA-005 (runtime image/CI); ADR-016 test DB isolation, ADR-028 autosave, ADR-031 tutor isolation.

## Precondition: production acceptance

Conduct the real student/parent end-to-end flow (open → draft → save → reload → submit → tutor pending → parent review through SSH tunnel → feedback → restart persistence). If not performed, keep acceptance pending; document first failure separately and prioritize its narrow repair. No synthetic acceptance and no production fixtures.

## Proposed incremental ACE task sequence

| ID | Increment | Dependency | Deliverable | Exit criterion |
| --- | --- | --- | --- | --- |
| T036 (proposed) | Data foundation | Physical design approval, acceptance blocker triage | Explicit versioned migration, attempt relations, backfill, stores, read-compatible API | Historical rows unchanged; attempts constrained; fresh and legacy fixtures pass |
| T037 (reserved, not registered) | Student revision | T036 verified | Start revision, existing L1–L4 editor, autosave and submit per attempt | Prior immutable; reload, duplicate, concurrency and L1/L4 tests pass |
| T038 (reserved) | Tutor re-evaluation | T037 verified | Queue context and evaluation for revision submission | Correct submission association, no prior changes, ADR-031 isolation pass |
| T039 (reserved) | Progress comparison | T038 verified | First/latest/best with matched-rubric improvements | Mathematically correct, pending ignored, no MC regression |

Reserve IDs only as a proposal; confirm tracker IDs at each later task registration. T034/T035 are separate maintenance, not prerequisites unless a proven blocker.

## T036 — detailed plan (NO EXECUTION YET)

1. **Inventory & invariants**: review `app/writing/store.py` SCHEMA_SQL and methods `exercises`, `draft`, `submission`, `save_draft`, `submit_typed`, `tutor_queue`, `progress_inputs`; review `routes.py`, `tutor.py`, `progress.py`, `tests/app/test_writing_*.py`, `app/static/app.js`. Capture query expectations and checksums of legacy fixtures.
2. **Migration contract**: explicitly version `writing.student_attempt`; add attempt FK to draft/submission; backfill attempt #1 once for every exercise with any draft or submission. Existing submission/evaluation/criterion_score IDs and payloads remain unchanged. Determine attempt revision from submission first, else draft, else current exercise revision; reject inconsistency rather than guess.
3. **Transactional ordering**: build attempt records and columns, backfill and validate all FK relationships, constrain NOT NULL, move draft PK to attempt_id, replace `uq_submission_exercise` with `UNIQUE(submission.attempt_id)`; maintain `uq_evaluation_submission`. Inspect indexes, lock durations, and app startup safety; do not rely on schema bootstrap for irreversible DDL.
4. **Store compatibility**: add attempt-aware retrieval/creation methods using transaction locking and stable idempotency, preserve old first-attempt routes during increment 1; no user-facing revision control until increment 2. Guard against a legacy write silently selecting attempt #2.
5. **Data verification**: backfill idempotency, partial failure rollback, row counts, ID invariance, timestamps, L4 JSON sections and L1 text unchanged. Test empty and populated DB, at least one draft-only row, submission-only, completed evaluation with scores, and mixed history.
6. **Safety & authorization**: all database mutation tests on `mentor_pro_test` only; no production data or secrets. ADR-031 tutor service unchanged. Check direct URL/attempt mismatch and input validation.
7. **Gate & review**: `bash .ace/scripts/verify.sh`, targeted writing tests, browser regression and multiple-choice tests; record actual results in `docs/progress/task_T036_result.md`. Feature branch → `dev` PR only after explicit implementation approval. No `main` merge or deployment without another authorization.

## Migration design sketch (NOT EXECUTABLE SQL)

```text
writing.exercise (unchanged)
  -> writing.student_attempt(attempt_id PK, exercise_id FK,
                             attempt_number, previous_attempt_id,
                             exercise_revision, created_at,
                             UNIQUE(exercise_id, attempt_number))
       -> writing.draft(attempt_id PK/FK, exercise_id legacy FK?,
                        text_es, sections, client_seq, exercise_revision)
       -> writing.submission(submission_id PK, attempt_id UNIQUE/FK,
                             exercise_id legacy FK?, exercise_revision,
                             text_es, sections, submitted_at)
            -> writing.evaluation(evaluation_id PK,
                                  submission_id UNIQUE/FK, rubric checksum)
                 -> writing.criterion_score(PK evaluation_id+criterion_code)
```

Draft submission-free attempts may exist. Completed submissions remain immutable. Constraints should prevent cross-exercise `attempt_id`/exercise mismatches; use composite FK if appropriate, otherwise enforce transactionally and test direct SQL misuse. Avoid rewriting historical evaluated payloads.

## Migration verification matrix

| Case | Expected |
| --- | --- |
| Empty schema | No attempt rows; fresh startup works |
| Existing draft only | One attempt #1, exact text/sections/client_seq |
| Existing submitted only | One attempt #1, same submission ID/revision |
| Completed evaluated submission | Unchanged evaluation ID/record, rubric SHA, scores/comments |
| Parallel revision creation | At most one attempt #2 |
| Stale draft update | Not applied to a newer version, cannot target previous attempt |
| Double submit | Same submission ID for same request/attempt |
| L1 | Previous corrected text retained for revision seed |
| L4 | Five structured sections and assembled text round-trip |
| Dashboard | Existing baseline totals/coverage unchanged by migration |
| Authorization | No tutor routes on student service; token and host checks preserved |
| Multiple choice | No changes to `practice.*` or its metrics |

## Rollback and release boundary

Before any future production migration: fresh verified backup and isolated restore rehearsal, operational window and PO approval. Test down migration only while there are no >1 attempts per exercise; once revisions exist, old uniqueness constraints cannot be restored without data loss. Stop and choose a forward fix or separately approved database restore after archiving new attempt records; never silently erase them. Preserve production volume and pinned image until a separately approved deployment.

## Pending decisions for implementation approval

- Confirm physical names and constraints (`student_attempt`, `attempt_id`, migration version tracking).
- Confirm pinning of original exercise revision and handling quarantined/edited exercises for a revision.
- Confirm compatibility contract for old exercise-scoped write endpoints.
- Confirm migration scheduling, backup/restore rehearsal, and rollback handling after real second attempts.
- Confirm approval to register T036 as pending in `docs/progress/tasks.json` and implement **only** data foundation.

## Unrelated maintenance

T034 flaky concurrent practice test; T035 short-token tutor exit status; CI pull requests targeting `dev`. Track independently.
