# T062 Result: Approved Inventory Expansion

- **Role:** Developer (PO authorization PO-QUESTION-BANK-PHASE-B-2026-11-09)
- **Status:** tooling implemented and tested; production generation and
  human review pending

## Change (ADR-036)

- `app/practice/replenishment.py`, `inventory`: per objective and
  difficulty it reports eligible, pending review, quarantined and rejected
  questions separately, plus served, answered, correct and accuracy.
- `python -m app.practice.replenish inventory|assess|run|requests`.
- Candidates are generated through the existing seeder:
  - fixed 100-cell plan per subject, exact cells, D01;
  - lock, free models only, shared daily budget.
- They are held until the tutor's `seed_bank item-review-record` approval.
  Nothing marks a candidate approved.

## Production inventory at the start (read-only, 2026-11-09)

| Subject | Batch | Filled cells | Reviews |
| ------- | ----- | ------------ | ------- |
| Matemáticas | open, review pending | 9 of 100 (1 generated) | 1 approved, 1 quarantined |
| Español | none | — | — |
| Ciencias | none | — | — |
| Estudios Sociales | none | — | — |

Accepted questions overall:

| Prefix | Easy | Medium | Hard |
| ------ | ---- | ------ | ---- |
| M | 9 | 19 | 3 |
| E | 10 | 11 | 1 |
| C | 2 | 2 | 1 |
