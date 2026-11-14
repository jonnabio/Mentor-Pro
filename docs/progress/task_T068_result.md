# T068 Result: Tutor Question Review Dashboard

- **Role:** Developer (PO authorization PO-QBANK-COMPLETION-2026-11-14)
- **Status:** implemented and tested; PO review of the PR required before
  release; first acceptance is a real pending candidate reviewed by the
  human tutor in production
- **Decision:** [ADR-036](../adr/ADR-036-question-bank-phase-b.md)

## Change

- Tutor page: a third section, **Revisión de preguntas**:
  - pending queue with filters (subject, objective, difficulty, batch);
  - full question (stimulus, stem, options, explanation), with the proposed
    correct answer highlighted;
  - curriculum objective and its evidencia as grounding;
  - approve or quarantine; the quarantine reason is required, the comment
    optional;
  - next-question navigation, "Pregunta n de N", and live
    pending/approved/quarantined counts per subject.
- `app/practice/tutor_review.py`: `GET /api/tutor/review/queue` and
  `POST /api/tutor/review/decisions`, served by the tutor service only, with
  the existing tutor check (allowed client address and tutor token).
- **No second approval mechanism.** The queue is
  `seeding.item_review_export` for each subject's current batch. Verdicts go
  through `seeding.item_review_record` (T051, append-only
  `generation.bank_item_review`); eligibility stays the existing
  `QuestionBank` rule. The reviewer is `tutor`, the same value the CLI
  records.
- **Exactly once.** `item_review_record` now takes an advisory transaction
  lock (4047, 1) and re-checks inside the transaction. A repeated, stale or
  simultaneous submission is refused with 409 `already_reviewed` and records
  nothing. The page also disables the button while a decision is in flight.
- **Audit trail:** `generation.bank_item_review` gains an optional `comment`
  column (additive, `ADD COLUMN IF NOT EXISTS`). Verdict, reason, reviewer
  and timestamp were already recorded.

## Unchanged

- Pending questions are never eligible.
- Nothing is approved without the tutor; the page never preselects a verdict.
- The batch sample gate and the CLI (`seed_bank item-review-sample/-record`)
  still work.
- The student app has no review route.
- Tutor token handling is unchanged.

## Tests

`tests/app/test_tutor_review.py`:

- **Queue content:** key, grounding and counts.
- **Filters:** all four, plus invalid values rejected.
- **Authorization:** no token, wrong token and wrong address are refused,
  and nothing is recorded.
- **Approve and quarantine:** a reason is required; eligibility follows the
  verdict; the audit row holds the comment; a repeat is refused (409); an
  unknown request is refused; the batch gate is untouched.
- **Concurrency:** four simultaneous submissions record one verdict.
- **Student app:** no review routes; the tutor service registers them.
- **Browser (Playwright, `MENTOR_PRO_BROWSER=1`):**
  - a wrong code returns to the login;
  - the key is highlighted and the progress is shown;
  - a missing verdict or reason is refused;
  - navigation works;
  - an approval with a comment (double click) records once;
  - the quarantine is recorded with its reason;
  - the counts update;
  - a stale-tab resubmission is refused (409).

## T067 merge record

PR #72 merged into `dev` as `8aeaad9` (CI run 43614514102). Not yet
released.
