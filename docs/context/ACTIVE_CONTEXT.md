# Active Context: 2026-11-25 (v2026.11.24-1 deployed; Gate C pending; scheduler paused)

## Session Metadata

- **Last Updated:** 2026-11-25, session handoff.
- **Active Role:** none; the session ended.
- **Mode:** waiting for consolidated Gate C (T071 and T072 human
  acceptance) and PO decisions.

## Handoff 2026-11-25 (supersedes the sections below where they differ)

### Completed (2026-11-24 to 2026-11-25)

- **PR #84 review correction:** a failed bulk-approve batch is reported as
  **unconfirmed** (may or may not have applied; never retried; the tutor
  is pointed to the refreshed queue), and later batches as **not sent**
  (never attempted). The queue refresh is unchanged.
  - Commit `31dc74d`; new test
    `test_a_failed_last_batch_is_unconfirmed_with_nothing_unsent`.
  - PR head `31dc74df3ade59e9a6a0eb4f80d5a037314d209d`, CI 45417773859.
  - Merged into `dev` (exact-head guard) as
    `97e29646192ac1b1edd6c70bfeeda37c7893de89`; `dev` CI 45420176013.
  - Both runs green, browser tests executed=29 skipped=0.
- **Gate A (release publication):**
  - Release PR #85 (head `97e2964`, CI 45494892496) merged into `main` as
    `141d0725eb1583579601885a3de215c5e03aab9f`; `main` CI 45496672372
    green, including Tag and Release.
  - Release `v2026.11.24-1`; image
    `ghcr.io/jonnabio/mentor-pro@sha256:9948605d05bedf176543f7621a398e85f819862b75e9b98851f1fd5d57e3a384`
    (registry digest checked independently).
  - Manifest sha256
    `d0f4167b3f2ec83abcf3c31b11b26f20f87fe2f6bfd7c9228757debb4311e60e`;
    labels: version, revision, `report-holds=1`, schema 0001..0001.
  - `dev` fast-forwarded to `main`.
  - Evidence: [T071 result](../progress/task_T071_result.md) section 7.
- **Gate B (production deployment)**
  (`PO-T071-APPROVE-ALL-GATE-B-2026-11-24`, window
  `T071-APPROVE-ALL-2026-11-24`):
  - Helpers match the release (`mentorpro` `da92f99e…`,
    `mentorpro_deploy.py` `f76c89a1…`, `mentorpro_migrate.py`
    `880545d3…`).
  - Preflight: `PREFLIGHT OK: DEPLOY COMPATIBLE`, report holds enforced.
  - Backup `mentor_pro_2026-11-25_002248.dump`, sha256
    `b339d7b2ac7b00bc81bc929c18090e5db44589cb42af398573461d8ac9a609c6`,
    `VERIFY OK`.
  - Deployed 2026-11-25T00:23:13Z: `DEPLOY OK`, `SMOKE PASS (13/13)`,
    `STATUS HEALTHY`. Previous image `@sha256:22cfcbf3…bce1b2`.
  - Fingerprints before and after: all 38 tables, env and crontab
    hashes identical.
  - The served `tutor.js` contains "Seleccionar todas las pendientes (N)".
  - No question was approved or quarantined by the agent.
  - Evidence: [T071 result](../progress/task_T071_result.md) section 8.

### Current State (2026-11-25)

- **Production:** `v2026.11.24-1` (`@sha256:9948605d…e3a384`, commit
  `141d072`), healthy. It includes the approve-all enhancement.
- **Flags:** `MENTOR_PRO_AUTO_ELIGIBILITY` unset (off),
  `OPENROUTER_ALLOW_PAID=false`, bank-only for Matemáticas only.
