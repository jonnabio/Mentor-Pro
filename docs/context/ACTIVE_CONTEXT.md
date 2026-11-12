# Active Context: Session Handoff 2026-11-12

## Session Metadata

- **Last Updated:** 2026-11-12 (Phase B activated in production; T065
  generation-quality fix merged into `dev` via PR #68; not released)
- **Active Role:** Developer
- **Mode:** EXECUTION
- **Earlier history:** T006-T055, deployment stages 6.1-6.3, ADR-030 to
  ADR-035: see `docs/progress/task_T0xx_result.md`, `docs/planning/`,
  release records in `docs/progress/` and this file's Git history.

## Current Objective

PO-QUESTION-BANK-COMPLETION-2026-11-11 (CRITICAL): make bank-only quiz
sizes 10-30 operational. First milestone: a genuine 10-question
Matemáticas practice. Increments: A generation quality (done, unreleased),
B inventory via free runs plus tutor review, C sizes 10-30, D
replenishment verified end to end.

## Handoff Summary

### Completed

- **Phase B release** `v2026.11.10-1` (T061-T064: reliability, sizes,
  inventory, replenishment): PR #66 merged as `f207de4`, release PR #67
  as `74eaaea`; deployed, `STATUS HEALTHY`, smoke 13/13.
- **Phase B activation** (no code): the administrator set
  `MENTOR_PRO_BANK_ONLY_SUBJECTS=matematicas:5,10,15,20,25,30` and
  force-recreated the app; loaded config verified
  (`{'matematicas': (5, 10, 15, 20, 25, 30)}`). Bounded free runs, review
  files prepared, tutor API verified (403 without token, 200 with it),
  low-yield diagnosis. Evidence:
  [Phase B activation](../progress/2026-11-10-phase-b-activation.md).
- **T065 Increment A** (generation quality): generation prompt 1.4.0
  (`SUBJECT_DIFFICULTY`, `GROUNDING_RULE`), `item_checker.py` 1.7.0
  (`coordinated_phrases` for F01). Rubric, thresholds, solve, duplicate
  checks, limits and paid settings unchanged. Evidence: grounding replay
  32/42 -> 38/42 (the 4 left are genuine); live benchmark accepted 2/12 ->
  7/12, calls per accepted 24.0 -> 7.7, difficulty pass 2/14 -> 7/14.
  [T065 result](../progress/task_T065_result.md). Tools:
  `scripts/dev/replay_grounding.py`,
  `scripts/dev/benchmark_generation_quality.py`.
  - Branch `fix/T065-generation-quality`, PR #68 into `dev` (CI
    43161957071 green; full ACE gate pass), merged into `dev` at
    session end on the user's instruction.
- `tasks.json`: T061-T064 `done`, T065 `in_progress`.

### Current State

- **Production:** `v2026.11.10-1` (digest `a07867c8…3aef`), `STATUS
  HEALTHY`, smoke 13/13. T065 is **not deployed**. Latest backup
  `mentor_pro_2026-11-11_035231.dump` (sha256 `c22243c8…7b3a`) `VERIFY
  OK`. Paid generation off.
- **Availability:** every subject offers size 5 only. Matemáticas mixed
  composes 5 from the bank; easy/medium/hard fall back to generation.
- **Inventory (eligible / pending tutor / quarantined):** Matemáticas
  30/5/1, Estudios Sociales 14/3/0, Español 8/0/0, Ciencias 5/3/0.
- **Size gaps (mixed, whole subject):** Matemáticas size 10 lacks one
  approved question each in M07, M12, M20 (15/20/25/30 lack 7/10/13/18).
  Español size 5 short 3, size 10 short 6 objectives; Ciencias size 5
  short 4, size 10 short 8; Estudios Sociales size 5 short 3, size 10
  short 6.
- **Repository:** `main` `74eaaea`; `dev` contains PR #68 plus this
  handoff; no `dev` -> `main` release yet.
