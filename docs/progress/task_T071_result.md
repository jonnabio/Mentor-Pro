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
- The individual and bulk views both show `[object Object]` when a
  stimulus is a structured object. This rendering predates T071 (T068).
- Operations: no migration and no configuration change. Deploying needs
  the standard release flow and PO authorization.
