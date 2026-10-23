# ADR-013: Student Practice Sessions with Server-Managed Generation Jobs

> **Status:** Accepted (Product Owner task T010)
> **Date:** 2026-10-23

---

## Context

T010 connects the validated set generator (ADR-011, ADR-012) to the Spanish
practice page (ADR-008). A 5-question set takes about 10 minutes on free
models, so the browser cannot hold one request open. Keys must never reach
the browser before an answer is submitted; answers are evaluated on the
server. There are no accounts.

---

## Decision

### Sessions and jobs (schema `practice`, `app/practice/`)

- `practice.session`: one row per practice. `session_id` is a random 128-bit
  token (the only capability for that practice). Holds configuration,
  allocation, job status (`queued`, `running`, `complete`, `partial`,
  `failed`), progress (slots finished), stop reason, `practice_set_id` and
  timestamps. No student identity.
- `practice.item`: accepted items per slot (with keys; server only).
- `practice.answer`: one answer per slot; the first answer is final.

### Job runner

- `POST /api/practice/sessions` validates the configuration (5 questions
  only), allocates with `allocate`, stores a `queued` session and submits it
  to an in-process single-worker queue; it returns at once (202).
- The worker runs `generate_set` (validation unchanged), reports progress
  after each slot, then stores items and the final status.
- Durability: state lives in PostgreSQL, so polling and refresh survive
  browser reloads. On server start, sessions still `queued`/`running` are
  marked `failed` with `interrupted` (the worker is in-process).

### Duplicate prevention

- The browser sends a `client_request_id`; it is unique, so a repeated
  submission returns the same session.
- A partial unique index allows one active (`queued`/`running`) session per
  configuration fingerprint, so double clicks or a second tab reuse it.

### Student API (no keys before submission)

- `GET /api/practice/sessions/{id}`: status, progress, Spanish message,
  objectives; when ready, questions as `student_view` (stimulus, stem,
  options). For answered questions only: chosen and correct option and
  explanation.
- `POST /api/practice/sessions/{id}/answers`: `{slot, label}`. Evaluated
  against the stored key; repeated submissions return the first result
  (`already_answered: true`).
- Summary (correct, incorrect, percentage, objectives and evidencias) when
  every available question is answered.

### Status shown to the student

Partial sets can be practised with a notice; failed sets show the reason
(`daily_budget`, `set_call_limit`, `llm_unavailable`,
`slot_retries_exhausted`, `interrupted`, `internal_error`) in Spanish.

### Frontend

Same static page, plain JavaScript: configuration → progress (polling every
3 s) → one question at a time → feedback → summary. The session token is kept
in `sessionStorage` so a refresh resumes. Only 5 questions are selectable.

---

## Consequences

### Positive

- No open request during generation; refresh-safe; keys never sent early.

### Negative

- In-process worker: a server restart fails running jobs (shown as
  interrupted); one set generates at a time.

### Neutral

- Anyone with a session token can see that practice; tokens are random and
  not listed anywhere.

---

## Related

- [ADR-008](ADR-008-practice-configuration-api.md),
  [ADR-011](ADR-011-validated-practice-sets.md),
  [ADR-012](ADR-012-controlled-parallel-generation.md)
- Report: `docs/progress/task_T010_result.md`
