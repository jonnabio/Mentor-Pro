# ADR-034: Question Bank Foundation (Seeded Batches and Review Gate)

> **Status:** Accepted (Product Owner task T047, 2026-11-01). Amends
> [ADR-014](ADR-014-validated-question-bank.md).
> **Date:** 2026-11-01

---

## Context

Practices fill slots from accepted questions (ADR-014) and generate the
rest while the student waits, about 5 minutes, and may end `partial`. The
bank grows only from those practices. The PO asked for a persistent,
validated inventory of 100 questions per subject, prepared ahead of
practice, without weakening validation, the budget or existing records.

---

## Decision

### Batches and the fixed cell plan (`app/practice/seeding.py`)

- A batch (`generation.bank_batch`) is a fixed plan of `target` cells
  (default 100) for one subject and baseline: `allocate(all multiple-choice
  objectives, target, "mixed")`. A cell is an objective, an evidencia and a
  difficulty. The plan is stored and never changes.
- A cell is filled only by an eligible question for that exact cell. Nothing
  is borrowed from another cell to reach the target; a cell that fails stays
  a reported gap.
- `generation.bank_batch_item` links a question to a cell. A question
  belongs to at most one batch; a cell has at most one active question. A
  link is deactivated, never deleted.
- Tables are additive (`CREATE ... IF NOT EXISTS` in `QuestionBank`), like
  ADR-014. No versioned migration; existing sessions, answers and attempts
  are untouched.

### Three separate states

| State | Meaning |
| ----- | ------- |
| Inventory | active linked questions / target |
| Coverage | filled / planned cells; gaps and roll-ups by objective, evidencia, difficulty; catalog objectives and evidencias with no planned cell |
| Educational readiness | `review_status` `pending`, `passed` or `failed` |

Batch `status` is `open` until every cell has an active question, then
`filled`. Only the PO closes a batch as `short`.

### Seeding run (`python -m app.practice.seed_bank run`)

1. **Lock.** `pg_try_advisory_lock(4047, crc32(baseline:subject))` on a
   dedicated connection, held for the whole run. A competing run fails at
   once (`SEED BUSY`, exit 3). The lock dies with the connection, so a crash
   never leaves the subject locked. Before every write the run checks in
   `pg_locks` that its own backend still owns the lock and stops with
   `LOCK LOST` (exit 4) otherwise. Unique indexes (one current batch per
   subject; one active question per cell; one batch per question) hold even
   without the lock.
2. **Adopt.** Unfilled cells take accepted questions that are eligible
   under ADR-014 (current checker, or recorded revalidation), match the cell
   exactly, pass D01 against the batch, are not quarantined and are not
   linked elsewhere. This also recovers questions a crashed run stored but
   did not link (`practice_set_id` `seed-<batch>-…`, origin `generated`).
3. **Generate gaps.** One cell at a time with the unchanged pipeline
   (`generate_set`, `generate_one`), within `--max-calls` (default 20) and
   the shared daily budget. Each accepted question is linked as soon as it
   is stored, after D01 against the whole batch.

### Educational review gate

- `review-sample` draws a reproducible sample (seeded per batch, shuffled
  per difficulty, taken round-robin) of 10 filled cells and writes the
  tutor's review file (question, key, explanation, curriculum text).
- `review-record` stores verdicts all-or-nothing in the append-only
  `generation.bank_item_review` (`approved`, or `quarantined` with
  `wrong_key`, `ambiguous`, `off_curriculum`, `level` or `other`). Samples
  are kept per round in `generation.bank_review_sample`; no verdict or sample
  row is ever changed or removed.
- A quarantined question is never eligible (practices, adoption, coverage);
  its cell reopens and the next run fills it. The replacement forms the next
  review round.
- `passed`: every sampled cell ends with an approved active question in a
  filled batch. `failed`: 3 quarantined sample questions; the batch is then
  investigated, not continued.
- `quarantine` marks any accepted question, linked or not, outside a sample.
  A quarantine in a batch that already passed returns it to `pending`: its
  generated questions are held again until every reopened cell's
  replacement is reviewed and approved.

### Serving rule

Questions the seeder generated are held from practices until their batch
review passes (`QuestionBank.eligible`). Adopted questions stay servable,
as before, unless quarantined. Validation, routes, the student UI, the
generation pipeline and the LLM budget are unchanged.

---

## Consequences

### Positive

- Inventory is prepared outside student requests, resumable and auditable
  per cell; shortfalls are visible, not padded.
- Question-level quarantine now exists for multiple-choice questions.

### Negative

- At the unchanged budget (50 requests a day, shared with practices) a
  100-question batch takes weeks of runs.
- Readiness depends on the tutor's review time.
- Practices still match cells exactly (ADR-014); configurable sizes and
  looser matching are Increment 2.

### Neutral

- A single anonymous student (ADR-015): "seen" counts are global.
- Running the seeder on production is a separate PO authorization.

---

## Related

- [ADR-011](ADR-011-validated-practice-sets.md),
  [ADR-014](ADR-014-validated-question-bank.md),
  [ADR-015](ADR-015-repeat-aware-learning-status.md),
  [ADR-027](ADR-027-writing-exercise-eligibility.md) (append-only
  eligibility pattern)
- Report: `docs/progress/task_T047_result.md`
