# T051 Result: Targeted Seeding and Individual Educational Review

- **Date:** 2026-11-03
- **Role:** Developer
- **Status:** Done. PO final approval 2026-11-03; PR #48 (head
  `2a4fb4e`, CI 41729749634) merged into `dev` as `3b99f02` (`dev` CI
  41747414133 green). Not released or deployed. No production seeding, no live generation,
  budget unchanged.
- **Decision record:** [ADR-034](../adr/ADR-034-question-bank-foundation.md)
  (amendment T051)

## Stage A assessment (read-only, 2026-11-03)

- Production on `v2026.11.02-1` (`738af74e`), all containers healthy.
  Reads ran with `default_transaction_read_only=on`.
- No seeding batch exists yet. Matemáticas: 12 accepted questions
  (checker 1.6.0) over 8 of 22 objectives, one `hard` (M16). Six match a
  cell of the 100-cell plan (22 objectives, 80 evidencias, 34/33/33).
- Whole-subject size 5 always uses M01, M05, M09, M14, M18: M09 is empty
  and none of the five has a `hard` question. Size 10 also needs M07,
  M12 and M20.
- Yield: 12 accepted of 16 Matemáticas attempts for 49 calls (about 4.1
  calls per accepted question). LLM requests: 19 on 2026-11-02, 0 on
  2026-11-03 (limit 50 a day, shared with practices).
- Blockers found: review sampling requires a filled batch and seeder
  output is held until the batch passes, so a pilot released nothing;
  the run generated gaps in plan order and could not target an objective.

## Change

- `app/practice/seeding.py`: `run(objective=...)`; `item_review_export`,
  `item_review_record`; sample verdicts count only from the sampling time;
  `report` adds `individually_approved`.
- `app/practice/bank.py`: `INDIVIDUALLY_APPROVED_SQL` in the serving rule.
- `app/practice/seed_bank.py`: `run --objective`, `item-review-sample`,
  `item-review-record`.
- Carries the T050 acceptance record (commit `074e133`).

## Deviations from the request

- Stricter serving rule than listed: an individual approval releases a
  question only while the batch review is `pending` and the question was
  never sampled. Found while testing: sample-round approvals are also
  `approved` rows, so the plain rule released sampled questions of a
  failed batch and of a batch held again after a post-release quarantine.
- The batch sample re-reviews a question even if it was individually
  approved before sampling, so the batch gate stays independent.
- `report` output gains one key (`individually_approved`); one existing
  test's exact-dict assertion was extended for it.

## Verification

- `tests/app/test_bank_seeding.py`: 20 passed (13 T047 tests unchanged in
  substance, 7 new): targeted generation and refusal, resume, open-batch
  review, individual eligibility via `eligible` and `candidates` (bank-only
  path), all-or-nothing verdicts, quarantine after approval and the held
  replacement, individual approvals never passing the gate, failed and
  re-held batches never released by sample approvals.
- Full gate `bash .ace/scripts/verify.sh`: `VERIFY_RESULT=pass gate=all`
  (933 passed, 9 skipped; lint passed), logs
  `.ace/logs/verify/20261103-160329-287`.
