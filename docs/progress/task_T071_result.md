# T071 Result: Tutor Bulk Review and Approval

- **Role:** Developer (T071 request, 2026-11-16)
- **Date:** 2026-11-16
- **Status:** ready for PO review. Not merged, released or deployed.

## 1. Existing implementation reused

- The queue is the T068 `ReviewQueue.pending`, with the same filters:
  subject, objective, difficulty and batch.
- Each approval is the existing `seeding.item_review_record` call. It
  keeps the review lock `(4047, 1)`, the in-transaction re-check, the
  append-only `generation.bank_item_review` row with reviewer `tutor`,
  and the "active generated link without a verdict" lifecycle rule.
- Authorization is the shared `tutor_guard`: an allowed client address
  plus the tutor token. The route exists only in the tutor service.
- No schema change and no new approval workflow. The batch gate is not
  touched. Bulk only approves; quarantine stays individual because each
  quarantine needs its own reason.

## 2. Changes

- `GET /api/tutor/review/queue`:
  - new optional `page` and `page_size` (at most 50);
  - adds `total` and, when paging is requested, `pagination`;
  - without them the response is the T068 full list.
- `POST /api/tutor/review/bulk-approve` with `{"request_ids": [...]}`:
  - accepts explicit IDs only, 1 to 50 per call;
  - refuses duplicate, empty or over-long IDs with 422, recording nothing;
  - processes each ID in its own transaction and returns one result per
    ID: `approved`, `already_reviewed`, `not_pending` or `error`;
  - a refused ID never undoes or blocks the others, and no verdict is
    ever half recorded.
- Tutor page, "Aprobación en bloque" (Spanish):
  - expandable full question with the proposed key, explanation,
    objective, evidence, batch and request;
  - a checkbox per question, "Seleccionar toda la página", "Limpiar
    selección", and "Aprobar seleccionadas (N)";
  - a confirmation dialog states the exact count;
  - the result message reports approved and refused questions with the
    reason for each;
  - the selection is page-scoped and resets after a result, a page change
    or a filter change;
  - the existing one-at-a-time review is unchanged.

## 3. Verification

- `tests/app/test_tutor_bulk_approve.py` (8 API tests and 1 browser test)
  covers:
  - paging and filters;
  - single and multiple approval with audit rows and curriculum links
    preserved;
  - partial failure, including a quarantine that is not overridden;
  - repeated and simultaneous submissions;
  - invalid payloads;
  - authorization;
  - absence from the student service.
- The browser test (phone viewport) covers single selection, page-scoped
  select-all, clear, page and filter resets, a cancelled confirmation and
  a partial failure.
- Regression: the T068 review tests and the tutor service tests pass
  (56 passed with the browser tests enabled).
- During the work the T068 browser regression caught a defect, which was
  fixed: refreshing the bulk list kept the individual-review busy flag set
  and dropped a fast second decision.
- Screenshots: `docs/progress/screenshots/T071/`.
- Full gate (`.ace/scripts/verify.sh`): `VERIFY_RESULT=pass gate=all`,
  1202 passed, 15 skipped, lint passed.
  - The first run had 7 setup errors in `test_quiz_sizes_subjects.py`
    (`DeadlockDetected` in a fixture). That file passes alone and after
    the T071 tests, and it runs before them.
  - The rerun was clean. This is recorded as an intermittent existing
    fixture deadlock.

## 4. Risks and operations

- An approval makes a question servable to the student at once. The
  confirmation dialog and the expandable inspection keep the tutor in
  control, but the page cannot force the tutor to open every question.
- **PR #77 review correction (structured stimulus):** both views used to
  show `[object Object]` for a structured stimulus. This is fixed.
  - Supported shapes (`generation/parsing.py`): `{"type": "none"}`,
    `{"type": "text" | "table", "text": ...}`, and plain strings in older
    records.
  - `renderStimulus` in `tutor.js` builds DOM nodes and text only, never
    `innerHTML`.
  - A table stimulus with at least two pipe- or tab-delimited lines
    becomes a table. Any other text keeps its line breaks, so no content
    is dropped. `none` and empty stimuli are hidden.
  - The same function now serves the individual review, the bulk review
    and the practice-results detail.
  - No schema, generation or approval change.
  - Production table text was not sampled because the read-only
    production query was not permitted from this session. Unrecognised
    layouts fall back to line-preserving text.
  - Evidence: `screenshots/T071/structured-stimulus.png`; tests
    `test_stimulus_rendering_cases` and
    `test_structured_stimulus_in_both_review_views`. Those tests include
    an injection case.