- **Scheduler:** paused (reason text is still the old "review queue 51 >
  40"); ticks record `skipped (paused)` with 0 calls.
- **Verdicts:** 92 (77 approved, 15 quarantined, all by the tutor). That is
  33 approvals since the 2026-11-22 Gate C baseline, made by the tutor
  before the deploy. 0 reports.
- **Branches:** `main` = `141d072`; `dev` = `main` plus this handoff
  record (merged from `handoff/T071-approve-all-release`).
- **Tasks:** T071 and T072 stay `review` in `tasks.json` until the tutor
  confirms Gate C.
- **Locks:** none held; no lane claim.

### Next Steps

1. Get the tutor's Gate C results (checklist: T071 steps 1–5, including
   "Seleccionar todas las pendientes (N)"; T072 steps 6–12).
2. Post-acceptance verification, read only: run
   `bash ~/t072-helper/fp.sh <out>` and compare with
   `~/t072-helper/fp_t071ab_pre.txt` (the newest baseline, 2026-11-25);
   check verdicts against the tutor's actions, reports, `status` and
   smoke.
3. If the tutor confirms: record separate T071 and T072 acceptance and set
   both tasks to `done`.
4. Scheduler resumption: PO decision only.

### Blockers/Issues

- **Gate C:** waiting for the tutor. Nothing is accepted without the
  tutor's explicit confirmation. The 33 new approvals need to be confirmed
  as the tutor's own Gate C actions.
- **PO decisions pending:** resuming the scheduler; activating automatic
  eligibility.
- **Not tested in production:** the legacy-rollback write barrier.
- **Approve-all residual risk:** concurrent approvals can shift pages and
  miss a question; it stays pending, never wrongly approved.
- **Local only:** `test_bulk_approval_in_the_browser` exceeds its 5 s
  timeout on Windows; CI passes it.

### Notes

- **Server:** `ssh jonnabio@100.64.84.15`; the agent may run only
  `sudo -n /usr/local/lib/mentor-pro/mentorpro`. Manifest:
  `/opt/mentor-pro/manifests/v2026.11.24-1.json`.
- **Staging files:** `~/t072-helper/` (`fp.sh` and fingerprints). Remove
  only after Gate C closes.
- **Verdict query:** `generation.bank_item_review` (`reviewer`,
  `verdict`); there is no `generation.item_review` table, so `fp.sh`'s
  verdicts section prints nothing.
- **CI:** if a new push leaves an older PR run in progress, the new run
  may be cancelled; cancel the stale run and `gh run rerun` the new one.
- **GHCR without Docker:** an anonymous token from
  `https://ghcr.io/token?scope=repository:jonnabio/mentor-pro:pull` reads
  the manifest digest and config labels.
- **Local browser tests:**
  `MENTOR_PRO_BROWSER=1 .venv/Scripts/python.exe -m pytest tests/app/test_tutor_approve_all.py`.

## Handoff 2026-11-24 (supersedes the sections below where they differ)

### Completed (2026-11-24)

- **T072 Gate B** (`PO-T072-GATE-B-2026-11-21`, window
  `T072-RELEASE-2026-11-21`):
  - `v2026.11.21-1` (commit `e039cd3`) is deployed to production,
    2026-11-22 at about 20:30 UTC.
  - Image `@sha256:22cfcbf3…bce1b2`, `DEPLOY OK`, smoke 13/13,
    `STATUS HEALTHY`.
  - Backup `mentor_pro_2026-11-22_202801.dump` (`VERIFY OK`).
  - Fingerprints are identical, apart from the new, empty
    `generation.question_report`.
  - Evidence: [T072 result](../progress/task_T072_result.md) section 10.
- **Deploy helper:** the first Gate B attempt stopped because the installed
  `mentorpro_deploy.py` predated T072. The administrator installed the
  release copy, and all three helper files now match `e039cd3`.
- **Gate C preparation:** the read-only baseline was taken at
  2026-11-22T21:38:27Z (server `~/t072-helper/fp_gatec_pre.txt`), and the
  browser checklist was handed to the PO and tutor.
