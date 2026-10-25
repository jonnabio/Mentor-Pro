# ADR-028: Reliable Writing Draft Saving

> **Status:** Accepted (Product Owner task T030)
> **Date:** 2026-10-25

---

## Context

Drafts (ADR-021, ADR-026) were saved on demand, on L4 stage changes and,
for L4 only, after a pause in typing. A delayed request could overwrite
newer text, a failed save showed only a general error, and edits made just
before hiding or closing the tab could be lost.

---

## Decision

### Ordering

- Each save carries `client_seq`, a value that only increases (the
  browser uses its millisecond clock and never goes below the last value it
  sent or loaded). `writing.draft.client_seq` stores the newest; a save that
  is not newer changes nothing and answers `applied: false`.
- Each applied save records `writing.draft.exercise_revision` (the
  revision the student is writing against).

### Browser

- One save in flight at a time; edits made meanwhile are saved right after
  it. Autosave after 2 s without typing in every typed editor (L1–L4).
- Immediate save before changing L4 stage, leaving the exercise or
  submitting; a failed save keeps the student on the page.
- Tab hidden (`visibilitychange`) or page closing (`pagehide`): pending
  edits are sent with `fetch(…, {keepalive: true})`; `beforeunload` asks
  before discarding unsaved text.
- Indicator: "Cambios sin guardar", "Guardando…", "Guardado" (only after
  the server answered) and "No se pudo guardar" with "Reintentar". The text
  on screen is never replaced by a failed or late response.

### Server

- A database error while saving answers 503 `save_failed`; the transaction
  writes nothing, so the earlier draft stays.
- Submitted work stays immutable (drafts 409 after submission; one
  submission per exercise).

---

## Consequences

- Browsers limit keepalive bodies to 64 KiB; a larger draft (very long L4
  text) is sent without keepalive when the page closes and may not arrive.
- If the browser or computer stops abruptly (crash, power loss), only what
  the server already confirmed is kept.
- After a reload, the page shows the draft stored at that moment; a
  keepalive save still in transit appears on the next load.

---

## Related

- [ADR-021](ADR-021-student-writing-practice.md),
  [ADR-026](ADR-026-guided-composition-l4.md)
- `docs/progress/task_T030_result.md`
