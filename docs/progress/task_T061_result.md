# T061 Result: Performance-Based Replenishment

- **Role:** Developer (PO authorization PO-QUESTION-BANK-PHASE-B-2026-11-09)
- **Status:** implemented and tested; production operation pending
  deployment

## Change (ADR-036)

- Policy (configurable starting values): at least 10 answers and accuracy
  0.80 for the performance trigger; low inventory below 3 per objective and
  difficulty; at most 100 candidates per subject per run. Coverage and low
  inventory triggers do not depend on accuracy.
- `generation.replenishment_request`:
  - One pending request per cell, enforced by a unique partial index.
  - Each request records its trigger, evidence and policy.
  - Statuses: `open`, then `candidates_generated` (awaiting review), then
    `closed` (`satisfied`, `reviewed` or `no_planned_gap`).
- `generation.inventory_snapshot`: what the tutor page shows.
- `run`:
  - Generates for open requests only.
  - Stops on the call limit, the batch limit, the budget or rate limits,
    keeping requests open.
  - Never generates a pending request twice.
- Tutor page "Banco de preguntas y reposición" (`GET /api/tutor/practice/bank`,
  read-only): inventory per subject and cell, pending requests and their
  reasons.

## Tests

`tests/app/test_replenishment.py` (11):

- Policy validation; independent triggers; minimum answers.
- One request per cell, opened once; database uniqueness.
- Candidates held for review; no second generation.
- A rejected candidate is never eligible; an approved one is eligible.
- Budget, call and batch limits keep requests open.
- `no_planned_gap`.
- Performance trigger from real answers (12 answered, 11 correct).
- Tutor view: refused without the token, POST 405, no question text.

Browser E2E (desktop and mobile): the tutor bank view matches the stored
snapshot and pending requests, with no overflow.

## Limitation needing a PO decision

Generation fills only the fixed 100-cell plan per subject (ADR-034). Once a
subject's plan is full, a performance-triggered request closes as
`no_planned_gap`. Generating beyond the plan, for example a second batch,
needs a PO decision.

## Release

- PR #66 merged into `dev` as `f207de4` (dev CI 42750606976, green).
  Authorization `PO-PHASE-B-PROD-2026-11-09`.
