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
  calling `deploy/mentorpro-replenish-tick.sh` (PO review correction):
  keeps the real exit status of `replenish tick`; logs one classified
  `RESULT=` line (`OK`, `SKIPPED`, `TICK_FAILED` 5, `ERROR` rc,
  `CONTAINER_MISSING` 20, `DOCKER_ERROR` 21, `LOG_ERROR` 22); on failure
  appends at most 20 output lines; redacts key/token/password values,
  bearer tokens and URL credentials; creates the log directory (700, log
  600); `--check` verifies directory and container before activation.
  Tests: `tests/app/test_replenish_tick_wrapper.py` (12, fake `docker`).
  No change to the root-owned deployment tool or `compose.yml`.
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
2. Install the wrapper, run `--check`, install the cron line (runbook M).
3. Administrator adds `MENTOR_PRO_REPLENISH_SCHEDULE=on` to
   `/etc/mentor-pro/app.env` and force-recreates the app.
4. Verify the first tick in `schedule-status` and the log.

## Tutor Review PO-QBANK-REVIEW-20-2026-11-12

Targeted free generation for 15 gap objectives (149 calls) produced 20
candidates; M08, M15, EL05 and C16 produced none. The tutor reviewed
all 20; each verdict was recorded once (`item-review-record --reviewer
tutor`), 9 approved and 11 quarantined. The review schema stores the
reason code only; the tutor's explanations are kept here.

| Request | Objective | Verdict | Code | Tutor reason |
| --- | --- | --- | --- | --- |
| `req-e07cdca09b3f4faa` | M06 medium | approved | | |
| `req-ddf0888559fb4de3` | M11 easy | approved | | |
| `req-10c4d5e77b4144da` | EL07 medium | approved | | |
| `req-edb10af3c21949d2` | EL07 hard | approved | | |
| `req-408a2e676e1f4bba` | C08 medium | approved | | |
| `req-75717ae8cdba43e4` | C12 easy | approved | | |
| `req-272f773275f149a6` | ES06 hard | approved | | |
| `req-65c9daa5baed4a10` | ES06 medium | approved | | |
| `req-a8b7242764bd4bc9` | ES18 easy | approved | | |
| `req-9925955af01246a1` | M11 hard | quarantined | `other` | Asks for an approximate area although the exact area is directly calculable. |
| `req-51357afcbb374967` | M21 hard | quarantined | `off_curriculum` | Tests compound outcome counting, not recognising chance. |
| `req-cb718ca19ce24143` | EL04 easy | quarantined | `other` | The passage supplies the answer verbatim. |
| `req-1615d3d11a91416b` | EL04 medium | quarantined | `ambiguous` | Several consequences; "inmediata" does not single out the key. |
| `req-2e7e508364d845cd` | C04 easy | quarantined | `other` | The key repeats the question wording; excessively cued. |
| `req-1e10d7acd9f7482c` | C08 hard | quarantined | `other` | Guaria morada is nectarless and pollinated by orchid bees, not honeybees. |
| `req-a5a61444392244c9` | ES06 easy | quarantined | `other` | Misleading oak-forest ecology and Valle Central association. |
| `req-3ce3e99a85ec4923` | ES18 medium | quarantined | `other` | Near-duplicate of `req-a8b7242764bd4bc9`. |
| `req-268ae6f6bf6d4b7a` | ES18 hard | quarantined | `level` | Weak distractors for hard difficulty. |
| `req-3bdf87e3e1f1439a` | ES24 medium | quarantined | `ambiguous` | More than one option names a relevant Liberal Reform; imprecise wording. |
| `req-ad4be33c895b41a9` | ES24 hard | quarantined | `other` | Attributes state secularisation to the 1871 Constitution, conflating later reforms. |

After recording (real composer, `compose-check` and `POST
/api/practice/availability`; pending review 0 in every subject):

- Eligible: Matemáticas 42, Estudios Sociales 20, Español 10, Ciencias 10.
- Matemáticas mixed `[5, 10]` from the bank; size 15 still lacks M08,
  M15, M21.
- Size 5 from the bank still lacks Español EL04, EL05; Ciencias C04,
  C16; Estudios Sociales ES24. These subjects keep generated size 5.