- Operations: no migration and no configuration change. Deploying needs
  the standard release flow and PO authorization.

## 5. Gate B: production deployment (2026-11-18)

The PO authorized Gate B (`PO-T071-GATE-B-2026-11-18`). Production
acceptance by the tutor remains a separate decision and is **pending**.

- **Release identity:** `release-manifest.json` sha256
  `7685f567a8a6b3436a0f80424fcb03c93ef75d25918bcc319fa34beba5f79f9a`
  matched. Commit `bc590fb6c144c2f94537488f45db0fa555d5d237`, CI run
  44232643285 (success), schema 0001..0001 and the image digest all
  agree.
- **Preflight:** `PREFLIGHT OK: DEPLOY COMPATIBLE`. The server retrieved
  the image, and the live schema is current.
- **Backup:** `mentor_pro_2026-11-18_210616.dump`, sha256
  `462ad9451eed426d388597244e5bec61a4b8b09e41f0ca0ec27acfa840aa7080`
  (37 tables, 2850 rows). `verify-backup` returned `VERIFY OK`.
- **Deploy:** 2026-11-18T21:06:41Z, window `T071-RELEASE-2026-11-18`.
  - Result: `DEPLOY OK`, `SMOKE PASS (13/13)`, `STATUS HEALTHY`.
  - Both app and tutor run
    `ghcr.io/jonnabio/mentor-pro@sha256:71723c4eed2e3b493bfd640453ed191b3eaf18143316cd29726edc60ac0aee2e`.
  - The previous image was `@sha256:dc5d1ce4…805b` (`v2026.11.16-2`).
    Rollback was not required.
- **Data integrity:** row counts and md5 fingerprints for all 37 tables
  (curriculum, generation, llm, practice, writing) are identical before
  (21:05:34Z) and after (21:06:52Z) the deploy.
  - Verdicts: 41 (26 approved, 15 quarantined). No verdict was recorded.
- **Configuration:** unchanged.
  - `OPENROUTER_ALLOW_PAID=false`, `MENTOR_PRO_REPLENISH_SCHEDULE=on`,
    `MENTOR_PRO_BANK_ONLY_SUBJECTS=matematicas:5,10,15,20,25,30`.
  - The env key set hash and the crontab hash are unchanged.
  - Scheduler: enabled, `tick_calls` 10, not paused, 0 failures.
- **T071 security (non-mutating checks):**
  - tutor `bulk-approve` without the token: 403;
  - the paged queue without the token: 403;
  - the student service `bulk-approve`: 404;
  - the tutor page: 200, and the deployed `tutor.js` contains
    `renderStimulus` and bulk approval.
- **Operational risk:** the review queue is **51 pending**, above the 40
  pause threshold:
  - Español 8, Matemáticas 23, Ciencias 11, Estudios Sociales 9;
  - it was 26 at the last handoff;
  - it is reported to the PO. The scheduler was not paused, because Gate
    B requires the configuration to be preserved.

## 6. Enhancement: approve all pending questions (2026-11-22)

PO requirement: the tutor approves the whole queue in one explicit
operation instead of page by page (10 per page). Frontend only; the
backend, the API limit and the approval path are unchanged.

- **Selection:** "Seleccionar todas las pendientes (N)", where N is the
  total for the applied filters. It reads every page of
  `GET /api/tutor/review/queue` (`page_size` 50). The selection survives
  page changes, and the checkboxes show it. Individual checks, "Seleccionar
  toda la página" and "Limpiar selección" keep working. A filter change or
  a result clears the selection.