- **Locks:** none (no seeding advisory lock, no lane claim, no paid
  operation `in_use`).

### Next Steps

1. Get PO approval for the release of T065, then open the `dev` -> `main`
   release PR (`--match-head-commit`), verify tag and GitHub Release.
2. Deploy: manifest download and sha256 compare, preflight, backup,
   verify-backup, deploy, status, smoke.
3. Targeted free runs: `seed_bank run --subject matematicas --objective
   M07|M12|M20 --max-calls ...` within daily limits, then the other
   subjects' gaps (`replenish run` orders alphabetically, so target
   objectives explicitly).
4. Export review files including the 11 existing pending questions;
   record only authentic tutor verdicts (`item-review-record --reviewer
   tutor`); delete the review files after recording.
5. Recount inventory, check `POST /api/practice/availability` for
   Matemáticas size 10; verify replenishment end to end; record merge
   SHAs, CI and deployment in `task_T065_result.md` and `tasks.json`.

### Blockers/Issues

- **PO release approval** for T065 (merged into `dev`, unreleased).
- **Tutor review:** size 10 opens only after M07, M12, M20 questions are
  approved by the tutor; 11 questions already pending.
- Hard Ciencias/Estudios Sociales items under prompt 1.4.0 are often
  rejected for near-identical options (C04, correct rejection); possible
  follow-up prompt work.
- Replenishment prioritisation is alphabetical by objective; possible
  code follow-up (PO decision).
- Pending PO decision: narrow the `mentorpro` sudo rule (see Git history
  2026-11-06 for the recommendation).
- Root-owned tool copy: when a release changes `deploy/`, the
  administrator re-runs the three `sudo install` commands.
- Environment changes need the administrator force-recreate:
  `sudo docker compose -p mentor-pro -f
  /usr/local/lib/mentor-pro/compose.yml --env-file
  /opt/mentor-pro/release.env up -d --no-deps --force-recreate app`
  (`deploy` on an unchanged digest does not reload env).
- Older items (T034, T035, CI skips 102 tests, student name in commit
  `42adbe7`, `origin/copilot/clean-repository`, markdown lint debt): see
  this file's Git history at 2026-11-06.

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
- **`llm` migrations:** `docker run --rm --network mentor-pro_default -e
  DATABASE_URL -e PGPASSWORD --entrypoint python <image@digest> -m
  app.llm.migrate status|apply [--dry-run]`, with both variables taken
  from the app container and never printed. Always after a verified
  backup.
- **Review recording:** copy the decisions file into the app container
  (`docker cp`), run `python -m app.practice.seed_bank
  item-review-record --subject matematicas --decisions <file> --reviewer
  tutor` once, delete the copy, then `seed_bank report --cells`. Only a
  verdict confirmed by the human tutor may be recorded.
- **Release flow:** feature PR into `dev`, then a `dev` → `main` PR
  (merge with `--match-head-commit`). The `main` run tags, publishes to
  GHCR and creates the GitHub Release; `dev` runs skip Tag and Release.
  A release PR may come from a handoff branch (`dev` plus the docs
  record); sync `dev` from `main` afterwards.
- **Switch check:** `/etc/mentor-pro` is root-only and production reads
  are blocked for the agent; the administrator runs `sudo grep -c
  '^MENTOR_PRO_BANK_ONLY_ENABLED=' /etc/mentor-pro/app.env` (expect `0`).
- **Server:** `ssh jonnabio@100.64.84.15` (docker group).
  - Student app: `127.0.0.1:8080` and `192.168.50.229:8080`.
  - Tutor: `127.0.0.1:8081` only, through
    `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`, then open
    `http://127.0.0.1:8081/tutor`.
- **Gate:** `bash .ace/scripts/verify.sh` (`VERIFY_RESULT=pass gate=all`,
  4–12 min). Run pytest with `.venv/Scripts/python.exe`
  (run `tests/app` and `tests/ace` separately; their conftests clash).
  On Windows, edit
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
