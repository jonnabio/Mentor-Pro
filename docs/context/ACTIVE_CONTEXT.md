# Active Context: Session Handoff 2026-11-06

## Session Metadata

- **Last Updated:** 2026-11-06 (T055 released and deployed as
  `v2026.11.05-2`, closed by the PO; T054 M09 question quarantined
  `level` by the tutor; session end)
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

- **T051–T054** (earlier this session window): targeted seeding
  (`v2026.11.04-1`), T052 pilot stopped, T053 explicit generation model
  list (`v2026.11.05-1`), T054 live fallback pilot (1 M09 question).
  See [T053 record](../progress/2026-11-05-production-release.md),
  [T054 result](../progress/task_T054_result.md).
- **T055** paid generation only with adult approval, read-only credit
  checks, cost tracking, explicit `llm` migration L001 (ADR-009
  amendment T055). [T055 result](../progress/task_T055_result.md).
  - PR #53 (head `500c74b`, CI 42114069387) → `dev` `07d7238` (CI
    42117635772). Release PR #54 (CI 42119143155) → `main` `c865c2b`
    (CI 42120588276, Tag and Release green).
  - Tag `v2026.11.05-2`, digest
    `sha256:77d409027ded28ab12727b71ea0e763c8fd9489008a5edae53c49efdb341d110`,
    manifest sha256 `1e7f3319…d29f` (identical on the server), writing
    schema `0001..0001`.
  - Deployment `PO-T055-2026-11-05` (window `T055-2026-11-05`):
    preflight `DEPLOY COMPATIBLE`; backup
    `mentor_pro_2026-11-05_223031.dump` (31 tables, 984 rows, sha256
    `5ea6c54c…4549`) `VERIFY OK`.
  - L001 from the released digest (one-shot `--rm` container on
    `mentor-pro_default`, `DATABASE_URL` and `PGPASSWORD` passed
    through): `base` → dry run (249 usage rows, digest `79a561d8…`) →
    applied once → `current`; 249 rows, same digest; 0 authorizations.
    The first status attempt failed on a missing password and changed
    nothing.
  - `DEPLOY OK`, `STATUS HEALTHY`, smoke 9/9; cost report works; `paid
    list` empty; `paid estimate` refused ("paid generation is
    disabled").
  - PO decision: **T055 CLOSED** (2026-11-05).
- **T054 M09 review** (`PO-T054-M09-REVIEW-2026-11-06`): the tutor
  confirmed `quarantined` / `level` for `req-74baf4b32a7144eb` (cell 41,
  E1, medium; mathematically correct, but the table gives the
  definitions, so it is closer to easy). Recorded once with
  `item-review-record --reviewer tutor` (`recorded 1, quarantined 1`).
  Cell 41 is a gap again; batch still `open`/`pending`; `STATUS
  HEALTHY`, smoke 9/9.

### Current State

- **Production** (macedonianserver): `v2026.11.05-2`
  (`77d40902…d110`) for app and tutor, `postgres:17.6`; writing schema
  `current 0001`; `llm` migration L001 `current`; 9 dumps (latest
  `mentor_pro_2026-11-05_223031.dump`).
  - `OPENROUTER_QUESTION_GENERATION_MODELS=nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-26b-a4b-it:free`.
  - `MENTOR_PRO_BANK_ONLY_ENABLED` absent (off); `/api/subjects`
    `bank_only: false`, sizes `[5]`.
  - Paid generation off: `OPENROUTER_ALLOW_PAID`, `OPENROUTER_PAID_MODEL`,
    `OPENROUTER_PAID_MAX_USD_PER_OPERATION` and
    `OPENROUTER_MANAGEMENT_KEY` absent. Daily limits 0 USD, 200 requests.
  - Rollback target: `v2026.11.05-1` (`c1e6ba1a…e112`), same writing
    schema, compatible with the migrated `llm` schema.
- **Bank:** batch `bb-matematicas-cd792836` `open`/`pending`; 6/100
  cells filled (6 adopted), 1 deactivated (the quarantined M09 item),
  0 generated, 0 held. M09 0/5. Eligible Matemáticas inventory last
  recorded as 12 (not re-counted after the quarantine; the item was
  never servable, so it should be unchanged). Review file
  `~/mentor-pro-review/T054-M09-2026-11-05.json` holds the verdict
  (private).
- **Repository:** `main` `c865c2b`; `dev` synced with `main` by the
  session-end handoff PR (this file).
- **Tracker:** T053 `verified`; T054, T055 `done` (T055 closed by the
  PO); T052 `pending` (superseded by T054); T034, T035 pending.
- **Locks:** none (no seeding advisory lock, no lane claim, no paid
  operation `in_use`).

### Next Steps

1. Record the T055 deployment evidence and closure in
   `docs/progress/task_T055_result.md` and `tasks.json` (status
   `verified`) inside the next functional PR, as the PO asked (not a
   docs-only PR).
2. With separate PO authorization, run targeted free seeding: M09
   (cell 41 and others), M05, M14, M18 and a `hard` cell, so size-5
   bank-only practice can be composed. Export each new question for
   individual tutor review.
3. Re-count the eligible Matemáticas inventory (read-only) at the start
   of that work.
4. Enabling paid approval in production (`OPENROUTER_ALLOW_PAID`,
   `OPENROUTER_PAID_MODEL`, `OPENROUTER_PAID_MAX_USD_PER_OPERATION`,
   optional management key) remains a separate administrator step under
   PO authorization.
5. Maintenance candidates: T035 (tutor exit 78 for short tokens), T034
   (deterministic practice-set test), CI on PRs into `dev`. Stage 6.3
   close: ADR-030 criterion 8 (restart part not yet shown).

### Blockers/Issues

- **Bank-only blocker:** size 5 needs servable questions for M01, M05,
  M09, M14, M18 and a `hard` question. M05, M09, M14, M18 have none.
- **Provider capacity (T054):** Gemma 4 26B free returned HTTP 429 on
  all 6 requests; Nemotron 3 Ultra truncated 2 of 3 generations at 4,000
  tokens. An accepted question cost up to 5 calls; cell 41 has 6 failed
  attempts.
- **Generator difficulty calibration:** the M09 `medium` item was really
  `easy` (definitions supplied in the stimulus). Expect more `level`
  quarantines until prompts are tightened.
- **Pending PO decision:** the sudo rule covers every `mentorpro`
  command, including `migrate`, `rollback`, `maintenance`, `rehearse`
  and `adopt-legacy`. Recommended (2026-11-01, not applied): allow
  passwordless only `status`, `smoke`, `backup`, `verify-backup *`,
  `preflight *` and `deploy *`. Administrator change (`visudo -f`, then
  `visudo -c` and `sudo -n -l`).
- **Root-owned tool copy:** when a release changes `deploy/`, the
  administrator must re-run the three `sudo install` commands before
  deploying.
- **T046 limit:** the link works only on the house Wi-Fi (or with 8080
  tunnelled too). In local development it points at production.
- Never run a pre-T036 image on the migrated database. Recovery after a
  failed migration is the G3 restore, a PO decision. The protected dump
  is `mentor_pro_2026-10-31_170927.dump`.
- `migrate rollback` (L001) refuses once any authorization or new-column
  data exists; recovery is then from the backup, by PO decision.
- T035, T034 pending.
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
- **`llm` migrations:** `docker run --rm --network mentor-pro_default -e
  DATABASE_URL -e PGPASSWORD --entrypoint python <image@digest> -m
  app.llm.migrate status|apply [--dry-run]`, with both variables taken
  from the app container and never printed. Always after a verified
  backup.
- **Review recording:** copy the decisions file into the app container
  (`docker cp`), run `python -m app.practice.seed_bank
  item-review-record --subject matematicas --decisions <file> --reviewer
  tutor` once, delete the copy, then `seed_bank report --cells`. Only a
  verdict confirmed by the human tutor may be recorded.
- **Release flow:** feature PR into `dev`, then a `dev` → `main` PR
  (merge with `--match-head-commit`). The `main` run tags, publishes to
  GHCR and creates the GitHub Release; `dev` runs skip Tag and Release.
  A release PR may come from a handoff branch (`dev` plus the docs
  record); sync `dev` from `main` afterwards.
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
