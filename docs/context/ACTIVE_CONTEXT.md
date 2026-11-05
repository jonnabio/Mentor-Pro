# Active Context: Session Handoff 2026-11-05

## Session Metadata

- **Last Updated:** 2026-11-05 (T055 paid approval and cost tracking:
  feature PR into `dev`; not released; T054 M09 question still awaiting
  tutor review)
- **Active Role:** Developer
- **Mode:** EXECUTION
- **Earlier history:** T006–T050, deployment stages 6.1–6.3, ADR-030 to
  ADR-033: see `docs/progress/task_T0xx_result.md`, `docs/planning/`,
  release records in `docs/progress/` and this file's Git history.

## Current Objective

Matemáticas question bank population and activation (fast track). Goal:
five-question bank-only Matemáticas practice (ADR-035).

## Handoff Summary

### Completed

- **T051** (targeted seeding, individual review; ADR-034 amendment):
  released and deployed as `v2026.11.04-1` (2026-11-04 01:20 UTC).
  [Record](../progress/2026-11-04-production-release.md).
- **T052** M09 pilot stopped: 11/11 Nemotron generation calls timed out;
  the configured fallback (minimax) had been delisted.
  [T052 result](../progress/task_T052_result.md).
- **T053** explicit generation model list
  `OPENROUTER_QUESTION_GENERATION_MODELS` (ADR-009 amendment): PR #50 →
  `dev` `647af18`; release PR #51 → `main` `27fd409` (CI 42057883562);
  tag `v2026.11.05-1`, digest `c1e6ba1a…e112`. Administrator added the
  setting (backup `app.env.bak-T053`). Deployed 2026-11-05 18:54 UTC under
  `PO-T053-2026-11-05`; smoke 9/9, `STATUS HEALTHY`.
  [Release record](../progress/2026-11-05-production-release.md).
- **T054** live fallback and M09 pilot (`PO-T054-M09-2026-11-05`): 10
  calls, 244 s, 1 question accepted (M09 cell 41, medium, by Nemotron);
  Gemma reached 6 times, all HTTP 429. Question exported for tutor review;
  no verdict. [T054 result](../progress/task_T054_result.md).
- Handoff PR #52 merged into `dev` as `ff5fb8b` (`dev` synced with
  `main` `27fd409`).
- **T055** paid generation only with adult approval, read-only
  credit checks and cost tracking (ADR-009 amendment T055). PR #53 (head
  `500c74b`, CI 42114069387) merged into `dev` as `07d7238` (`dev` CI
  42117635772 green). Release and deployment authorized under
  `PO-T055-2026-11-05` (in progress).
  [T055 result](../progress/task_T055_result.md).

### Current State

- **Production** (macedonianserver): `v2026.11.05-1`
  (`c1e6ba1a…e112`) for app and tutor, `postgres:17.6`; schema `current
  0001`; 8 dumps (latest `mentor_pro_2026-11-05_185406.dump`).
  - `OPENROUTER_QUESTION_GENERATION_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-26b-a4b-it:free`;
    `MENTOR_PRO_BANK_ONLY_ENABLED` absent (off); `/api/subjects`
    `bank_only: false`, sizes `[5]`. Daily request limit 200 (23 used on
    2026-11-05).
  - Rollback target: `v2026.11.04-1` (`6a661861…c5d1`), same schema.
- **Bank:** batch `bb-matematicas-cd792836` `open`/`pending`, 7/100 cells
  (6 adopted, 1 generated and held). M09 1/5. Eligible Matemáticas
  inventory 12. Review file
  `~/mentor-pro-review/T054-M09-2026-11-05.json` on the server (private).
- **Repository:** `main` `27fd409`; `dev` `07d7238` (T055); release PR
  from `handoff/T055-merged` into `main`.
- **Tracker:** T053 `verified`; T054, T055 `done`; T052 `pending`
  (superseded by T054); T034, T035 pending.
- **Paid generation:** off in production and staying off. T055 adds no
  DDL at start-up. The explicit migration `L001_paid_cost_tracking`
  (`python -m app.llm.migrate apply`, after a verified backup, separately
  authorized) adds `llm.paid_authorization` and six nullable
  `llm.usage_record` columns. Without it the image runs free-only.
  Writing schema `0001` and `deploy/` are unchanged.
- **Locks:** none (no seeding advisory lock, no lane claim).

### Next Steps

1. Tutor reviews the exported M09 question; record the verdict with
   `seed_bank item-review-record --subject matematicas --decisions <file>`
   (needs PO authorization).
2. T055 release, L001 and deployment (`PO-T055-2026-11-05`). Enabling
   paid approval in production (`OPENROUTER_ALLOW_PAID`,
   `OPENROUTER_PAID_MODEL`, `OPENROUTER_PAID_MAX_USD_PER_OPERATION`,
   optional management key) remains a separate authorized step.