- **T071 "approve all pending" enhancement** (PR #84 into `dev`, head
  `306095b`, merged at session end):
  - "Seleccionar todas las pendientes (N)" works across pages, respects the
    applied filters and states its scope.
  - A confirmation dialog shows the count, subjects and scope; Cancelar and
    Escape send nothing.
  - The selection is re-checked against the queue at confirmation.
  - Approvals go to the existing endpoint in sequential batches of at most
    50, and a failed batch is never resent.
  - Frontend only. Details:
    [T071 result](../progress/task_T071_result.md) section 6.
- **CI gap closed:** the T071 bulk, stimulus and approve-all browser tests
  had never run in CI. `ci.yml` now runs them, with a minimum of 18
  executed and 0 skipped. Exact-head CI 45085023962 passed with 28
  executed and 0 skipped.

### Current State (2026-11-24)

- **Production:** `v2026.11.21-1`, healthy. It does **not** include the
  approve-all enhancement.
- **Flags:** `MENTOR_PRO_AUTO_ELIGIBILITY` is unset (off), and
  `OPENROUTER_ALLOW_PAID=false`.
- **Scheduler:** paused ("Gate C T071"). Ticks record `skipped (paused)`
  with 0 calls.
- **Queue at the baseline:** 33 pending (Español 0, Matemáticas 13,
  Ciencias 11, Estudios Sociales 9); 0 open reports. Verdicts: 59 (44
  approved, 15 quarantined).
- **Branches:** (superseded by the Gate A update above) `dev` had PR #84; `main` was at `e039cd3`, so the
  enhancement is not released.
- **Tasks:** T071 and T072 are `review` in `tasks.json` until the tutor
  confirms Gate C.

### Next Steps (2026-11-24)

1. Record PR #84's merge SHA and its `dev` CI run in the next docs update
   (not a docs-only PR).
2. Get the tutor's Gate C results (checklist: T071 steps 1–5, T072 steps
   6–12).
3. Run the post-acceptance verification:
   - compare with `fp_gatec_pre.txt` (`bash ~/t072-helper/fp.sh <out>` on
     the server);
   - check verdicts against the tutor's actions;
   - check the report and resolution rows, `status`, and smoke.
4. If the tutor confirms: record separate T071 and T072 acceptance and set
   both tasks to `done`.
5. Release and deploy the approve-all enhancement (`dev` → `main`), only
   with PO authorization.
6. Decide on resuming the scheduler, only with PO authorization.

### Blockers/Issues (2026-11-24)

- **Gate C:** waiting for human tutor acceptance. Nothing may be accepted
  without the tutor's explicit confirmation.
- **PO decisions pending:**
  - releasing the enhancement;
  - resuming the scheduler (queue below 40, Gate C complete,
    post-acceptance checks passed, explicit authorization);
  - activating automatic eligibility.
- **Local only:** `test_bulk_approval_in_the_browser` exceeds its 5 s
  timeout on the Windows machine, on unmodified `dev` too. CI passes it.
- **Not tested in production:** the legacy-rollback write barrier. The
  `mentor_pro_admin` role is a superuser with `pg_signal_backend`.
- **Approve-all residual risk:** approvals made elsewhere while the
  selection is read can shift pages, so a question can be missed. It stays
  pending; it is never wrongly approved.

### Notes (2026-11-24)

- **Server access:** `ssh jonnabio@100.64.84.15`. The agent may run only
  `sudo -n /usr/local/lib/mentor-pro/mentorpro`. Installing helper files
  needs the administrator (an interactive `sudo install`).
- **Manifest:** `/opt/mentor-pro/manifests/v2026.11.21-1.json` (sha256
  `b262e85e…4b6e35`).
- **Tutor API from the server:** a call without the token returns 403. Read
  the queue read-only through `ReviewQueue` inside `mentor-pro-tutor-1`;
  do not look up the token.
- **Staging files on the server:** `~/t072-helper/` holds `fp.sh`, the
  fingerprints and the staged helper. Remove them only once Gate C is
  closed.
- **Local browser tests:**
  `MENTOR_PRO_BROWSER=1 .venv/Scripts/python.exe -m pytest tests/app/test_tutor_approve_all.py`.
