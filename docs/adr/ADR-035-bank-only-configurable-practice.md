# ADR-035: Bank-Only Configurable Practice

> **Status:** Accepted (Product Owner task T048, 2026-11-01; decisions D1–D4
> approved, D5 delegated). Amends [ADR-014](ADR-014-validated-question-bank.md).
> **Date:** 2026-11-01

---

## Context

Practices had 5 questions, filled from the bank and then generated while the
student waited (about 5 minutes, possibly `partial`). The PO asked for 5, 10,
15, 20, 25 or 30 questions, served at once from validated bank questions,
without slow generation and without relaxing curriculum alignment.

The deterministic allocation asks for fixed cells (objective, evidencia,
difficulty). A seeded batch (ADR-034) is planned differently, so a quiz could
fail on exact cells while the bank holds suitable questions.

## Decision

### Sizes and request mode

- Permitted sizes: `QuestionCount` in `app/allocation.py` (5, 10, 15, 20,
  25, 30), used by the practice API and the plan endpoint. The UI defaults to 5.
- `POST /api/practice/sessions` takes `source`:
  - `bank_only` (the student UI): any permitted size, bank only.
  - `bank_then_generate` (default when omitted): the earlier flow, 5 questions
    only; other sizes get 422. Its stored configuration is unchanged.

### Bank-only composition (`app/practice/bank_allocation.py`)

1. Questions per objective come from `allocate` unchanged; no objective is
   swapped (D2).
2. Within an objective, any evidencia × difficulty cell with an unused
   eligible question may fill a slot; evidencias are spread before one
   repeats (D1). Each question matches its recorded objective, evidencia and
   difficulty exactly; the stored allocation records the cells used.
3. "Mixed" is a balance: each level within ±1 of a third of the practice
   (D3). Its educational purpose is a near-equal mix of levels; a slot's
   position carries no meaning. An explicit level is never substituted.
4. Unseen questions first; seen ones only when no unseen one fits. No
   question or near duplicate (D01) twice. Eligibility, quarantine and
   review holds are those of `QuestionBank` (ADR-014, ADR-034).
5. The practice is assembled before any session exists. Complete: the
   session is created `complete` with bank items. Otherwise nothing is
   created and the API returns 409 `insufficient_inventory` with `requested`,
   `largest_available` (largest smaller permitted size that fits now, 0 if
   none) and a Spanish message (D5). No LLM call, no job (D4: larger sizes
   are bank-only).
6. Selection is a depth-first search over slots that tries candidates in
   the preference order above. The first complete practice is the greedy
   choice whenever that works, and a dead end backtracks instead of
   reporting a shortage. Failed partial selections are remembered by their
   set of chosen questions; at most 20,000 states per size.
7. Bank lookups: one query per objective (`QuestionBank.candidates`), one
   shared connection per request, grounding built once per evidencia for
   revalidation.

### Switch (T049, 2026-11-02)

- `MENTOR_PRO_BANK_ONLY_ENABLED` (`true`, `1` or `yes`; anything else,
  or absent, is off). Production sets it in `/etc/mentor-pro/app.env`.
- Off (default): `/api/subjects` reports `practice.bank_only: false` and
  sizes `[5]`; the UI shows only 5 and sends no `source`, so practices use
  the earlier bank-first flow with generation. `source: bank_only` is
  refused server-side (422 `bank_only_disabled`, nothing created).
- On: the behavior above. Requests without `source` still get the
  5-question flow in both states; developer endpoints are unaffected.
- The switch does not touch seeding, review, quarantine or eligibility.

## Consequences

- Practices start in under a second (measured locally on the synthetic
  catalog: p95 439 ms for 5, 863 ms for 30; the earlier flow 592 ms for 5).
- Until the bank grows, larger sizes are refused with a smaller option, and
  repeated practices reuse seen questions.
- No schema migration; existing sessions, answers, mastery (ADR-015) and the
  generation pipeline are unchanged.

## Related

- [ADR-014](ADR-014-validated-question-bank.md),
  [ADR-015](ADR-015-repeat-aware-learning-status.md),
  [ADR-034](ADR-034-question-bank-foundation.md)
- Report: `docs/progress/task_T048_result.md`

## Amendment T057 (2026-11-07): Per-Subject Switch

- `MENTOR_PRO_BANK_ONLY_SUBJECTS` lists the subjects with bank-only
  practice and their sizes, for example `matematicas` (size 5) or
  `matematicas:5,10;ciencias`. Absent or empty means off. It takes
  precedence over `MENTOR_PRO_BANK_ONLY_ENABLED`, which keeps its T049
  meaning (every subject, every size). An unknown subject or size stops
  the application from starting.
- `/api/subjects` reports each subject's switch and sizes; the student UI
  applies them when a subject is chosen. Subjects without the switch keep
  the 5-question generated flow and refuse `source: bank_only` (422).
- A bank-only request for a size the subject does not offer is refused
  with 422 `invalid_question_count`; nothing is created. Composition rules
  D1-D4 and the no-generation guarantee are unchanged.

## Amendment T063 (2026-11-09): Sizes Offered Only When They Start

- `POST /api/practice/availability` reports, for the student's current
  choice, the permitted sizes the composer fills now (plus 5, which a
  shortage generates). The UI offers only those; see
  [ADR-036](ADR-036-question-bank-phase-b.md). Composition rules D1-D5, the
  409 refusal and the no-generation guarantee for sizes above 5 are
  unchanged.
