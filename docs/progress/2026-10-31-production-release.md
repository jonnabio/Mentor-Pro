# Production Release v2026.10.30-1 (Steps D and E)

- **Date:** 2026-10-31
- **Role:** Architect
- **Authorization:** PO message "Expedite Production Upgrade"
  (2026-10-31), recorded as `PO-expedite-upgrade-2026-10-31`
  (`authorization_verified=no`; a reference string does not prove the
  approval).
- **Operators:** the administrator (interactive `sudo`; the agent never
  requested or saw the password) and the agent (`jonnabio`, no `sudo`).
- **Result:** release `v2026.10.30-1` (commit `094a014`, digest
  `sha256:7702469e442596d56b1425bfc5a0d189bcc1f21a2fd3972d47f079b932423538`)
  running in production; schema `current 0001`; `STATUS HEALTHY`.
  Real-user acceptance of the revision cycle (step F) is **not done**.

## Before the window

| Item | Result |
| --- | --- |
| PR #35 | merged as `71d6830`; `dev` CI 41220406734 green (773 passed, `MANIFEST OK dev-71d6830`) |
| D0 | production equal to the step C end state; smoke 9/9 |
| D1 | manifest copied to `/opt/mentor-pro/manifests/v2026.10.30-1.json`, sha256 `384d9e3e…54ff` on both sides; image pulled by digest, `RepoDigests` exact, labels `v2026.10.30-1`, `094a014…`, schema `0001..0001`; registry tag `v2026.10.30-1` → `7702469e…3538` |
| Preconditions | administrator present, the student not using Mentor Pro, outage announced (PO, 2026-10-31) |

## Step D: timing rehearsal (window `stepD-2026-10-31`)

| Step | Time (UTC) | Result |
| --- | --- | --- |
| D2 `maintenance start` | 16:54:06 | OK; app and tutor stopped, PostgreSQL running |
| D3 `backup` | 16:54:07–16:54:11 | `BACKUP OK` `mentor_pro_2026-10-31_165407.dump`, 25 tables, 901 rows, 194,166 bytes, sha256 `c286e99f…b234`; restore check passed, verify container removed |
| D4 `rehearse` | 16:54:11–16:54:23 | `REHEARSAL OK`, total 9.3 s (dry run 0.6, apply 0.7, verify 0.3, start app and tutor 3.5, smoke 0.4); `legacy` → `current 0001`; counts kept; isolation and in-network smoke 9/9; cleanup verified |
| D5 `maintenance end` | 16:54:23–16:54:30 | app and tutor recreated on `5d69fe6c…1137` with health checks, `healthy`, smoke 9/9; schema unchanged (`legacy`) |
| Downtime | | **0.4 min** |
| D6/D7 | | `STATUS INCOMPLETE (1 item(s) unknown)` (schema, pre-T036 image); smoke 9/9; postgres container and start time unchanged; `compose.deploy.yml` and `release.env` unchanged; no rehearsal resource left |

## Step E: production upgrade (window `stepE-2026-10-31`)

| Step | Time (UTC) | Result |
| --- | --- | --- |
| E1 `maintenance start` | 17:09:27 | OK |
| E2 `backup` | 17:09:27–17:09:30 | `BACKUP OK` `mentor_pro_2026-10-31_170927.dump`, 25 tables, 901 rows, 194,166 bytes, sha256 `a8e923b9…c664` (pre-migration backup, kept) |
| E3 `rehearse` | 17:09:30–17:09:42 | `REHEARSAL OK` on that dump, total 9.4 s; cleanup verified |
| E4 `migrate` | 17:09:42–17:09:56 | dry run 0.6 s, apply 0.8 s, verify 0.3 s, deploy 9.4 s; `DEPLOY OK`; `MIGRATE OK: schema current 0001, 1 attempt-1 records, all writing records and relationships kept, nothing changed outside the migration` |
| Downtime | | **0.5 min** (limit 60) |
| `status` | | release.env and app/tutor on `7702469e…3538`, all three `running healthy`, schema current, student and tutor 200, `STATUS HEALTHY` |

`RELEASES` lines: `maintenance-start`, `rehearse`, `deploy`
(`previous=…5d69fe6c…1137`), `migrate` (`legacy:none->current:0001`,
`attempts_created=1`). `release.env.previous` holds the old digest.

## Phase 3 verification (agent, read only)

| Check | Result |
| --- | --- |
| Containers | app `ecf1cf49…` and tutor `d99de9fd…` on `7702469e…3538`, `healthy`, restarts 0, labels `v2026.10.30-1` / `094a014…`; ports unchanged (app `127.0.0.1:8080`, `192.168.50.229:8080`; tutor `127.0.0.1:8081`); postgres `94bded0c…` unchanged since 2026-10-25, `healthy` |
| Schema | ledger `0001_student_attempts`; `uq_submission_exercise` removed |
| Data | drafts 1, submissions 1, evaluations 1, criterion scores 2 (as before); attempts 1; the evaluation still linked to its submission; the submission on an attempt; table counts 25 → 27 (the two new writing tables) |
| Smoke | `SMOKE PASS (9/9)`; dashboard 200 |
| Tutor boundary | tutor API with a wrong token 403, without a token 403; `/tutor` on the student service 404; tutor port not reachable on the Wi-Fi address |

Progress is checked through the dashboard (200) and the unchanged
records; the student's progress view itself is part of step F.

## Deviations

- `deploy/__pycache__/` was created by the agent's read-only import check
  on 2026-10-30 (Python bytecode cache; harmless, left in place).
- None in steps D or E.

## Step F: real-user acceptance of the revision cycle (2026-10-31)

**ACCEPTED** by the PO: all eight functional checks passed. The evidence
is kept by source; an observation is not reported as independent
verification.

| # | Check | Evidence |
| --- | --- | --- |
| 1 | Original response preserved | screenshot-confirmed |
| 2 | Version 2 submitted | screenshot-confirmed; database: attempt 2 has 1 submission, chained to attempt 1 |
| 3 | Improvement pending tutor review | screenshot-confirmed |
| 4 | Tutor queue recognizes version 2 | screenshot-confirmed |
| 5 | Original evaluation remains completed | screenshot-confirmed; database: attempt 1 evaluation `completed`, 2 criterion scores |
| 6 | Tutor re-evaluation completed | PO observation; database (read-only counts, agent): attempt 2 evaluation `completed`, 2 criterion scores |
| 7 | Student criterion-level comparison | PO observation only |
| 8 | Progress counters and persistence | PO observation only. App and tutor have not restarted since the deployment (started 17:09:50Z, restarts 0), so persistence across a restart is not independently verified |

Database figures are counts and statuses only, read with
`default_transaction_read_only = on`; no rows or text were read.

## Not done

- Step G: I8 release closure ([plan](../planning/2026-10-31-step-g-release-closure-plan.md)).
