# T067 Result: Coverage-Driven Generation Priority

- **Role:** Developer (PO authorization PO-QBANK-COMPLETION-2026-11-14)
- **Status:** implemented and tested; PO review of the PR required before
  release
- **Decision:** [ADR-036 amendment](../adr/ADR-036-question-bank-phase-b.md)

## Problem

- `replenishment.run` took open requests by trigger, then objective code:
  nearly every cell has a `coverage` request, so generation went
  alphabetically (Matemáticas M04, M05, M06 ... before the M08, M15, M21
  that block size 15).
- One objective could spend the whole tick (`tick-39d20217e660`: all 10
  calls on one Español objective).
- Within an objective the seeder followed plan order, often a hard cell
  first, the level most often rejected for `difficulty_match`.

## Why M08, M15, EL05 and C16 yielded nothing (production, read-only)

Each had 10 calls on 2026-11-12, giving only 2-3 attempts. Of the 12
recent attempts reported as `rubric unavailable` or `independent solve
unavailable`, 11 were the run's own call cap: the question was generated,
then its solve or review was `budget_blocked`, so the generation call was
lost. One was a truncated review. The remaining rejections were
`rubric:difficulty_match` (hard cells) and one `generation exhausted` (all
free models failing at that moment). No content or prompt defect specific
to these objectives was found.

## Change

- `app/practice/coverage.py`: `report` (real composer: sizes 5-30 mixed
  and single-level size 5, per-objective and per-level shortfalls) and
  `priorities` (tiers: smallest missing size; objectives with nothing;
  single-level size 5; larger sizes; depth; performance last).
- `replenishment.run`: objectives in priority order, at most
  `MENTOR_PRO_REPLENISH_OBJECTIVE_CALLS` (default 5) per objective; a
  second pass gives leftover calls to objectives the cap stopped before
  any candidate; each run records tier, size and levels.
- `replenishment.yields` and `priority`; CLI `replenish coverage` and
  `replenish yield` (counts and reason codes only).
- Scheduler: a subject gets at most `max(objective calls, ceil(tick /
  subjects))` of a tick; tick detail lists each objective's tier,
  levels, calls and yield.
- `seeding.run(prefer=...)` orders an objective's planned gap cells by
  level; it never adds a cell.
- Whole attempts: `SetLimits.attempt_calls` / `BudgetGate.covers_attempt`.
  Seeding sets 3 (generation, solve, review); live practice sets keep 0
  (unchanged).

## Before and After (production data, read-only, 2026-11-14)

| Subject | Smallest missing | Old first objectives | New first objectives |
| --- | --- | --- | --- |
| Matemáticas | 15 | M04, M05, M06, M07 | M08, M15, M21 |
| Español | 5 | EL02, EL03, EL04 | EL04, EL05 |
| Ciencias | 5 | C02, C03, C04 | C04, C16 |
| Estudios Sociales | 5 | ES03, ES04, ES05 | ES24 |

The eight PO priority objectives are exactly the first tier in each
subject. Calls per objective per pass: before up to the whole tick; after
at most 5, and a subject at most 5 of a 10-call tick.

## Tests

- `tests/app/test_coverage_priority.py` (11): tier order, larger sizes,
  low-yield ordering, level choice, level-only shortages, reason codes,
  the real composer on the test database, run order, per-objective cap and
  second pass, run call bound, setting bounds, seeder level preference
  through a real seeding run.
- `tests/app/test_practice_set.py`: the whole-attempt guard at caps 3, 4,
  5, 7 leaves no generated question unchecked; without it, the same caps
  do (control); default off.
- `tests/app/test_replenish_schedule.py`: subject share per tick.

## Regression Guards

RCA-002 (`app/generation/pipeline.py`): the attempt loop gains a budget
check before an attempt; verdict rules, blind solve and proof rules are
unchanged. `tests/ace/test_item_checker.py` and
`tests/app/test_generation.py` pass.

## Limits

The 100-cell plan per subject is unchanged; sizes 25-30 need more cells
than some subjects plan for one objective (see `replenish coverage`).
Raising it needs PO authorization.