- **Scope:** the panel and the dialog state the scope: "todas las materias,
  sin filtros" or "solo las preguntas filtradas (…)". Filters edited but
  not applied are ignored.
- **Confirmation:** a modal dialog shows the exact count, the subjects
  represented, the scope and a warning that these are real tutor approval
  decisions. Nothing is sent before "Aprobar"; Cancelar or Escape send
  nothing.
- **Revalidation:** at confirmation the queue is read again. Questions no
  longer pending are dropped and counted in the dialog. Questions that
  appeared after the selection are never added.
- **Batches:** the existing `POST /api/tutor/review/bulk-approve`, in
  sequential batches of at most 50 (`BULK_MAX`). Each ID still goes through
  `item_review_record` (lock, re-check, audit row, reviewer `tutor`). A
  failed request stops the run; nothing already sent is resent.
- **Result:** approved, not approved (with the status per ID), not sent,
  and the pending count remaining. Progress shows between batches. The
  buttons are disabled while a run is in flight.
- **Page selection:** unchanged; it keeps the native confirmation.

Tests: `tests/app/test_tutor_approve_all.py` (browser, opt-in locally,
mandatory in CI):

- real tutor app and database: cross-page selection, filters,
  cancellation, revalidation and audit rows;
- scripted queue: sizes 0, 10, 33, 50, 51 and 120; batch bounds; a failed
  batch that is never resent; questions added after the selection;
- the frontend batch size equals `tutor_review.BULK_MAX`.

Risk: if other approvals happen while the selection is read page by page,
the pages shift and a question can be missed. It then stays pending; it is
never approved by mistake. The dialog always shows the revalidated count.

### 6.1 Review correction and integration (2026-11-24)

- **Correction (PO review of PR #84):** a failed batch is now reported as
  **unconfirmed**: the server may or may not have applied it, it is never
  retried, and the tutor is pointed to the refreshed queue. The batches
  after it are reported as **not sent** (never attempted; still pending).
  The queue refresh is unchanged. Commit `31dc74d`, with the new test
  `test_a_failed_last_batch_is_unconfirmed_with_nothing_unsent`.
- **PR #84:** final head `31dc74df3ade59e9a6a0eb4f80d5a037314d209d`,
  exact-head CI 45417773859 success (browser tests executed=29,
  skipped=0). Merged into `dev` with the exact-head guard as
  `97e29646192ac1b1edd6c70bfeeda37c7893de89`; `dev` CI 45420176013
  success (executed=29, skipped=0).

## 7. Gate A: release publication (2026-11-24)

PO authorized. Production was not modified.

- **Release PR #85** (`dev` → `main`): head `97e2964` (the approved
  integration commit, 8 files, PR #84 changes only). Exact-head CI
  45494892496 success (executed=29, skipped=0). `main` has no branch
  protection and requires no review. Merged with the exact-head guard as
  `141d0725eb1583579601885a3de215c5e03aab9f`.
- **`main` CI 45496672372:** all four jobs green, including Tag and
  Release.
- **Release `v2026.11.24-1`:** tag points to `141d072`; not a draft or
  prerelease; asset `release-manifest.json`.
- **Image:** `ghcr.io/jonnabio/mentor-pro@sha256:9948605d05bedf176543f7621a398e85f819862b75e9b98851f1fd5d57e3a384`.
  The registry digest for the tag was checked independently and matches
  the manifest.
- **Labels (read from the registry):** version `v2026.11.24-1`, revision
  `141d072…`, `io.mentorpro.capability.report-holds=1`, schema
  `0001..0001`.
- **Manifest:** sha256
  `d0f4167b3f2ec83abcf3c31b11b26f20f87fe2f6bfd7c9228757debb4311e60e`;
  commit `141d072`, CI run 45496672372, schema 0001..0001, smoke student
  and tutor pass, status "Published, not authorized for deployment".
- **Database compatibility:** schema range 0001..0001, the same as
  production `v2026.11.21-1`; no migration in this release.
- **`dev`** was fast-forwarded to `main` (`141d072`; it was an ancestor).
- **Not done (separately gated):** deployment, automatic eligibility,
  scheduler resumption, T071/T072 human acceptance.
