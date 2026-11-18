# Active Context: T071 Bulk Approval in Review (2026-11-16)

## Session Metadata

- **Last Updated:** 2026-11-16 (T071 implemented, PR into `dev` open)
- **Active Role:** Developer (T071).
- **Mode:** review. The T071 request (tutor bulk review and approval)
  is the new PO-requested increment after the Question Bank closure.
  [T071 result](../progress/task_T071_result.md).
  - Branch `feat/T071-bulk-approve` includes the
    `handoff/T069-T070-acceptance` evidence.
  - Waiting for PO review. Do not merge or deploy without authorization.
- **Earlier history:** T006-T068, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

None in development. The PO closed the Question Bank initiative after T070
(PO-QBANK-CLOSE-2026-11-16). Operations continue:

- free scheduled generation;
- tutor review in the dashboard;
- monitoring curriculum coverage.

Do not start another Question Bank development increment without a new PO
authorization.

## Handoff Summary

### Completed

- **T069 implementation (PO-T069-2026-11-16):**
  - `app/practice/capacity.py`: exact per-size counts by stage (plan,
    generated, approved).
  - Tutor "Cobertura del banco" (`GET /api/tutor/coverage`).
  - `replenish capacity` on the command line.
  - Four-subject synthetic regression for sizes 5-30 (API, plus browser on
    desktop and phone). The CI browser step runs 5 tests.
  - [ADR-037](../adr/ADR-037-quiz-size-capacity.md): structural capacity
    analysis.
  - PR #75 merged into `dev` as `2e1dca9`.
- **T069 release (PO-T069-RELEASE-2026-11-16):**
  - release PR #76 merged into `main` as `835ffb2`; `main` CI run
    43796742401 green;
  - tag `v2026.11.16-2`, image `@sha256:dc5d1ce4…805b`, manifest sha256
    `ed76e384…19e5d`;
  - backup `mentor_pro_2026-11-16_032417.dump`, `VERIFY OK`;
  - `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`;
  - post-deploy: coverage, `replenish capacity` and student availability
    agree; data fingerprints identical before and after; scheduler and
    configuration unchanged.
- **ADR-037 decision:** the 100-cell plan is kept; the 16-cell extension is
  deferred.
- **T070 final acceptance:** every mandatory criterion passes
  ([T070 result](../progress/task_T070_result.md)).
- **Closure (PO-QBANK-CLOSE-2026-11-16):**
  - T070 and the initiative are complete;
  - the minor issues are in [TODO-maintenance.md](../TODO-maintenance.md);
  - the tutor-dashboard review is recorded as an operational follow-up.
- **Records:** T069 and T070 results, ADR-037, the T069 plan, `tasks.json`
  (T067-T070 `done`), screenshots in `docs/progress/screenshots/T069/`.

### Current State

- **Production:** `v2026.11.16-2` (T066 to T069), `STATUS HEALTHY`.
  - The app and tutor containers run `@sha256:dc5d1ce4…805b`.
  - The tutor page has "Revisión de preguntas" and "Cobertura del banco".
- **`main` and `dev`:** both `835ffb2`.
- **Branch `handoff/T069-T070-acceptance`:** pushed, **intentionally not
  merged, and no PR open.**
  - It holds the release evidence (`eb18ee9`), the closure records and this
  handoff.
  - The PO forbids a documentation-only PR. Bring this branch into the next
    functional PR.
- **Configuration:**
  - `MENTOR_PRO_BANK_ONLY_SUBJECTS=matematicas:5,10,15,20,25,30`;
  - `OPENROUTER_ALLOW_PAID=false`;
  - `MENTOR_PRO_REPLENISH_SCHEDULE=on`, `tick_calls` 10, not paused.
- **Inventory** (whole subject, mixed):

  | Subject | Approved | Composes | Missing for size 30 |
  | --- | --- | --- | --- |
  | Matemáticas | 42 | 5, 10 | 11 |
  | Español | 10 | none | 22 |
  | Ciencias | 10 | none | 23 |
  | Estudios Sociales | 20 | none | 19 |

  Hard is the scarcest level everywhere.
- **Review queue:** 26 pending at the last check. No dashboard verdict has
  been recorded yet.
- **Locks:** none held. There is no lane claim in this project. The
  replenish lock (4047, 0) and review lock (4047, 1) are
  transaction-scoped and released when each transaction ends.

### Next Steps

1. **Check the review queue** (read-only). If it passes **40** before the
   tutor's first substantial review:
   - pause with `replenish pause --reason "<backlog> pending before first
     review"`;
   - record the backlog and reason;
   - notify the PO;
   - never resume without authorization.
2. **Run `replenish capacity` for Español, Ciencias and Estudios Sociales.**
   Report to the PO when the real composer builds a five-question practice
   for a subject. Request PO authorization before changing that subject's
   bank-only configuration.
