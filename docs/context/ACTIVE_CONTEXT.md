# Active Context: Session Handoff 2026-11-16 (T069)

## Session Metadata

- **Last Updated:** 2026-11-16 (T069 implemented; PR into `dev` for PO
  review)
- **Active Role:** Developer
- **Mode:** EXECUTION. T069 (PO-T069-2026-11-16) waits for PO review of its
  PR and of [ADR-037](../adr/ADR-037-quiz-size-capacity.md) (proposed).
- **Earlier history:** T006-T068, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-COMPLETION-2026-11-14 (Question Bank Final Delivery): T067 and
T068 are released and accepted. T069 (quiz sizes 5-30) is implemented and
in review; T070 (end-to-end acceptance) follows. The Question Bank feature
stays open until its production capabilities are demonstrated. T069 must not
be merged or deployed without PO review.

## Handoff Summary

### Completed

- **T068 release and acceptance:** `v2026.11.16-1` (PR #74, `main`
  `2bd7dad`) deployed with `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`.
  Evidence: [T068 result](../progress/task_T068_result.md), `44b6e7c`.
- **T069 (PO-T069-2026-11-16):** see
  [T069 result](../progress/task_T069_result.md).
  - `app/practice/capacity.py`: exact per-size count by stage (plan,
    generated, approved). It agrees with the composer when there are no near
    duplicates.
  - Tutor "Cobertura del banco" (`GET /api/tutor/coverage`): available
    sizes, blockers of the next size with pending questions, progress toward
    30. `replenish capacity` gives the same report on the command line.
  - Four-subject synthetic regression for sizes 5-30 (API, plus browser on
    desktop and phone). The CI browser step now runs 5 browser tests.
  - Production capacity (read-only): the 100-cell plan holds whole-subject
    mixed sizes 5-30 everywhere. Generation is the first missing stage for
    every unavailable size. Approving all 23 pending questions opens no new
    size.
  - ADR-037 (proposed) covers explicit-level 25/30 (16 appended cells) and
    rejects single-objective expansion.

### Current State

- **Production:** `v2026.11.16-1` (T066, T067, T068), `STATUS HEALTHY`.
  The app and tutor containers run `@sha256:47431d24…ee8e`.
- **`main` and `dev`:** both `2bd7dad`.
- **Branch `feat/T069-quiz-sizes`:** T069 code, tests and docs, plus the
  T068 release evidence (`c655504`, `44b6e7c`). PR into `dev`.
- **Review queue:** 23 pending (Español 7, Matemáticas 6, Ciencias 6,
  Estudios Sociales 4), awaiting the tutor's first review in the
  dashboard. No verdict may be recorded on the tutor's behalf.
- **Composes now (whole subject, mixed):** Matemáticas 5 and 10; Español,
  Ciencias and Estudios Sociales none.
- **Missing approved questions for size 30:** Matemáticas 11, Español 22,
  Ciencias 23, Estudios Sociales 19. Hard is the scarcest level everywhere.
- **Locks:** none held. There is no lane claim in this project. The
  replenish lock (4047, 0) and review lock (4047, 1) are
  transaction-scoped.

### Next Steps

1. The PO reviews the T069 PR, then decides on ADR-037: no change to the
   plan, or 16 appended cells for explicit-level sizes 25 and 30.
2. After merging, release and deploy under a PO authorization. Then check in
   production, read-only:
   - the coverage view;
   - `replenish capacity`.
3. The tutor reviews the queue in the dashboard. Watch the backlog: pause the
   scheduler if the queue passes 40 before the first review session. Pausing
   needs PO authorization.
4. T070 end-to-end acceptance, once sizes beyond 10 compose in production.

### Blockers/Issues

- PO review of the T069 PR and a decision on ADR-037.
- Tutor review time limits how fast the inventory grows. The queue grows
  by up to about 3 candidates every 3 hours.
- Any plan extension (ADR-037) needs PO approval. The 100-cell plan already
  holds whole-subject mixed sizes 5-30; only explicit-level 25/30 and
  single-objective sizes are structurally limited.
- `replenishment.run` marks every difficulty `candidates_generated`;
  cells without a candidate are later labelled `reviewed` (follow-up).
- Pending PO decision: narrow the `mentorpro` sudo rule.
- `tests/app/test_practice_browser.py` is still opt-in and is not run in
  CI.

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
  - Capacity (after T069 is deployed): `replenish capacity --subject <s>`
    (sizes by stage, the plan's structural limits). Before deployment,
    send the module source inline as T069 did.
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