- **Earlier history:** T006-T070, the deployment stages, ADR-030 to
  ADR-038, the release records in `docs/progress/` and this file's Git
  history.

## Update 2026-11-19 (supersedes the sections below where they differ)

- **Production:** `v2026.11.19-1`, deployed 2026-11-19 at about 00:21 UTC
  (`PO-M5-DEPLOY-2026-11-19`).
  - Image `@sha256:8e6eacef…0541d9`, commit `1cbd857`, CI 44426535451.
  - `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`.
  - Backup `mentor_pro_2026-11-19_002029.dump` (`VERIFY OK`).
  - Fingerprints identical before and after the deploy.
  - It carries M5 (RCA-007, PR #79 and #80): the proposed answer is readable
    in dark mode.
- **Scheduler:** **paused** since 2026-11-18 21:12 UTC (reason "Gate C T071",
  PO-approved).
  - It resumes only when all of these hold: the queue is below 40, Gate C is
    complete, the post-acceptance checks pass, and the PO explicitly
    authorizes it.
  - Paused ticks record `skipped (paused)` with 0 calls.
- **T071 Gate C:** pending.
  - One tutor approval was recorded at 2026-11-18 23:52:39 UTC (42 verdicts
    in total).
  - The tutor found no wrong questions and asked for approve-all. They were
    pointed to page-by-page bulk approval; option A, a page-size selector,
    was proposed as M6.
  - Pre-acceptance baseline: 2026-11-18 21:13:01Z, `/tmp/gatec_fp_pre.txt` on
    the server.
- **T072** ([result](../progress/task_T072_result.md),
  [ADR-038](../adr/ADR-038-automatic-eligibility-and-student-reports.md)):
  - automatic eligibility behind `MENTOR_PRO_AUTO_ELIGIBILITY` (default
    off);
  - student reports with a hold;
  - tutor resolution (retain or quarantine);
  - `reports_open` scheduler pause.
  - Status: `review`. PR #81 merged into `dev` 2026-11-19 (merge
    `550fc21`, exact-head guard `73391a1`; `dev` CI 44648495199 green).
    Not released, deployed or activated.
  - Rollback safeguard (ADR-038 D6, RCA-008): deploy, rollback and
    preflight refuse an image without the report-hold label while reports
    are open. Feature PR into `dev`, awaiting review.
- **Next:**
  1. Review and merge the rollback safeguard into `dev`.
  2. Release and deploy T072 only with PO authorization.
  3. Activate the flag only with separate PO authorization.
  4. Finish Gate C, then the scheduler-resume decision.
- **Earlier history:** T006-T070, deployment stages, ADR-030 to ADR-037:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Gate B Update (2026-11-18 21:06 UTC)

- **`v2026.11.18-1` is deployed to production.** Image
  `@sha256:71723c4e…0aee2e`, `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`.
- Backup: `mentor_pro_2026-11-18_210616.dump` (`VERIFY OK`).
- All 37 table fingerprints are identical before and after the deploy.
- Configuration and scheduler are unchanged.
- Bulk approval without the token returns 403, and the student service
  returns 404 for it.