3. **Confirm the first authentic tutor-dashboard decision** once the tutor
   has reviewed (read-only `bank_item_review` rows with reviewer `tutor`).
   That is the operational acceptance follow-up. Never record a verdict for
   the tutor.
4. **Next functional PR:** branch from `dev` and merge in
   `handoff/T069-T070-acceptance` so the evidence goes in with it. Any
   maintenance item needs its own authorization.

### Blockers/Issues

- No development blockers. The Question Bank is closed.
- **Pending PO decisions:**
  - bank-only for the other three subjects, once each composes size 5;
  - narrowing the `mentorpro` sudo rule (backlog M3);
  - the ADR-037 extension, which stays deferred.
- **Maintenance backlog** ([TODO-maintenance.md](../TODO-maintenance.md)):
  - M1: replenishment request labels;
  - M2: `test_practice_browser.py` is not in CI;
  - M3: the sudo rule;
  - M4: local `initdb.exe` blocked.
- **Operational:** tutor review throughput limits inventory growth. The
  queue grows by about 2 to 3 candidates every 3 hours.

### Notes

- **Tutor dashboard:**
  - `https://macedonianserver.tailb0ac04.ts.net:8443/tutor` (tailnet only);
  - "Revisión de preguntas": Aprobar, or Cuarentena (a reason is required),
    an optional comment, or "Omitir" to skip;
  - "Cobertura del banco": the sizes each subject composes and what the
    next size lacks;
  - the SSH tunnel `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`
    also works.
- **Read-only checks:**
  - **Queue:** run the `ReviewQueue` `counts()` script through
    `docker exec -i mentor-pro-tutor-1 python - < script.py`.
  - **Capacity:** `docker exec mentor-pro-app-1 python -m
    app.practice.replenish capacity [--subject <s>]` (sizes by stage,
    plan limits).
  - **Coverage and priority:** `replenish coverage --subject <s>`.
  - **Scheduler:** `replenish schedule-status`.
  - **Student availability** (creates nothing): POST
    `http://127.0.0.1:8080/api/practice/availability` on the server.
  - **Model usage:** `llm.usage_record` (`started_at`, `tier`,
    `cost_usd`).
  - **Database:** `docker exec -i mentor-pro-postgres-1 psql -U
    mentor_pro_admin -d mentor_pro -X`. Wrap checks in `BEGIN READ ONLY`.
  - **Data fingerprints:** the T069 release section lists the tables
    compared before and after a deploy.
- **Release tags use the UTC date.**
- **Windows shell:**
  - never run `python -` or `cat >` with empty stdin, since both hang;
  - write scripts to the scratchpad and pass `</dev/null` to local
    commands;
  - Python `write_text` writes CRLF, so normalize with
    `sed -i 's/\r$//'`;
  - don't name scratch scripts after standard-library modules (for example
    `struct.py`).
- **Deploy, unattended:**
  - `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`;
  - `preflight "$M"`, `backup`, `verify-backup <dump>`,
    `deploy "$M" --backup <dump> --window <ref> --authorization <ref>`,
    `status`;
  - manifest: `gh release download <tag> -p release-manifest.json`, `scp`
    to `/opt/mentor-pro/manifests/<tag>.json`, compare sha256;
  - stop on any other result; never restore or roll back automatically.
- **Release flow:**
  - feature PR into `dev`, then `dev` to `main` with
    `--match-head-commit <full 40-character SHA>`;
  - afterwards, sync `dev`: `git push origin origin/main:refs/heads/dev`.
- **Environment changes** need the administrator force-recreate:
  `sudo docker compose -p mentor-pro -f /usr/local/lib/mentor-pro/compose.yml
  --env-file /opt/mentor-pro/release.env up -d --no-deps --force-recreate
  app`. Bank-only changes also need PO authorization.
- **Gate:**
  - `bash .ace/scripts/verify.sh` (about 8 min);
  - locally, 5 `test_deploy_backup.py` tests fail because Windows App
    Control blocks `initdb.exe`; confirm they are the only failures and
    rely on CI;
  - records go in the next functional PR, never a docs-only PR;
  - skip `scripts/pubs/check_lane.py`;
  - check which project a pasted prompt targets before acting on it.
- **Never:**
  - `docker compose down -v`, `compose.deploy.yml`, or restoring over the
    live database;
  - printing env values or tokens;
  - the student's name in code, tests, commits or docs;
  - synthetic production submissions;
  - recording review verdicts the tutor did not state.

## Active Constraints

- `.ace/standards/question-engine.md`, `.ace/standards/coding.md`,
  `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-037](../adr/ADR-037-quiz-size-capacity.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-006)
