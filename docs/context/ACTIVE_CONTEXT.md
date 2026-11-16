# Active Context: Session Handoff 2026-11-15

## Session Metadata

- **Last Updated:** 2026-11-15 (`v2026.11.16-1` published, not deployed)
- **Active Role:** Developer
- **Mode:** EXECUTION. Release PO-T067-T068-PROD-2026-11-14 is paused
  before the server steps.
- **Earlier history:** T006-T066, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-COMPLETION-2026-11-14 (Question Bank Final Delivery): T067
coverage-driven generation, T068 tutor review dashboard, T069 quiz sizes
5-30, T070 end-to-end acceptance. Now: deploy the combined T067 + T068
release under PO-T067-T068-PROD-2026-11-14, then T069 design and
implementation. T069 is not to be merged or deployed without PO review.

## Handoff Summary

### Completed

- **T068 corrective (PO-T068-CORRECTIVE-2026-11-14):**
  - Tutor startup now applies the existing Question Bank schema, which
    adds the review `comment` column. This is done through
    `ReviewQueue.ensure_schema()`, which reuses the `QuestionBank`
    initialization (`cd22b5f`). A regression test covers starting from the
    previous schema.
  - The T068 Playwright browser test runs in CI with Chromium installed,
    and the step fails if the test is skipped (`30a5dac`).
  - PR #73 CI run 43670655765 green. ACE gate `VERIFY_RESULT=pass
    gate=all` (1172 passed, 10 skipped). The explicit browser run executed
    9, passed 9, skipped 0.
  - Evidence is in [T068 result](../progress/task_T068_result.md).
- **T068 merge:** the PO merged PR #73 into `dev` as `f2f308c`. `dev` CI
  run 43672511622 green.
- **Release PR #74 (`dev` to `main`):**
  - PR CI run 43782145310 green.
  - Merged with `--match-head-commit f2f308c`; `main` is now `2bd7dad`.
  - `main` CI run 43783087848 green: Python Tests, Release Identity,
    Validate and Publish Docker Image, Tag and Release.
- **Release `v2026.11.16-1`:**
  - Image `ghcr.io/jonnabio/mentor-pro@sha256:47431d24b3bb4d385081ac5d20a8c273e0252b2b83c46ec96620f9541b23ee8e`.
  - Downloaded manifest sha256
    `69311fd1ed979627206cd8d7602b0d33d61498a4f484d0a4812399138260c7bb`.
  - Manifest content: schema 0001..0001; student and tutor smoke tests
    pass; commit `2bd7dad`.
- **`dev` synced:** fast-forwarded to `main` (`2bd7dad`).

### Current State

- **Production:** still `v2026.11.13-1` (T066). Nothing on the server was
  touched this session: no manifest copy, preflight, backup or deploy.
- **`main` and `dev`:** both `2bd7dad`. They contain T067 and T068.
- **Branch `feat/T069-quiz-sizes`:** created from `dev`. It holds only
  this handoff, and no PR is open. T069 code has not started.
- **Bank:** one real pending Español candidate awaits the tutor. No verdict
  has been recorded on the tutor's behalf, and none may be.
- **Sizes offered:** unchanged from T066. Do not claim 30-question quizzes
  until the real composer confirms them.
- **Locks:** none held. There is no lane claim in this project. The
  replenish lock (4047, 0) and review lock (4047, 1) are
  transaction-scoped.

### Next Steps

1. Make sure Tailscale on the workstation is connected, then check that
   `ssh jonnabio@100.64.84.15` works.
2. Continue PO-T067-T068-PROD-2026-11-14 for `v2026.11.16-1`:
   1. `gh release download v2026.11.16-1 -p release-manifest.json`, `scp`
      it to `/opt/mentor-pro/manifests/v2026.11.16-1.json`, and compare
      its sha256 with `69311fd1…60c7bb`.
   2. Run preflight, then `backup` and `verify-backup <dump>`.
   3. Deploy with `--window T067-T068-RELEASE-<date>
      --authorization PO-T067-T068-PROD-2026-11-14`.
   4. Confirm smoke 13/13 and `STATUS HEALTHY`.
3. Post-deploy acceptance, read-only:
   - the tutor container added `generation.bank_item_review.comment`, and
     the historical verdict count is unchanged;
   - the "Revisión de preguntas" section is shown through the tutor
     tunnel;
   - the pending Español question is visible, with no decision recorded;
   - T067 priorities cover the eight known missing objectives;
   - the T066 scheduler is enabled, within its limits, and on free models
     only.
4. Give the PO the tutor URL (`http://127.0.0.1:8081/tutor` through the
   tunnel) and the review steps.