- **Next:**
  - the tutor runs the production acceptance checklist (T071 result,
    section 5, and the PR #78 description);
  - after that, set T071 to `done` in `tasks.json`.
- **Risk:** the review queue is at 51 pending, above the 40 threshold.
  Waiting on the PO to decide whether to pause the scheduler; bulk
  approval is now live to reduce it.
- The sections below are from before Gate B. Where they say Gate B is
  pending or production runs `v2026.11.16-2`, this update supersedes
  them.

## Current Objective

T071 (tutor bulk review and approval) is implemented, reviewed, merged and
published as `v2026.11.18-1`. It is **not deployed**. Gate B (production
deployment) needs a separate, explicit PO authorization. Until then the
work is operational:

- free scheduled generation;
- tutor review in the dashboard;
- monitoring curriculum coverage.

No other development increment is authorized.

## Handoff Summary

### Completed

- **T071 implementation** ([T071 result](../progress/task_T071_result.md)):
  - `GET /api/tutor/review/queue`:
    - optional `page` and `page_size` (at most 50);
    - adds `total` and `pagination`;
    - without them the T068 full list is unchanged.
  - `POST /api/tutor/review/bulk-approve`:
    - explicit IDs only, 1 to 50 per call; duplicate, empty or over-long IDs
      are refused with 422;
    - each ID goes through the existing `seeding.item_review_record` in its
      own transaction (review lock, re-check, audit row with reviewer
      `tutor`);
    - one result per ID: `approved`, `already_reviewed`, `not_pending` or
      `error`.
  - Tutor page, "Aprobación en bloque":
    - expandable full question and a checkbox per question;
    - page-scoped "Seleccionar toda la página", "Limpiar selección", and
      "Aprobar seleccionadas (N)" with a confirmation;
    - partial-failure feedback;
    - the selection resets on a result, a page change or a filter change.
  - Review correction: `renderStimulus` in `tutor.js` renders structured
    stimuli in the individual review, the bulk review and the practice
    results.
    - `none` is hidden, `text` keeps its line breaks, and a `table` with
      pipe- or tab-delimited rows becomes a table;
    - other layouts fall back to text;
    - DOM text only, never `innerHTML`.
  - Fixed a busy-flag regression: the bulk refresh had dropped a fast
    second individual decision.
  - Tests: `tests/app/test_tutor_bulk_approve.py` (API and browser).
    Screenshots are in `docs/progress/screenshots/T071/`.
  - No schema, configuration, generation or deployment change.
- **Integration:**
  - PR #77, approved at head `7b6a880`, was merged into `dev` as
    `dd2440492a75981157d36aa7b31bff39b0cbcf44`.
  - PR CI run 43871162934 and `dev` CI run 43877468777 are green.
  - Local gate: `VERIFY_RESULT=pass gate=all`, 1203 passed, 17 skipped,
    lint passed.
  - PR #77 also carried the T069/T070 handoff evidence (`eb18ee9`,
    `6c1b508`).
- **Gate A, release publication (PO authorized):**
  - Release PR #78 was merged into `main` with the guard on `dd24404…`,
    giving merge commit `bc590fb6c144c2f94537488f45db0fa555d5d237`.
  - PR CI run 43879335351 passed on attempt 2. Attempt 1 hit the known
    deadlock in the `test_quiz_sizes_subjects.py` setup.
  - `main` CI run 44232643285 is green on all four jobs, including Tag and
    Release.
  - Tag `v2026.11.18-1` points to `bc590fb`.
  - Image: `ghcr.io/jonnabio/mentor-pro@sha256:71723c4eed2e3b493bfd640453ed191b3eaf18143316cd29726edc60ac0aee2e`.
  - Manifest sha256 `7685f567a8a6b3436a0f80424fcb03c93ef75d25918bcc319fa34beba5f79f9a`:
    commit `bc590fb`, schema 0001..0001, smoke student and tutor pass,
    status "Published, not authorized for deployment".
  - `dev` was synced to `main` (it was an ancestor, so nothing was
    discarded).
- **Production was not modified this session.**

### Current State

- **Production:** still `v2026.11.16-2` (T066 to T069), `@sha256:dc5d1ce4…805b`,
  last known `STATUS HEALTHY`. The bulk approval and stimulus fix are
  **not live**.
- **`main`, `dev` and tag `v2026.11.18-1`:** all
  `bc590fb6c144c2f94537488f45db0fa555d5d237`.
- **Branch `handoff/T071-release`:** this handoff (based on `bc590fb`).
  It is pushed but **not merged and has no PR**, following the
  no-docs-only-PR rule. Bring it into the next functional PR or the Gate B
  records.
- **`tasks.json`:** T071 status is `review`. Set it to `done` after Gate B
  and production acceptance.
