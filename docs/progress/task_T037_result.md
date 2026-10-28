# T037 Result: Student Revision "Mejorar mi respuesta" (ADR-032)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T037-student-revision` (from `dev` at `273100b`)
- **Status:** implemented and verified locally on `mentor_pro_test`; PR to
  `dev` open, not merged (needs separate PO authorization); released only
  together with T038; nothing deployed, migrated or published

## Thought

PO approved the T037 plan (API, quarantine: no revision, joint release
with T038). T036 already provides `start_revision`, `save_attempt_draft`,
`submit_attempt`; T037 adds the student routes and screen only. The
exercise response already has a `revision` key (the editorial revision,
ADR-023), so the new block is `revision_attempt` (recorded in the ADR-032
amendment).

## Action

- `app/writing/routes.py`: `revision_attempt` in the exercise view;
  `POST /exercises/{id}/revision` (201/200, 409 `revision_not_allowed`
  with Spanish reason, 409 `exercise_unavailable` when quarantined);
  `PUT /attempts/{id}/draft`, `POST /attempts/{id}/submit` (attempt 1
  refused, malformed 422, unknown 404, quarantined 409); submission
  validation shared with the exercise route (`submitted_text`).
- `app/static/index.html`, `app/static/app.js` (RCA-003 guarded): first
  response block moved above the editor; "Mejorar mi respuesta" /
  "Seguir mejorando"; "Mi primera respuesta", "Mi nueva versión",
  "Entregar mi mejora", "Mi mejora: …"; drafts and submit go to the
  attempt URL while revising (`work()`, `workUrl`); reload returns to the
  revision; L1 restore button hidden; L4 stage memory per attempt. The new
  handler is wired at page load.
- Tests: `tests/app/test_writing_revision_api.py` (13);
  `scenario_revision` in `scripts/dev/practice_e2e.py` (13 checks per
  viewport).
- ADR-032 T037 amendment; plan marked approved; T037 registered.

## Observation

| Check | Result |
| --- | --- |
| `test_writing_revision_api.py` | 13 passed |
| Writing and tutor tests (`-k "writing or tutor"`) | 233 passed |
| Browser suite (mocked, desktop + mobile) | `E2E=pass (473 checks, 0 failed)`; 447 earlier checks unchanged, incl. `scenario_dashboard_before_subjects_load` (RCA-003) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, test 621 passed, lint passed (log `.ace/logs/verify/20261028-092459-1781`) |

API tests cover: no offer before a completed review (draft, pending,
in progress); quarantine (no offer, 409, open revision frozen, history
readable); idempotent and parallel start (6 threads, one attempt); L1
seeded from the correction, no reference text in responses; L4 five
sections, validation, submission by sections; stale `client_seq`
ignored, frozen after submit, submit retry returns the first; first
submission, evaluations and scores byte-identical; attempt routes refuse
attempt 1; legacy exercise routes cannot write the revision; progress
shape unchanged.

Browser (both viewports): L2 double-click start creates one attempt;
first response and review stay visible; reload keeps the revision text;
double-click submit yields one submission, status "Mi mejora: Pendiente
de revisión del tutor"; L1 starts from the correction without restore;
failed save → "No se pudo guardar" → "Reintentar" stores; `pagehide`
flushes the revision draft; "Seguir mejorando" for an open revision; L4
five sections restored and submitted; no overflow, no JavaScript errors.

Preserved: L1–L4 editor behaviour, submission immutability, ordered
autosave (ADR-028), ADR-031 tutor isolation (no tutor file changed). No
new dependency; no regression-guarded file other than `app.js` changed.

## Risks

- **T038 required before release:** the tutor queue lists the revision as
  an ordinary submission without the first response; the student page
  does not show a review of the improved version yet.
- Progress counts revision submissions as activity until T039.
- Production needs the T036 migration first (runbook K) and approval.
- Live (non-mocked) restart check of an attempt draft not run.

## Next

T038 tutor re-evaluation; then joint T037+T038 release decision.