5. Record the release and acceptance evidence in the T067 and T068 result
   files and this file, inside the T069 PR rather than a docs-only PR.
6. T069 (quiz sizes 5-30): Analyze, Discuss, Plan, Execute, Verify on
   `feat/T069-quiz-sizes`. Then open a PR into `dev` for PO review. No
   merge or deploy without approval.

### Blockers/Issues

- **Workstation cannot reach the server:** Tailscale is stuck in
  "starting" (`NoState`), and SSH to `100.64.84.15:22` times out. This
  blocks every server step of the release.
- Tutor review time limits how fast the inventory can grow.
- `replenishment.run` marks every difficulty `candidates_generated`;
  cells without a candidate are later labelled `reviewed` (follow-up).
- Pending PO decision: narrow the `mentorpro` sudo rule.
- If the database is unreachable when the tutor service starts, the
  review schema is applied on the first review request instead. This is
  accepted behavior.
- `tests/app/test_practice_browser.py` is still opt-in and is not run in
  CI.

### Notes

- **Session slip 2026-11-14:** prompts for another repository
  (`xai-eval-framework`) were executed in this session. Check which
  project a pasted prompt targets before acting on it.
- **Release tags use the UTC date.** The release created on the evening
  of 2026-11-15 local time is `v2026.11.16-1`.
- **Review via dashboard:** open the tunnel with `ssh -N -L
  8081:127.0.0.1:8081 jonnabio@100.64.84.15`, go to
  `http://127.0.0.1:8081/tutor`, enter the tutor code, then open
  "Revisión de preguntas". The CLI (`item-review-record --reviewer
  tutor`) still works.
- **Browser test:** the CI step runs `test_review_in_the_browser` with
  `MENTOR_PRO_BROWSER=1` and fails if it is skipped. To run it locally:
  `MENTOR_PRO_BROWSER=1 .venv/Scripts/python.exe -m pytest
  tests/app/test_tutor_review.py -rA`.
- **Windows shell:** never run `python -` or `cat >` with empty stdin,
  since both hang. Write scripts to the scratchpad and pass `</dev/null`.
  Python `write_text` on Windows writes CRLF, so normalize with `sed -i
  's/\r$//'`.
- **Deploy, unattended:** `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`;
  `preflight "$M"`, `backup`, `verify-backup <dump>`, `deploy "$M" --backup
  <dump> --window <ref> --authorization <ref>`, `status`. Manifest: `gh
  release download <tag> -p release-manifest.json`, `scp` to
  `/opt/mentor-pro/manifests/<tag>.json`, compare sha256. Stop on any other
  result; never restore or roll back automatically.
- **Review recording:** only verdicts stated by the human tutor. The
  dashboard stores a reason code and an optional comment. The CLI stores
  reason codes only: copy the decisions file into the app container with
  `docker cp`, run `python -m app.practice.seed_bank item-review-record`
  once, then delete both the container copy and the host file.
- **Composer checks:** `seed_bank compose-check --subject <s>` (read-only)
  and `POST /api/practice/availability`.
- **Release flow:** feature PR into `dev`, then `dev` to `main` with
  `--match-head-commit`. Afterwards, sync `dev` from `main`
  (`git push origin origin/main:refs/heads/dev`).
- **Environment changes** need the administrator force-recreate: `sudo
  docker compose -p mentor-pro -f /usr/local/lib/mentor-pro/compose.yml
  --env-file /opt/mentor-pro/release.env up -d --no-deps --force-recreate
  app`.
- **Gate:** `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`,
  about 8 min). Records go in the next functional PR, never a docs-only
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
