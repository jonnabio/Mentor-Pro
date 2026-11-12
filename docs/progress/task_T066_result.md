# T066 Result: Scheduled Replenishment

- **Role:** Developer (PO authorization PO-QBANK-CONTINUATION-2026-11-12)
- **Status:** implemented and tested; PO review of the PR required before
  release and activation
- **Decision:** [ADR-036 amendment](../adr/ADR-036-question-bank-phase-b.md)

## Problem

T061 opens replenishment requests from inventory and performance, and
`replenish run` generates candidates for them. Nothing started a run: an
administrator had to invoke every one. Replenishment was a request
tracker, not an operational workflow.

## Change

- `app/practice/replenish_schedule.py`: `tick()` runs one bounded pass:
  - skipped (and recorded) when `MENTOR_PRO_REPLENISH_SCHEDULE` is not
    `on` (default `off`) or the administrator paused it;
  - a global `pg_try_advisory_lock` (key `4047, 0`): a concurrent tick is
    recorded as `skipped: busy` and runs nothing;
  - `replenishment.run` per subject in rotation from where the previous
    tick ended, until `MENTOR_PRO_REPLENISH_TICK_CALLS` (default 10, 1-50)
    calls are spent or a `daily_budget` or `provider_rate_limited` stop;
  - a subject held by another seeding run is skipped, the tick continues;
  - any other error ends the tick as `failed` with the error recorded; a
    tick left `running` for two hours is marked `abandoned`.
- Tables `generation.replenish_schedule` (single row: pause, reason,
  rotation index) and `generation.replenish_tick` (status, calls,
  generated, per-subject detail, error), created `IF NOT EXISTS`; no
  versioned migration, no existing row changes.
- `replenish tick | schedule-status | pause --reason | resume`; a failed
  tick exits 5.
- `deploy/mentorpro-replenish.cron`: user crontab line, every 3 hours,
  one log line per tick. No change to the root-owned deployment tool or
  `compose.yml` (settings arrive through `env_file`).
- Runbook section M.

## Guarantees Kept

Each subject pass is the existing `replenishment.run`: one pending request
per cell (unique index), candidates awaiting review are never generated
again, planned gap cells of the fixed 100-cell plan only, the per-subject
seeding lock, the shared daily budget, free models only (no paid opener).
No verdict is ever recorded: generated candidates stay held from
practices until the tutor approves them.

## Tests

`tests/app/test_replenish_schedule.py` (mentor_pro_test, fake runs or a
mocked LLM):

- settings default off and bounded;
- disabled and paused ticks run nothing; resume needs no restart;
- a held schedule lock skips the tick as `busy`; released with its
  connection;
- the call budget per tick, rotation across ticks, budget stop, busy
  subject skipped;
- failures recorded with the error, consecutive failures counted (skips
  ignored), stale `running` ticks marked `abandoned`;
- end to end through `replenishment.run` and the seeder: the first tick
  generates held candidates (pending review equals generated), the
  second generates nothing while they await review.

## Observation (not changed here)

`replenishment.run` generates per objective and marks every open request
of that objective `candidates_generated`, including difficulties whose
cell received no candidate. The next assessment closes those as
`reviewed` although nothing was reviewed; a later assessment reopens the
cell if it still triggers. No duplicate generation results, but the close
reason is misleading in the tutor view. Follow-up candidate.

## Activation (after PO review and release)

1. Release and deploy through the normal workflow.
2. Install the cron line (runbook M).
3. Administrator adds `MENTOR_PRO_REPLENISH_SCHEDULE=on` to
   `/etc/mentor-pro/app.env` and force-recreates the app.
4. Verify the first tick in `schedule-status` and the log.
