# Active Context: Session Handoff 2026-11-14

## Session Metadata

- **Last Updated:** 2026-11-14 (T067 merged to `dev`; T068 in PR #73)
- **Active Role:** Developer
- **Mode:** EXECUTION, awaiting PO review
- **Earlier history:** T006-T066, deployment stages, ADR-030 to ADR-036:
  see `docs/progress/task_T0xx_result.md`, `docs/planning/`, release
  records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QBANK-COMPLETION-2026-11-14 (Question Bank Final Delivery): T067
coverage-driven generation -> T068 tutor review dashboard -> T069 quiz
sizes 5-30 -> T070 end-to-end acceptance. One increment at a time: ACE
gate, PR into `dev`, PO review, release only after approval, verify.

## Handoff Summary

### Completed

- **T066** released (`v2026.11.13-1`), activated and accepted in
  production (records on `dev`: `4371f11`, `0695664`, `6c8ab99`).
- **T067 coverage-driven generation priority:** PR #72 merged into `dev`
  as `8aeaad9` (CI 43614514102 green). Not yet released to `main`.
- **T068 tutor review dashboard:** branch
  `feat/T068-tutor-review-dashboard`, commit `a53a458`, PR #73 into `dev`
  (open). "Revisión de preguntas" section in the tutor page; `GET
  /api/tutor/review/queue`, `POST /api/tutor/review/decisions` (tutor
  service only, existing tutor check); verdicts via
  `seeding.item_review_record` with advisory lock (4047, 1) and 409
  `already_reviewed`; additive `comment` column on
  `generation.bank_item_review`. 7 API tests + Playwright browser test;
  full ACE gate `VERIFY_RESULT=pass gate=all`.
  [T068 result](../progress/task_T068_result.md).

### Current State

- **Production:** `v2026.11.13-1` (T066). T067 and T068 are not deployed.
- **`dev`:** `8aeaad9` (T067 merged). PR #73 open, not merged: it needs
  PO review; never merge it unreviewed.
- **Bank:** one real pending Español candidate awaits the tutor; no
  verdict was recorded on the tutor's behalf.
- **Sizes offered:** unchanged from T066 (T069 not started); do not claim
  30-question quizzes until the real composer confirms them.
- **Locks:** none held (no lane claim in this project; replenish tick
  lock (4047, 0) and review lock (4047, 1) are transaction-scoped).

### Next Steps

1. PO reviews PR #73 (T068); address feedback; merge into `dev` only
   after approval.
2. With PO release authorization: `dev` -> `main` (T067 + T068) with
   `--match-head-commit`, deploy, smoke, record evidence in the next
   functional PR.
3. Tutor reviews the pending Español candidate in the production
   dashboard (T068 acceptance). Do not infer decisions.
4. Start T069 (quiz sizes 5-30) from `dev`.

### Blockers/Issues

- PO review of PR #73 and release authorization for T067 + T068.
- Tutor review time bounds inventory growth.
- `replenishment.run` marks every difficulty `candidates_generated`;
  cells without a candidate are later labelled `reviewed` (follow-up).
- Pending PO decision: narrow the `mentorpro` sudo rule.

### Notes

- **Session slip 2026-11-14:** two "Paper G" prompts for another
  repository (`xai-eval-framework`) were pasted into this session and
  executed there (its PRs #119, #120 merged). Mentor-Pro was not touched by
  that work. Check which project a pasted prompt targets before acting.
- **Review via dashboard:** tutor tunnel `ssh -N -L 8081:127.0.0.1:8081
  jonnabio@100.64.84.15`, section "Revisión de preguntas". The CLI
  (`item-review-record --reviewer tutor`) still works.
- **Windows shell:** never run `python -` with an empty heredoc; write
  scripts to the scratchpad instead.
- **Deploy, unattended:** `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"`;
  `preflight "$M"`, `backup`, `verify-backup <dump>`, `deploy "$M" --backup
  <dump> --window <ref> --authorization <ref>`, `status`. Manifest: `gh
  release download <tag> -p release-manifest.json`, `scp` to
  `/opt/mentor-pro/manifests/<tag>.json`, compare sha256. Stop on any other
  result; never restore or roll back automatically.
- **Review recording:** decisions file into the app container (`docker
  cp`), `python -m app.practice.seed_bank item-review-record --subject <s>
  --decisions <file> --reviewer tutor` once, delete the copy and the
  host file. Only verdicts stated by the human tutor; the CLI stores
  reason codes only (the T068 dashboard also stores an optional comment).
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