- **Configuration and inventory:** unchanged since the 2026-11-16 handoff.
  - Bank-only is on for Matemáticas only; paid models are off; the
    scheduler is on.
  - Last known review queue: 26 pending.
- **Locks:** none held. There is no lane claim. The replenish lock
  (4047, 0) and review lock (4047, 1) are transaction-scoped.

### Next Steps

1. **Wait for the PO's Gate B decision.** Do not deploy without it.
2. **On Gate B authorization, deploy `v2026.11.18-1`** with the
   unattended deploy procedure (Notes):
   - download the manifest and compare its sha256 with `7685f567…f79f9a`;
   - preflight, backup, `verify-backup`, deploy with the window and
     authorization references, then `status` and smoke;
   - data fingerprints before and after.
3. **Production acceptance** (plan in the PR #78 description). The tutor
   records every verdict; run no synthetic production submissions.
   - Structured stimuli display correctly in both views.
   - One individual approval and one bulk approval, each with its audit
     rows.
   - Partial failures: observe them only if they happen naturally;
     otherwise rely on the CI evidence.
   - Approved questions count as servable (capacity, coverage,
     availability).
   - `bulk-approve` returns 403 without the token.
   - Scheduler and configuration unchanged.
4. **Record the Gate A and Gate B evidence** in the T071 result and
   `tasks.json`, bringing in `handoff/T071-release`. Do it in the next
   functional PR, not a docs-only PR.
5. **Operational checks continue (read-only):**
   - review queue: pause the scheduler only if it passes 40 before the
     tutor's first substantial review;
   - `replenish capacity` for the other subjects;
   - confirm the first authentic tutor decision.

### Blockers/Issues

- **Gate B (production deployment of `v2026.11.18-1`):** not authorized;
  waiting for the PO.
- **Intermittent test deadlock (new maintenance candidate):**
  - `test_quiz_sizes_subjects.py` fixture setup raises `DeadlockDetected`
    (7 errors);
  - seen in `dev` CI run 43797888363 (`835ffb2`), the first attempt of PR
    CI run 43879335351, and one local gate run;
  - it passes on rerun and alone, and it predates T071;
  - it needs a maintenance authorization before anyone works on it.
- **Production table-stimulus layouts were not sampled.** The read-only
  production query was not permitted from this session. Check them during
  Gate B acceptance.
- **Pending PO decisions:**
  - Gate B;
  - bank-only for the other three subjects;
  - narrowing the `mentorpro` sudo rule (M3);
  - the ADR-037 extension (deferred).
- **Maintenance backlog** ([TODO-maintenance.md](../TODO-maintenance.md)):
  - M1: replenishment labels;
  - M2: `test_practice_browser.py` is not in CI;
  - M3: the sudo rule;
  - M4: local `initdb.exe` blocked.
- **Operational:** tutor review throughput limits inventory growth. Bulk
  approval addresses this once it is deployed.

### Notes

- **Tutor dashboard:**
  - `https://macedonianserver.tailb0ac04.ts.net:8443/tutor` (tailnet only);
  - "Revisión de preguntas": Aprobar, or Cuarentena (a reason is required),
    an optional comment, or "Omitir" to skip;
  - after `v2026.11.18-1` is deployed, "Aprobación en bloque" appears above
    the individual review. It approves only; quarantine stays individual,
    with at most 50 IDs per call;
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
  - if `test_quiz_sizes_subjects.py` setup fails with `DeadlockDetected`,
    rerun the failed CI job (`gh run rerun <id> --failed`) and record it.
    Never bypass a red check;
  - T071 browser tests: `MENTOR_PRO_BROWSER=1
    MENTOR_PRO_SCREENSHOTS=<dir> pytest tests/app/test_tutor_bulk_approve.py`;
  - GHCR digest check: the `gh` token lacks `read:packages` and Docker is
    not installed locally, so confirm the digest in the CI log ("exporting
    manifest sha256:…");
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
