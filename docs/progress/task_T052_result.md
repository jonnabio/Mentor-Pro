# T052 Result: Matemáticas M09 Seeding Pilot (Stopped: Provider Timeouts)

- **Date:** 2026-11-05 (UTC)
- **Role:** Developer (operations)
- **Status:** Stopped, no question generated. Authorizations
  `PO-T052-M09-2026-11-04` (pilot, `--max-calls 10`) and
  `PO-T052-RECOVERY-2026-11-04` (probe, `--max-calls 1`).
- **Release:** `v2026.11.04-1`; bank-only off throughout; no
  configuration, limit or deployment change.

## Preflight (both runs)

- App and tutor on `6a661861…`, all containers healthy; no
  `MENTOR_PRO_BANK_ONLY_ENABLED` key; `/api/subjects` `bank_only: false`.
- Daily request limit in production: 200 (`OPENROUTER_MAX_REQUESTS_PER_DAY`).
- Pilot: no batch, no advisory lock, no running practice job. Probe:
  batch `bb-matematicas-cd792836` `open`/`pending`, no lock.

## Results

| Run | Elapsed | Calls sent | Outcome |
| --- | --- | --- | --- |
| Pilot `run --subject matematicas --objective M09 --max-calls 10` | 619 s | 10 | batch created; 6 cells adopted; 0 generated; `run_call_limit` |
| Probe `... --max-calls 1` | 64 s | 1 | 0 generated; `run_call_limit` |

- All 11 calls: `generation`, `nvidia/nemotron-3-ultra-550b-a55b:free`,
  free tier, `timeout` at about 60 s (60,010–60,217 ms), no output, cost
  $0. One further attempt per run was refused by the call cap
  (`budget_blocked`, not sent).
- Cells attempted: 41 (M09, E1, medium; 3 slot attempts of 3 calls each)
  and 42 (M09, E2, hard). No question reached validation.
- The same model generated normally from 2026-10-27 to 2026-11-02 (25 s
  average on 2026-11-02). OpenRouter's public endpoint data for it showed
  status `-2` and no latency data.
- **Root cause of the single-model exposure:** production lists
  `minimax/minimax-m3.1-flash:free` as the next free model, but it is no
  longer listed by OpenRouter and the router drops unlisted models
  silently; `nvidia/nemotron-3.5-super-vl:free` is excluded from
  generation. Fixed by T053 (ADR-009 amendment).

## State after the runs

- Batch `bb-matematicas-cd792836`: `open`, review `pending`, 6/100 cells
  (all adopted, already servable, all seen); M09 0/5.
- Matemáticas eligible inventory unchanged (12). Nothing to review; no
  verdicts recorded; no review file created.
- Bank-only feasibility (read-only, real composer): sizes 5 and 10 mixed
  short, `largest_available: 0`. Blocker: M09 has no question and none of
  M01, M05, M09, M14, M18 has a `hard` question (target cell 42).
- Note: an accepted question needs at least 2 calls (generation and
  review; a blind solve when the key is not proven), so a probe needs
  `--max-calls 3` to be able to produce one.