3. Continue seeding M05, M09, M14, M18 (and a `hard` cell, target 42) so
   size-5 bank-only practice can be composed; each run separately
   authorized.
4. Maintenance candidates: T035 (tutor exit 78 for short tokens), T034
   (deterministic practice-set test), CI on PRs into `dev`.
5. Stage 6.3 close: ADR-030 criterion 8 (restart part not yet shown).

### Blockers/Issues

- **Pending PO decision:** the sudo rule covers every `mentorpro`
  command, including `migrate`, `rollback`, `maintenance`, `rehearse`
  and `adopt-legacy`. Recommended (2026-11-01, not applied): allow
  passwordless only `status`, `smoke`, `backup`, `verify-backup *`,
  `preflight *` and `deploy *`, so the others fall back to the
  password-protected rule. Applying it is an administrator change
  (`visudo -f`, then `visudo -c` and `sudo -n -l`).
- **Root-owned tool copy:** when a release changes `deploy/`, the
  administrator must re-run the three `sudo install` commands before
  deploying. Otherwise the old tool runs.
- **T046 limit:** the link works only on the house Wi-Fi (or with 8080
  tunnelled too). In local development it points at production.
- Never run a pre-T036 image on the migrated database. Recovery after a
  failed migration is the G3 restore, a PO decision. The protected dump
  is `mentor_pro_2026-10-31_170927.dump`.
- **Provider capacity (T054):** Gemma 4 26B free returned HTTP 429 on
  all 6 requests; Nemotron 3 Ultra truncated 2 of 3 generations at 4,000
  tokens. An accepted question cost up to 5 calls.
- **Bank-only blocker:** size 5 needs servable questions for M01, M05,
  M09, M14, M18 and a `hard` question; M05, M14, M18 have none and M09's
  one question awaits review.
- T035, T034 pending (above).
- CI skips 102 tests (baseline workbook not in Git); a green run is not
  a full release gate.
- Production practice generation takes about 5 minutes and may return
  `partial` until the bank fills. No L5 writing exercises.
- No login on the app; the tutor boundary is a shared token plus the
  gateway address (ADR-024, ADR-031).
- A real reboot with Wi-Fi publication (`ip_nonlocal_bind`) is untested.
- The GHCR image is public, by decision.
- The student's first name appears in pushed commit `42adbe7`;
  rewriting it needs approval.
- Remote branch `origin/copilot/clean-repository` remains.
- Framework markdown lint debt (`docs/TODO-markdown-lint.md`).
- Older items (T017 quarantine review, RCA-003, draft limits,
  keyword-based checks, local `trust` auth, Edge automation): see this
  file's Git history at 2026-10-30.

### Notes

- **Deploy, unattended:**
  - `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`.
  - Sequence: `preflight "$M"`, `backup`, `verify-backup <full dump path>`,
    `deploy "$M" --backup <full path> --window <ref> --authorization <ref>`,
    then `status`.
  - References contain no spaces. Stop on any other result; never restore
    or roll back automatically.
  - Manifest: `gh release download <tag> -p release-manifest.json`, then
    `scp` to `/opt/mentor-pro/manifests/<tag>.json` and compare sha256.
- **Release flow:** feature PR into `dev`, then a `dev` → `main` PR
  (merge with `--match-head-commit`). The `main` run tags, publishes to
  GHCR and creates the GitHub Release; `dev` runs skip Tag and Release.
  `v2026.11.02-1` used a release PR from the handoff branch (`dev` plus
  the docs record); `dev` was then synced by a closure PR from `main`.
- **Switch check:** `/etc/mentor-pro` is root-only and production reads
  are blocked for the agent; the administrator runs `sudo grep -c
  '^MENTOR_PRO_BANK_ONLY_ENABLED=' /etc/mentor-pro/app.env` (expect `0`).
- **Server:** `ssh jonnabio@100.64.84.15` (docker group).
  - Student app: `127.0.0.1:8080` and `192.168.50.229:8080`.
  - Tutor: `127.0.0.1:8081` only, through
    `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`, then open
    `http://127.0.0.1:8081/tutor`.
- **Gate:** `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`,
  4–12 min). Run pytest with `.venv/Scripts/python.exe`. On Windows, edit
  accented text with the Edit tool, not heredocs.
- **Records:** merge SHAs and CI go in the next substantive docs update,
  not in a docs-only PR. Skip `scripts/pubs/check_lane.py` (another
  project).
- **Never:**
  - `docker compose down -v`, or `compose.deploy.yml`, which pins a
    pre-T036 image;
  - restoring over the live database;
  - printing env values, the token or tutor references;
  - putting the student's name in code, tests, commits or docs.
- Use only `mentor_pro_test` for tests. No synthetic production
  submissions.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-005)
