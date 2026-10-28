# T037 — Student Revision ("Mejorar mi respuesta") — Implementation Plan

> **Date:** 2026-10-28
> **Status:** PROPOSED — awaiting Product Owner approval; T037 not
> registered in `docs/progress/tasks.json`; no code written
> **ADR:** [ADR-032](../adr/ADR-032-guided-writing-revision-attempts.md)
> (accepted for T036); this plan proposes the API details ADR-032 left to
> "API review" and needs an ADR-032 amendment before code
> **Depends on:** T036 (merged into `dev`)
> **ACE:** Analyze → Discuss → Plan → Execute → Verify

## Scope

Only the student-facing workflow on the student service (port 8080):

1. After a **completed** tutor review, the student sees "Mejorar mi
   respuesta".
2. The student opens a revision of the same exercise, sees "Mi primera
   respuesta" and "Comentarios del tutor", edits "Mi nueva versión" in the
   existing L1–L4 editor (autosave, reload, retry) and submits with
   "Entregar mi mejora".
3. Afterwards the exercise shows the revision as pending tutor review; the
   first response and its feedback stay visible and unchanged.

Out of scope: tutor screen changes (T038), progress comparison (T039),
L5, AI grading, new infrastructure, deployment, production migration.

## Current state (from T036)

- Store: `start_revision(exercise_id)` (completed evaluation required, at
  most two attempts, parallel calls return one attempt, draft seeded once
  from the submitted text and L4 sections), `save_attempt_draft`,
  `submit_attempt`, `attempt_draft`, `attempt_submission`, `attempts`.
- Routes: every student route addresses attempt 1 only.
- UI (`app/static/app.js`, guarded by RCA-003): `openWritingExercise`,
  `renderWritingState` (editor hidden once submitted, feedback shown),
  `renderGuided`, draft saving (`draftUrl`, `sendDraft`, `flushDraft`,
  `client_seq`), submit with `client_request_id`.

## Proposed API (student service only; additive)

| Method and path | Behaviour |
| --- | --- |
| `GET /api/writing/exercises/{id}` | Unchanged fields describe attempt 1. New `revision` object: `available` (attempt 1 reviewed, typed, eligible, no revision yet), or the open/submitted revision: `attempt_id`, `attempt_number`, `draft`, `submission` (status), `feedback` (null until T038 reviews exist) |
| `POST /api/writing/exercises/{id}/revision` | `start_revision`; 201 created or 200 existing (same `attempt_id`); 409 `revision_not_allowed` with a Spanish message; 409 `exercise_unavailable` for quarantined exercises |
| `PUT /api/writing/attempts/{attempt_id}/draft` | `save_attempt_draft`; same body, `client_seq` ordering and responses as the exercise draft route; 409 `already_submitted` |
| `POST /api/writing/attempts/{attempt_id}/submit` | `submit_attempt`; same validation as today (empty text, L4 missing sections, blank lines); retry returns the first submission |

Rules:

- Writes always name the `attempt_id`; nothing infers the newest attempt.
  Attempt routes refuse attempt 1 (`attempt_routes_are_for_revisions`,
  409) so the old routes stay the only writers of attempt 1.
- `attempt_id` format validated (`^ATT-[A-Za-z0-9-]{1,80}$`); unknown →
  404; attempt of a quarantined or handwritten exercise → 409.
- Responses never include tutor references, evaluation drafts or rubric
  internals (only the completed feedback view already used today).
- Old clients keep working: they ignore `revision`; their exercise-level
  draft saves stay frozen (409) once attempt 1 is submitted.

## Proposed UI

- Feedback card: button **"Mejorar mi respuesta"** when
  `revision.available`; **"Seguir mejorando"** when a revision draft
  exists; none when the revision is submitted.
- Revision screen (same exercise panel):
  - **"Mi primera respuesta"**: read-only first text (L4: the four
    paragraphs; plan collapsed).
  - **"Comentarios del tutor"**: the existing feedback card, read-only.
  - **"Mi nueva versión"**: existing editor seeded from the revision draft
    (L1: the student's submitted correction, never the text with errors;
    "Restaurar texto original" hidden; L2–L3: the submitted paragraph; L4:
    the five stages with the submitted sections).
  - Save indicator, autosave, keepalive flush and "Reintentar" exactly as
    ADR-028, against the attempt URL; `saveSeq` restored from the revision
    draft's `client_seq`.
  - **"Entregar mi mejora"** with the existing confirmation.
- After submission: "Mi mejora: Pendiente de revisión del tutor" plus the
  first response and its feedback.
- Reload/`rememberWriting` keeps the student on the revision (stores the
  `attempt_id` with the exercise).
- Handlers wired at page load, not after fetches (RCA-003 invariant 1).

## Implementation steps (after approval)

1. ADR-032 amendment: API table and rules above; PO approval.
2. Register T037 in `tasks.json` (`pending` → `in_progress`).
3. Routes and response view (`app/writing/routes.py`); API tests.
4. UI (`index.html`, `app.js`, `styles.css`); browser scenarios.
5. Verify, result file, PR to `dev` (CI verified on the `dev` push, as
   for T036, unless CI on PRs into `dev` exists by then).

## Tests

API (`tests/app/test_writing_revision_api.py`, test database only):

- Button state: not before completed review; not for pending,
  in-progress or handwritten; not for a quarantined exercise.
- Start idempotent and concurrent (one attempt, same id); 409 messages.
- L1 seeded from the submitted correction; L2/L3 paragraph; L4 five
  sections and assembled text.
- Attempt draft ordering, stale `client_seq`, frozen after submit, submit
  retry returns the first submission, L4 validation.
- Attempt routes refuse attempt 1 and unknown or malformed ids; exercise
  routes never write the revision.
- First submission, evaluation and scores byte-identical after the whole
  flow; responses contain no tutor reference text.
- Progress endpoint unchanged in shape (counts change is T039).

Browser (`scripts/dev/practice_e2e.py`, mocked, desktop and mobile):

- L2: review → "Mejorar mi respuesta" → edit → reload keeps text → submit
  → pending; first response and feedback still shown.
- L1: editor starts from the correction; no restore button.
- L4: five stages restored; submit with sections.
- Double click on start and on submit; offline save → "No se pudo
  guardar" → "Reintentar"; closing the tab flushes the revision draft.
- `scenario_dashboard_before_subjects_load` still passes (RCA-003).

Gates: `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`),
browser suite, live draft restart check for an attempt draft.

## Risks and dependencies

- **Tutor side (T038):** without T038, the tutor queue lists the revision
  as an ordinary submission (it already carries `attempt_number`) and the
  tutor can evaluate it without the first response in context.
  Recommendation: release T037 only together with T038.
- **Progress (T039):** revision submissions count as activity until T039.
- **RCA-003:** `app.js` is guarded; new handlers must not depend on
  asynchronously created controls.
- **Production:** any release needs the T036 migration first (runbook K)
  and separate approval; T032/T033 real-user acceptance is still pending.

## Decisions requested from the Product Owner

1. Approve the API table and rules (ADR-032 amendment).
2. Quarantined exercise with a reviewed first attempt: no revision
   (proposed, fail closed) or allow it on the pinned revision?
3. Release T037 only with T038 (proposed), or allow T037 alone?
4. Register T037 and start implementation.
