# T047 Result: Question Bank Foundation (Increment 1)

- **Date:** 2026-11-01
- **Role:** Developer
- **Status:** Done (PR into `dev`, awaiting PO review). Mocked LLM only:
  no live generation, no production seeding, no deployment.
- **Decision record:** [ADR-034](../adr/ADR-034-question-bank-foundation.md)

## Change

- `app/practice/bank.py`: additive tables `bank_batch`, `bank_batch_item`,
  `bank_review_sample`, `bank_item_review` with their unique indexes.
  `eligible()` now excludes quarantined questions and holds seeder output
  until its batch review passes (`include_held` for the seeder only).
- `app/practice/seeding.py` (new): fixed exact-cell plan, adoption, gap-only
  generation through the unchanged `generate_set`, advisory lock with
  ownership checks, coverage and readiness report, reproducible review
  sample, all-or-nothing verdicts, review gate, question quarantine.
- `app/practice/seed_bank.py` (new): CLI `run`, `report`, `review-sample`,
  `review-record`, `quarantine`; exit codes 0, 1, 3 (`SEED BUSY`), 4
  (`LOCK LOST`).
- Runbook section L; ADR-034; tracker entry.

Unchanged: `app/generation/pipeline.py` (RCA-002 guard), writing code,
practice routes, student UI, LLM settings and budget.

## Verification

| Requirement | Test (`tests/app/test_bank_seeding.py`) |
| ----------- | --------------------------------------- |
| Fixed plan, gaps reported, no substitution, resume keeps the batch | `test_plan_is_fixed_and_gaps_are_reported_without_substitution` |
| Exact cells filled; generated questions held from practices | `test_generation_fills_every_exact_cell_and_holds_new_questions` |
| Budget stop, then gap-only resume, earlier links untouched | `test_budget_stop_then_resume_generates_only_the_gaps` |
| Adoption refuses near duplicates, wrong cells, quarantined and other-batch output | `test_adoption_takes_only_eligible_exact_cell_non_duplicate_unquarantined_questions` |
| Competing run refused at once; lock per subject | `test_a_competing_run_is_refused_immediately` |
| Crash releases the lock; unlinked output recovered | `test_a_crashed_run_releases_the_lock_and_its_unlinked_output_is_recovered` |
| Lock loss mid-run stops before any write | `test_lock_loss_stops_the_run_before_any_further_write` |
| Database rejects double links and a second current batch | `test_database_constraints_reject_double_links_and_a_second_current_batch` |
| Reproducible sample spread over difficulties | `test_sampling_is_reproducible_and_spread_over_difficulties` |
| Quarantine, reviewed replacement, release, evidence kept | `test_review_gate_quarantines_reviews_the_replacement_and_keeps_all_evidence` |
| Three quarantines fail the batch; still held | `test_three_quarantined_sample_questions_fail_the_batch` |
| Verdicts all-or-nothing | `test_review_decisions_are_all_or_nothing` |
| Quarantine after release re-holds the batch until the replacement is reviewed | `test_a_quarantine_after_release_holds_the_batch_until_the_replacement_is_reviewed` |

- New file: 13 passed. Related suites (question bank, practice API,
  mastery, practice set, generation): 103 passed.
- ACE gate: `VERIFY_RESULT=pass gate=all`; pytest 892 passed, 6 skipped
  (baseline before T047: 879 passed, 6 skipped).

## Limits

- At the unchanged budget a 100-question batch needs weeks of runs; the
  calls per accepted question will be measured on the first authorized run.
- The tutor's review is a manual step; readiness waits for it.
- Practices still use exact cell matching (ADR-014). Configurable sizes are
  Increment 2.
