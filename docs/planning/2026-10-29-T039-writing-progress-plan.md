# T039 Plan: Writing Progress and Revision Comparison

- **Date:** 2026-10-29
- **Role:** Architect
- **Status:** PROPOSED for PO review. Implementation NOT authorized.
- **Decision record:** ADR-032 "Progress semantics" and T038 amendment
  ("T039 must stop repeated attempts from being counted as additional
  exercises"); ADR-025 (writing progress dashboard); ADR-019 (rubric
  scores only from completed human evaluations)
- **Builds on:** T036 (attempts), T037 (student revision), T038 (tutor
  re-evaluation); all merged into `dev`, none deployed
- **Release role:** required before the next production application
  release; T037 and T038 are released together with it

## Analyze

### What exists

- `GET /api/writing/progress` (student service) returns
  `progress.summary(*store.progress_inputs())`: `notice_es`, `criteria`
  (20 EE rows), `dimensions`, `coverage`, `activity`.
- `store.progress_inputs()` reads **every submission** (one per attempt
  since T036) with its evaluation status and scorable criteria, and the
  records of completed evaluations. It does not read `attempt_id`,
  `attempt_number` or `exercise_id`.
- A revision (attempt 2) is allowed only after attempt 1 is typed,
  submitted and has a completed evaluation; `MAX_ATTEMPTS = 2`; the
  revision pins the same exercise revision; its evaluation uses the same
  rubric (T038).
- The tutor detail (`GET /api/tutor/submissions/{id}`, tutor service)
  already shows `previous` with the attempt-1 evaluation (T038).
- The dashboard (`app/static/app.js`, "writing progress") shows
  `activity.submitted` as "entregados", `evaluations_completed`,
  `evaluations_pending`, per-level "evaluados · entregados", and per
  criterion latest, best, evaluation count and pending count.

### Defects with revisions (the release blocker)

| Field | Today with one revised exercise | Correct meaning |
| --- | --- | --- |
| `activity.submitted` | 2 ("2 entregados") | 1 exercise submitted |
| `activity.levels[].submitted` / `evaluated` | 2 / 2 | 1 / 1 |
| `activity.evaluations_completed` | 2 | 2 evaluations, 1 exercise evaluated: both must be explicit |
| `activity.evaluations_pending` | counts a pending revision as pending work | stays, but labelled as a pending improvement |
| `criteria[].evaluations` | counts both attempts | number of evaluations (correct), plus number of exercises |
| `criteria[].pending` | a pending revision marks criteria "pending" | already evaluated criteria stay "Evaluado"; the pending improvement is shown separately |
| `latest_points` / `best_points` | follow evaluation dates across attempts | correct per ADR-032 (latest **completed**), unchanged |
| `coverage`, `dimensions` | criterion-based, from latest points | unchanged |

Nothing shows the student the first-versus-improved comparison.

## Discuss (design)

### 1. Counting by exercise identity

`progress_inputs` adds `exercise_id`, `attempt_number`, `attempt_id`,
`exercise_revision` and the evaluation `rubric_id`/`rubric_sha256` to
each submission (one read-only query joining `writing.student_attempt`).
`progress.activity` then counts:

- `submitted`: **distinct exercises** with at least one submitted
  attempt (field kept; same value for every history without revisions);
- `levels[].submitted` / `levels[].evaluated`: distinct exercises per
  level with a submission / with a completed evaluation on any attempt;
- new `exercises_evaluated`: distinct exercises with a completed
  evaluation;
- new `submissions`: all submitted attempts; `first_attempts` and
  `improvements` (attempt ≥ 2) separately;
- `evaluations_completed` / `evaluations_pending`: unchanged meaning
  (evaluations), plus new `improvements_pending` (revision submissions
  waiting for the tutor).

A pending revision never makes an exercise "evaluated" or "pending" a
second time: an exercise counts once, in the best state reached
(evaluated if any attempt has a completed evaluation).

### 2. Criterion progress

- `latest_points`, `best_points`, `latest_at`: unchanged rules (latest
  completed evaluation by date; best observed points); a pending
  revision never replaces the latest evaluated value.
- `evaluations`: unchanged (completed scored evaluations); new
  `exercises`: distinct exercises with a scored evaluation of the
  criterion.
- `pending`: counts only **first attempts** waiting for the tutor; new
  `improvements_pending` per criterion for waiting revisions. The status
  rule stays (`evaluated` before `pending`).

### 3. First-versus-improved comparison (student)

New additive block `revisions` in `GET /api/writing/progress`, one entry
per exercise with an attempt 2, newest first:

```json
{"exercise_id": "...", "title_es": "...", "level": "L2",
 "first": {"submitted_at": "...", "evaluated_at": "..."},
 "improved": {"submitted_at": "...", "status": "pending|completed",
              "evaluated_at": null},
 "comparable": true,
 "criteria": [{"code": "EE07", "first_points": 2, "improved_points": 3,
               "change": 1, "change_es": "+1 punto en EE07"}],
 "summary_es": "Mejoraste en 2 criterios, igual en 3, bajaste en 0."}
```

Rules (ADR-032):

- a criterion is compared only when it is `scored` in **both** completed
  evaluations, with the same `rubric_id` and `rubric_sha256` and the same
  pinned exercise revision; otherwise it is listed without a change and
  marked "No comparable";
