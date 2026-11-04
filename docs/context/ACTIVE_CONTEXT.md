# Active Context: Session Handoff 2026-11-03

## Session Metadata

- **Last Updated:** 2026-11-03 (T051 merged into `dev` as `3b99f02`;
  not released or deployed)
- **Active Role:** Developer
- **Mode:** EXECUTION
- **Earlier history:** T006–T045, deployment stages 6.1–6.3, ADR-030 to
  ADR-033: see `docs/progress/task_T0xx_result.md`, `docs/planning/` and
  this file's Git history (handoff of 2026-10-30).

## Current Objective

T051, Matemáticas question bank population and activation (fast track).

- **Stage A done (read-only):** whole-subject size 5 always uses M01, M05,
  M09, M14, M18; M09 is empty and none of the five has a `hard` question.
  Size 10 also needs M07, M12, M20. No batch exists in production.
  [T051 result](../progress/task_T051_result.md).
- **Change developed (PO approval 2026-11-03):** `run --objective`,
  `item-review-sample` / `item-review-record`, and individual approval
  as a serving path (ADR-034 amendment T051). PR #48 (head `2a4fb4e`, CI
  41729749634) merged into `dev` as `3b99f02` (`dev` CI 41747414133
  green), with the T050 records (`074e133`).
- **Release candidate:** `dev` at `3b99f02` plus this handoff record;
  only `app/practice/` changed since `v2026.11.02-1` (no `deploy/`,
  schema, Dockerfile or requirements change, so no tool reinstall).
- **Still separate authorizations:** release, deployment, the
  production pilot (`run --subject matematicas --objective M09
  --max-calls 10`), live generation, provider limits and enabling
  `MENTOR_PRO_BANK_ONLY_ENABLED`.

## Handoff Summary

### Completed

- **Earlier releases, closed:** `v2026.10.30-1` (T036–T039, T045;
  [record](../progress/2026-10-31-production-release.md)) and
  `v2026.10.31-1` (T046, PO acceptance 2026-11-01;
  [T046 result](../progress/task_T046_result.md)). Unattended deployment
  with `sudo -n` enabled 2026-10-31. Closure PR #41 merged as `2000f42`.
- **T047 (question bank foundation) developed, PR #42.** Fixed 100-cell
  plan, adoption, resumable gap-only seeding under an advisory lock,
  coverage and readiness report, question quarantine, 10-question review
  gate. The PO accepted the post-approval quarantine rule (a passed batch
  returns to `pending`). CI run 41322277632 failed: on a fresh database
  `practice.item` did not exist when the seeding tests ran first; the test
  fixture now creates it (`PracticeStore`). Application code unchanged.
  [T047 result](../progress/task_T047_result.md). PO final approval
  2026-11-01; PR #42 (head `6033edb`, CI 41350431996) merged into `dev`
  as `9a09d38` (`dev` CI 41359022505 green).
- **Release `v2026.11.02-1` (T047 + T048 + T049) deployed 2026-11-02
  20:54 UTC**, window `T047-T049-2026-11-02`, authorization
  `PO-T047-T049-2026-11-02`.
  - T048 PR #43 merged as `0a776f9` (`dev` CI 41383980544); T049 PR #44
    merged as `69e2c39` (`dev` CI 41481451161).
  - Release PR #45 (head `ae3e09b`, CI 41517124354) merged into `main` as
    `166acdc` (CI 41518476299, Tag and Release green). Digest
    `sha256:738af74e…547a`; manifest sha256 `459ce7b3…e35b` on both sides.
  - Switch: the administrator's key count returned `0`; the containers had
    no such key.
  - `status`/smoke 9/9; backup `mentor_pro_2026-11-02_205333.dump`
    (sha256 `ad991fc0…00ff`, `VERIFY OK`); `PREFLIGHT OK` (schema `0001`);
    `DEPLOY OK`; smoke 9/9; `STATUS HEALTHY`.
  - `/api/subjects` reports `bank_only: false`, sizes `[5]`; a 10-question
    request and a `bank_only` request are refused (422) before any write;
    writing and tutor pages 200.
  - [Release record](../progress/2026-11-02-production-release.md).
  - Closure PR #46 merged into `dev` as `167c985` (CI 41523840735 and
    `dev` CI 41525157754 green); `dev` now contains `main`.
- **T050 (browser acceptance) passed 2026-11-02:** production rechecked
  (`STATUS HEALTHY`, smoke 9/9, `bank_only: false`, sizes `[5]`); the PO
  reported PASS for practice form, a real five-question practice, navigation,
  writing workflow and tutor navigation; no failures. The practice was real
  use by the student under PO observation (ADR-017), not a synthetic test.
  T047, T048 and T049 are `verified`;
  [release record](../progress/2026-11-02-production-release.md). The PO
  closed the cycle.
- **T050 handoff records** (`074e133`) merged with PR #48.

### Current State

- **Production** (macedonianserver):
  - `v2026.11.02-1` (`738af74e…547a`) for app and tutor, `postgres:17.6`;
    `MENTOR_PRO_BANK_ONLY_ENABLED` absent (off).
  - Schema `current 0001`; 6 dumps (no automatic deletion).
  - Rollback target: `v2026.10.31-1` (`e7dd6edb…3215`), same schema, with
    `mentor_pro_2026-11-02_205333.dump`.
- **Production inventory (read-only, 2026-11-02):** 34 accepted questions
  (Matemáticas 12, Estudios Sociales 9, Español 8, Ciencias 5), all checker
  1.6.0, about one per cell; 31 already seen. No subject simulation can be
  filled bank-only; five-question practices only for some objective sets.
- **Repository:** `main` at `166acdc` (`v2026.11.02-1`); `dev` synced
  with `main` by the closure PR. No open feature branches. No `deploy/`
  or schema change since `v2026.10.31-1`.
- **Production state (final, 2026-11-02):** `v2026.11.02-1`, bank-only
  disabled, schema `0001`, `STATUS HEALTHY`.
- **Tracker:** T046–T050 `verified`. T034 and T035 pending (maintenance).

### Next Steps

1. **T051:** release PR from `handoff/T051-merged` into `main` (as for
   `v2026.11.02-1`), then deployment, the targeted M09 pilot, individual
   tutor review, and the activation decision. Each step needs its own authorization.
2. Maintenance candidates, each a separate verified change:
   - T035: tutor exit 78 for tokens of 1–15 characters.
   - T034: deterministic practice-set test.
   - Assess CI on PRs into `dev`.
3. Stage 6.3 close: check whether the T050 practice on the student's own
   device, plus progress surviving a restart, satisfies ADR-030 criterion 8
   (restart part not yet shown).
4. With separate authorization only: remove the obsolete server files
   listed in runbook section 0.

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
