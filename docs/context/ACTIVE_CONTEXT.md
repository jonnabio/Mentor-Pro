# Active Context: Session Handoff 2026-11-16

## Session Metadata

- **Last Updated:** 2026-11-16 (`v2026.11.16-1` deployed and accepted)
- **Active Role:** Developer
- **Mode:** EXECUTION. T069 is in Discuss: its scope awaits a PO decision.
- **Earlier history:** T006-T068, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-COMPLETION-2026-11-14 (Question Bank Final Delivery): T067 and
T068 are released and accepted. Next is T069 (quiz sizes 5-30), then T070
(end-to-end acceptance). T069 must not be merged or deployed without PO
review.

## Handoff Summary

### Completed

- **T068 corrective (PO-T068-CORRECTIVE-2026-11-14):**
  - Tutor startup applies the Question Bank schema through
    `ReviewQueue.ensure_schema()` (`cd22b5f`).
  - The T068 Playwright browser test runs in CI and fails if skipped
    (`30a5dac`).
  - The PO merged PR #73 into `dev` as `f2f308c`.
- **Release PR #74:** merged into `main` as `2bd7dad`. `main` CI run
  43783087848 green. Tag `v2026.11.16-1`, image `sha256:47431d24…ee8e`,
  manifest sha256 `69311fd1…60c7bb`. `dev` synced to `main`.
- **Deploy (PO-T067-T068-RESUME-2026-11-15):** server steps resumed after
  Tailscale was restored.
  - Preflight `DEPLOY COMPATIBLE`.
  - Backup `mentor_pro_2026-11-16_012303.dump`, `VERIFY OK`.
  - Window `T067-T068-RELEASE-2026-11-16`: `DEPLOY OK`, smoke 13/13,
    `STATUS HEALTHY`.
- **Production acceptance (read-only):**
  - `comment` column created; 41 historical verdicts unchanged
    (fingerprint `44c18195…e801`).
  - The dashboard shows "Revisión de preguntas"; the API returns 403
    without the token.
  - 23 questions pending review, no verdicts recorded.
  - T067 first tier is the eight PO objectives.
  - T066 scheduler: enabled, 10 calls per tick, 140 calls since 2026-11-14,
    all free.
  - Evidence: [T068 result](../progress/task_T068_result.md), commit
    `44b6e7c`.
- **T069 analysis:** sizes 5-30 already exist (T063, offered only when
  they compose). Production composes only Matemáticas at sizes 5 and 10.
  Scope options went to the PO.

### Current State

- **Production:** `v2026.11.16-1` (T066, T067, T068), `STATUS HEALTHY`.
  The app and tutor containers run `@sha256:47431d24…ee8e`.
- **`main` and `dev`:** both `2bd7dad`.
- **Branch `feat/T069-quiz-sizes`:** pushed, no PR open. It holds the
  session handoffs and the T068 release evidence (`c655504`, `44b6e7c`,
  plus this handoff). No T069 code yet, and T069 is not in `tasks.json`.
- **Review queue:** 23 pending (Español 7, Matemáticas 6, Ciencias 6,
  Estudios Sociales 4), awaiting the tutor's first review in the
  dashboard. No verdict may be recorded on the tutor's behalf.
- **Eligible questions:** Matemáticas 42, Español 10, Ciencias 10,
  Estudios Sociales 20.
- **Shortfall for size 30:** Matemáticas 11, Español 22, Ciencias 23,
  Estudios Sociales 19.
- **Locks:** none held. There is no lane claim in this project. The
  replenish lock (4047, 0) and review lock (4047, 1) are
  transaction-scoped.

### Next Steps

1. Get the PO's T069 scope decision. The recommended scope changes no
   inventory or plan:
   - prove sizes 20-30 end to end on the synthetic bank (composer, API,
     browser on desktop and mobile);
   - add a tutor view of the sizes each subject composes and what each
     larger size lacks;
   - keep the T063/RCA-006 rule that a size is offered only after the
     server confirms it.
   Optionally, write an ADR proposing a higher plan ceiling for 25-30,
   for the PO to decide.
2. Add T069 to `tasks.json`, then write the implementation plan. Execute
   on `feat/T069-quiz-sizes`, run the ACE gate, and open a PR into `dev`
   for PO review. The release evidence already on the branch goes in with
   it.
3. The tutor reviews the queue through the dashboard. After that, check
   for new eligible questions and which sizes compose (read-only).

### Blockers/Issues

- PO decision on T069 scope.
- Tutor review time limits how fast the inventory grows. The queue grows
  by up to about 3 candidates every 3 hours.
- Raising the 100-cell plan per subject (needed for 25-30 on some
  objectives) needs PO authorization.
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