- `not_evaluable`, missing or pending scores are never numeric; no total,
  average or grade is computed; changes are shown as
  "+1 punto en EE07", never as an official grade;
- while the revision is pending: `status` "pending", no `criteria`
  changes, text "Tu mejora está pendiente de revisión";
- a voided evaluation counts as not completed.

Student page: a "Mis mejoras" section under the writing progress
dashboard (Spanish, same visual system), and on the exercise page the
existing `revision_attempt` feedback gets the same per-criterion change
list once both reviews are complete. No new route is needed for the
exercise page: the comparison is computed by the same function
(`progress.compare(first, improved)`).

### 4. Tutor comparison

`GET /api/tutor/submissions/{id}` (tutor service, ADR-031 boundary and
token unchanged) adds `comparison` when the submission is a revision and
both evaluations are completed: the same `progress.compare` output.
While the revision is being evaluated it is `null` (the tutor sees the
previous evaluation in `previous`, as today). Read-only; the evaluation
write path is unchanged; the student service never returns tutor-only
fields.

### 5. Backward compatibility

- No field is removed or renamed; types are unchanged. New fields are
  additive (`exercises_evaluated`, `submissions`, `first_attempts`,
  `improvements`, `improvements_pending`, `criteria[].exercises`,
  `criteria[].improvements_pending`, `revisions`, tutor `comparison`).
- **Semantic change** to existing fields: `activity.submitted`,
  `levels[].submitted`, `levels[].evaluated` and `criteria[].pending`
  count exercises / first attempts instead of submissions. For every
  history without revisions (all production data today: T037 is not
  deployed) the values are identical; a regression test asserts the
  whole `summary` output is byte-identical for single-attempt fixtures.
  The only client is the dashboard in this repository.
- Multiple-choice mastery and its dashboard are untouched.

### 6. Historical records and migration

- No schema change and no new migration: everything is derivable from
  `writing.student_attempt` (migration `0001`), `submission` and
  `evaluation`. The image keeps requiring schema `current 0001`
  (startup refuses `legacy`, T036), so the queries can rely on
  `attempt_id`.
- After the production migration every historical submission is
  attempt 1 (backfill), so historical progress is unchanged.
- Reads only; the progress endpoint writes nothing (existing test kept).

## Test plan

Unit (`progress`), store (synthetic `mentor_pro_test` only) and API:

1. single-attempt histories: `summary` identical to today's output
   (snapshot of the existing fixtures);
2. one exercise, attempt 1 evaluated, attempt 2 pending: 1 submitted, 1
   evaluated, 2 submissions, 1 improvement pending; criteria stay
   "Evaluado" with the attempt-1 points; comparison `pending`, no
   changes;
3. both evaluated: latest = attempt 2, best = max, `evaluations` 2,
   `exercises` 1; changes per criterion (+, 0, −);
4. `not_evaluable` in one attempt, missing score, different rubric
   checksum, voided evaluation: "No comparable", no number;
5. several exercises, mixed levels, one revised: per-level counts by
   exercise;
6. attempt 1 evaluated after attempt 2 started (date ordering), equal
   timestamps: deterministic by attempt number;
7. tutor detail: `comparison` null while pending, present when both
   completed; never on the student service; token and host checks
   unchanged;
8. dashboard and exercise page: "Mis mejoras", Spanish texts, no
   "calificación" wording (browser tests, existing harness);
9. read-only: no write during progress or tutor detail reads;
   multiple-choice dashboard unchanged.

ACE gate and PR CI as usual; no Docker change.

## Files (expected)

- modify: `app/writing/progress.py`, `app/writing/store.py`
  (`PROGRESS_SQL`), `app/writing/routes.py` (if the exercise view
  embeds the comparison), `app/writing/tutor.py`, `app/static/tutor.js`
  and `tutor.html` (show `comparison`), `app/static/app.js`,
  `app/static/index.html`, `app/static/styles.css`,
  `docs/adr/ADR-032-guided-writing-revision-attempts.md` (T039
  amendment)
- tests: `tests/app/test_writing_progress.py`,
  `tests/app/test_writing_revision_api.py`, tutor tests, browser tests
- create: `docs/progress/task_T039_result.md`

## Not in T039

Deployment, the production migration, GHCR, `main`; multiple-choice
mastery; more than one revision (`MAX_ATTEMPTS` stays 2, but the logic
compares first and latest attempt so a later increase needs no API
change); any grade, total or weighted score.

## PO decisions requested

1. Redefine `activity.submitted`, `levels[].submitted`/`evaluated` and
   `criteria[].pending` by exercise (values unchanged without revisions)
   rather than adding new fields and leaving the old ones counting
   submissions. Proposed: redefine, because the dashboard labels them
   "entregados" (exercises).
2. Comparison only for criteria scored in both completed evaluations
   with the same rubric checksum and pinned exercise revision; no total
   or average change. Proposed: yes.
3. Show the comparison to the student in a "Mis mejoras" section and on
   the exercise page; and to the tutor as an additive `comparison` field.
   Proposed: both.
4. Approve T039 on a feature branch from `dev`, PR into `dev`, synthetic
   data only; release still with T037 and T038 under separate
   authorization.
