# Active Context: Session Handoff 2026-10-31

## Session Metadata

- **Last Updated:** 2026-10-31 (session end: release `v2026.10.30-1`
  closed, T046 released as `v2026.10.31-1`)
- **Active Role:** Architect
- **Mode:** EXECUTION
- **Earlier history:** T006–T045, deployment stages 6.1–6.3, ADR-030 to
  ADR-033: see `docs/progress/task_T0xx_result.md`, `docs/planning/` and
  this file's Git history (handoff of 2026-10-30).

## Current Objective

None open. Production runs `v2026.10.31-1` (T046) on schema `0001`,
healthy. The next feature needs a PO decision.

## Handoff Summary

### Completed

- **Release `v2026.10.30-1` (T036–T039, T045) CLOSED.**
  - Step D rehearsal OK. Step E: production migrated to schema `0001`
    and deployed (downtime 0.5 min). Step F accepted by the PO.
  - Step G (I8), PR #37, merged as `a67523b` (`dev` CI 41246270688
    green). Its changes:
    - runbook section 0 rebuilt around `deploy/mentorpro`;
    - pre-T036 rollback prohibited;
    - protected pre-migration dump recorded;
    - obsolete server files listed, not removed;
    - ADR-033 Accepted.
  - Evidence: [release record](../progress/2026-10-31-production-release.md).
- **T046 (tutor "Volver a Mentor Pro" link) done and deployed.**
  - Change: a link to `http://192.168.50.229:8080/` (fixed LAN URL, PO
    decision) plus one regression test. Authentication and isolation
    unchanged.
  - PR #38 merged into `dev` as `ec2b838` (CI 41249721154). Release PR
    #39 merged into `main` as `4586a24`, pinned to head `ec2b838` (CI
    41250517110 and 41251160982 green).
  - Release `v2026.10.31-1`: protected tag, GitHub Release and manifest
    (sha256 `f29acb33…85af`), digest `sha256:e7dd6edb…3215`.
  - Deployed 2026-10-31 23:26 UTC (window `t046-2026-10-31`,
    authorization `PO-urgent-T046-release-2026-10-31`). The sequence:
    `PREFLIGHT OK`; backup `mentor_pro_2026-10-31_232534.dump`
    (sha256 `3ce142a3…427e`, `VERIFY OK`); `DEPLOY OK`; smoke 9/9;
    `STATUS HEALTHY`.
  - The link is present on the production tutor page, and its target
    returns 200. [T046 result](../progress/task_T046_result.md).
- **Unattended deployment enabled** (PO-authorized, 2026-10-31):
  - The administrator installed a root-owned copy of the tool in
    `/usr/local/lib/mentor-pro/`.
  - The sudo rule `/etc/sudoers.d/mentor-pro` lets `jonnabio` run only
    that tool without a password (`visudo -c` OK).
  - The agent now deploys with `sudo -n`. Runbook section 0 updated.

### Current State

- **Production** (macedonianserver):
  - `v2026.10.31-1` (`e7dd6edb…3215`) for app and tutor, `postgres:17.6`.
  - Schema `current 0001`; 5 dumps (732K, no automatic deletion).
  - Previous release `v2026.10.30-1` (`7702469e…3538`) is the allowed
    rollback target.
- **Repository:** `dev` and `main` contain everything up to
  `4586a24`, plus this handoff PR. No open feature branches.
- **Tracker:** T046 `done`. T034 and T035 pending (maintenance).

### Next Steps

1. Ask the PO for the next feature. Exactly one at a time, one PR into
   `dev`, deployment only with a separate release authorization.
2. Maintenance candidates, each a separate verified change:
   - T035: tutor exit 78 for tokens of 1–15 characters.
   - T034: deterministic practice-set test.
   - Assess CI on PRs into `dev`.
3. Stage 6.3 close: the student completes a five-question Matemáticas
   practice on the student's own device, and progress survives a
   restart (ADR-030 criterion 8).
4. Content: pre-generate a small Matemáticas bank, so practice does not
   wait about 5 minutes.
5. With separate authorization only: remove the obsolete server files
   listed in runbook section 0.

### Blockers/Issues

- **Pending PO decision:** the sudo rule covers every `mentorpro`
  command, including `migrate` and `rollback`. The PO may narrow it so
  that migrations still need the administrator.
- **Root-owned tool copy:** when a release changes `deploy/`, the
  administrator must re-run the three `sudo install` commands before
  deploying. Otherwise the old tool runs.
- **T046 limit:** the link works only on the house Wi-Fi (or with 8080
  tunnelled too). In local development it points at production.
- Never run a pre-T036 image on the migrated database. Recovery after a
  failed migration is the G3 restore, a PO decision. The protected dump
  is `mentor_pro_2026-10-31_170927.dump`.
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
