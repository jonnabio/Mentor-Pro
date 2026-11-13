# Active Context: Session Handoff 2026-11-12 (Evening)

## Session Metadata

- **Last Updated:** 2026-11-12 (T065 released and verified; Matemáticas
  size 10 live; T066 scheduler in PR)
- **Active Role:** Developer
- **Mode:** EXECUTION
- **Earlier history:** T006-T064, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-CONTINUATION-2026-11-12: grow approved inventory toward sizes
10-30 in every subject, and make replenishment run without an
administrator starting each run (T066).

## Handoff Summary

### Completed

- **Tutor reviews recorded** (`item-review-record --reviewer tutor`,
  each once): Phase B 11 approved (Matemáticas 5, Ciencias 3, Estudios
  Sociales 3); QBANK-FINAL 5 approved, 3 quarantined (NEW-3 `other`, NEW-4
  `level`, NEW-7 `other`). Review files deleted.
- **T065 done:** PR #68, release PR #69 merged as `4245869` (main CI
  43249020382 green), `v2026.11.12-1` deployed (digest `04e01d50…f3e8`,
  smoke 13/13, `STATUS HEALTHY`). Evidence in
  [T065 result](../progress/task_T065_result.md).
- **Matemáticas size 10 live:** whole-subject mixed composes 10 distinct
  bank questions (4 easy, 3 medium, 3 hard); `POST
  /api/practice/availability` returns `[5, 10]`.
- **T066** (branch `feat/T066-replenish-scheduler`): `replenish tick`,
  host cron every 3 h, off by default, pause/resume, global lock, rotation,
  recorded ticks. Full ACE gate pass.
  [T066 result](../progress/task_T066_result.md).

### Current State

- **Production:** `v2026.11.12-1`, `STATUS HEALTHY`. Latest backup
  `mentor_pro_2026-11-12_154415.dump` (sha256 `cec2a5ee…eb7b`) `VERIFY
  OK`. Paid generation off.
- **Eligible (pending, quarantined):** Matemáticas 40 (0, 4), Estudios
  Sociales 17, Español 8, Ciencias 8 (0 pending each before the current
  runs).
- **Sizes offered:** Matemáticas mixed `[5, 10]`; single-level
  Matemáticas and the other subjects generate size 5.
- **Gaps (real composer):** Matemáticas 15: M06, M08, M11, M15, M21;
  size 5 bank: Español EL04, EL05, EL07; Ciencias C04, C08, C12, C16;
  Estudios Sociales ES06, ES18, ES24 (one question each).
- **Targeted runs in progress** for those 15 objectives (free, 10 calls
  each); log `~/mentor-pro-review/runs/qbank-cont-2026-11-12.log`. M06: 1
  candidate.
- **Locks:** none held at handoff.

### Next Steps

1. When the runs finish: `item-review-sample` per subject, tutor review,
   record, recount, check availability.
2. PO review of the T066 PR, then `dev` -> `main`, deploy, install the
   cron line, administrator enables `MENTOR_PRO_REPLENISH_SCHEDULE=on`.
3. Bank-only for another subject only after its size 5 composes from the
   bank (administrator edits `MENTOR_PRO_BANK_ONLY_SUBJECTS`).

### Blockers/Issues

- PO review of T066.
- Tutor review time bounds inventory growth.
- `replenishment.run` marks every difficulty of an objective
  `candidates_generated`; cells without a candidate are later closed as
  `reviewed` (misleading label, no duplicate generation). Follow-up.
- Hard Ciencias/Estudios Sociales items often rejected for near-identical
  options (C04); replenishment prioritisation alphabetical within a
  trigger.
- Pending PO decision: narrow the `mentorpro` sudo rule.
- Older items: see this file's Git history at 2026-11-06.

### Notes

- **Deploy, unattended:** `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`;
  `preflight "$M"`, `backup`, `verify-backup <dump>`, `deploy "$M" --backup
  <dump> --window <ref> --authorization <ref>`, `status`. Manifest: `gh
  release download <tag> -p release-manifest.json`, `scp` to
  `/opt/mentor-pro/manifests/<tag>.json`, compare sha256. Stop on any other
  result; never restore or roll back automatically.
- **Review recording:** decisions file into the app container (`docker
  cp`), `python -m app.practice.seed_bank item-review-record --subject <s>
  --decisions <file> --reviewer tutor` once, delete the copy and the
  host file. Only verdicts stated by the human tutor; free-text comments
  are not stored (reason code only).
- **Composer checks:** `seed_bank compose-check --subject <s>` (read-only)
  and `POST /api/practice/availability`.
- **Release flow:** feature PR into `dev`, then `dev` -> `main` with
  `--match-head-commit`; sync `dev` from `main` afterwards.
- **Environment changes** need the administrator force-recreate: `sudo
  docker compose -p mentor-pro -f /usr/local/lib/mentor-pro/compose.yml
  --env-file /opt/mentor-pro/release.env up -d --no-deps --force-recreate
  app`.
- **Server:** `ssh jonnabio@100.64.84.15`; tutor via `ssh -N -L
  8081:127.0.0.1:8081 jonnabio@100.64.84.15`.
- **Gate:** `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`,
  about 6 min). Records go in the next functional PR, never a docs-only
  PR. Skip `scripts/pubs/check_lane.py`.
- **Never:** `docker compose down -v`, `compose.deploy.yml`, restoring over
  the live database, printing env values or tokens, the student's name in
  code, tests, commits or docs, synthetic production submissions.

## Active Constraints

- `.ace/standards/question-engine.md`, `.ace/standards/coding.md`,
  `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-036](../adr/ADR-036-question-bank-phase-b.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-006)
