# Active Context: Session Handoff 2026-11-16 (T069 released, T070 accepted)

## Session Metadata

- **Last Updated:** 2026-11-16 (`v2026.11.16-2` deployed; T070 acceptance
  complete)
- **Active Role:** QA Engineer (T070), after Developer (T069 release)
- **Mode:** VERIFICATION complete. Waiting for the PO's decision to close
  the Question Bank initiative.
- **Earlier history:** T006-T068, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-COMPLETION-2026-11-14 (Question Bank Final Delivery):

- T067, T068 and T069 are released and accepted.
- T070's final acceptance passes every mandatory criterion
  ([T070 result](../progress/task_T070_result.md)).
- Proposed: close the development initiative. Inventory growth and tutor
  review continue as operations.

## Handoff Summary

### Completed

- **T069 release (PO-T069-RELEASE-2026-11-16):**
  - PR #75 merged into `dev` as `2e1dca9`.
  - Release PR #76 merged into `main` as `835ffb2`; `main` CI run
    43796742401 green.
  - Tag `v2026.11.16-2`, image `@sha256:dc5d1ce4…805b`, manifest sha256
    `ed76e384…19e5d`.
  - Backup `mentor_pro_2026-11-16_032417.dump`, `VERIFY OK`.
  - Window `T069-RELEASE-2026-11-16`: `DEPLOY OK`, smoke 13/13,
    `STATUS HEALTHY`.
  - Records: [T069 result](../progress/task_T069_result.md), release
    section.
- **T069 post-deploy (read-only):**
  - the coverage view is live;
  - coverage, `replenish capacity` and student availability agree;
  - data fingerprints are identical before and after the deploy;
  - scheduler and configuration unchanged.
- **ADR-037:** the PO kept the 100-cell plan; the 16-cell extension is
  deferred, not authorized.
- **T070:** the acceptance matrix records no mandatory defect. Larger sizes
  depend only on inventory, which the application reports correctly.

### Current State

- **Production:** `v2026.11.16-2` (T066 to T069), `STATUS HEALTHY`.
- **`main` and `dev`:** both `835ffb2`.
- **Branch `handoff/T069-T070-acceptance`:** release and acceptance records.
  It has no PR (no docs-only PR); it goes in with the next functional PR.
- **Review queue:** 26 pending, below the 40 pause threshold. No verdict
  may be recorded on the tutor's behalf.
- **Composes now (whole subject, mixed):** Matemáticas 5 and 10; Español,
  Ciencias and Estudios Sociales none.
- **Bank-only configuration:** Matemáticas only
  (`matematicas:5,10,15,20,25,30`).
- **Locks:** none held. There is no lane claim in this project. The
  replenish lock (4047, 0) and review lock (4047, 1) are
  transaction-scoped.

### Next Steps

1. **PO:** decide whether to close the Question Bank initiative (T070
   recommendation).
2. **PO:** decide whether to enable bank-only practice for Español,
   Ciencias and Estudios Sociales. This is configuration only: an
   environment change plus force-recreate.
3. **Operations:**
   - the tutor reviews the queue in the dashboard; that first decision is
     the production proof of dashboard verdicts;
   - the scheduler keeps running free-only;
   - if the queue passes 40 before the first substantial review: pause with
     `replenish pause --reason`, record the backlog, notify the PO, and do
     not resume without authorization.
4. Periodically run `replenish capacity` read-only and check the coverage
   view.

### Blockers/Issues

- None blocking. Tutor review time limits how fast the inventory grows.
- The ADR-037 16-cell extension is deferred. Do not implement it, renumber
  cells or expand single-objective capacity without PO authorization.
- Minor, optional: `replenishment.run` labels every difficulty
  `candidates_generated`, so cells without a candidate are later labelled
  `reviewed`.
- Pending PO decision: narrow the `mentorpro` sudo rule.
- `tests/app/test_practice_browser.py` is still opt-in and is not run in
  CI.
- **Local workstation:** Windows Application Control blocks `initdb.exe`,
  so 5 `test_deploy_backup.py` tests fail locally. They pass in CI.

### Notes

- **Tutor dashboard:**
  `https://macedonianserver.tailb0ac04.ts.net:8443/tutor` (tailnet only).
  Go to "Revisión de preguntas", choose Aprobar or Cuarentena (Cuarentena
  needs a reason), optionally add a comment, or skip with "Omitir". The
  SSH tunnel `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15` also
  works.
- **Read-only checks:**
  - Queue: run the `ReviewQueue` `counts()` and `pending()` script through
    `docker exec -i mentor-pro-tutor-1 python -`.
  - Coverage: `docker exec mentor-pro-app-1 python -m
    app.practice.replenish coverage --subject <s>` (JSON with
    `generation_order` and `mixed[].composes`).
  - Scheduler: `replenish schedule-status`.
  - Capacity: `docker exec mentor-pro-app-1 python -m app.practice.replenish
    capacity [--subject <s>]` (sizes by stage, the plan's structural
    limits).
  - Model usage: `llm.usage_record` (`started_at`, `tier`, `cost_usd`).
  - Database: `docker exec -i mentor-pro-postgres-1 psql -U
    mentor_pro_admin -d mentor_pro -X`.
- **Release tags use the UTC date.**
- **Windows shell:** never run `python -` or `cat >` with empty stdin,
  since both hang. Write scripts to the scratchpad and pass `</dev/null`
  to local commands. Python `write_text` writes CRLF, so normalize with
  `sed -i 's/\r$//'`.
- **Deploy, unattended:** `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`;
  `preflight "$M"`, `backup`, `verify-backup <dump>`, `deploy "$M" --backup
  <dump> --window <ref> --authorization <ref>`, `status`. Manifest: `gh
  release download <tag> -p release-manifest.json`, `scp` to
  `/opt/mentor-pro/manifests/<tag>.json`, compare sha256. Stop on any other
  result; never restore or roll back automatically.
- **Release flow:** feature PR into `dev`, then `dev` to `main` with
  `--match-head-commit`. Afterwards, sync `dev`: `git push origin
  origin/main:refs/heads/dev`.
- **Environment changes** need the administrator force-recreate: `sudo
  docker compose -p mentor-pro -f /usr/local/lib/mentor-pro/compose.yml
  --env-file /opt/mentor-pro/release.env up -d --no-deps --force-recreate
  app`.
- **Gate:** `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`,
  about 8 min). Records go in the next functional PR, never a docs-only
  PR. Skip `scripts/pubs/check_lane.py`. Check which project a pasted
  prompt targets before acting on it.
- **Never:** `docker compose down -v`, `compose.deploy.yml`, restoring over
  the live database, printing env values or tokens, the student's name in
  code, tests, commits or docs, synthetic production submissions, or
  recording review verdicts the tutor did not state.

## Active Constraints

- `.ace/standards/question-engine.md`, `.ace/standards/coding.md`,
  `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-036](../adr/ADR-036-question-bank-phase-b.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-006)
