# Active Context: Session Handoff 2026-10-28

## Session Metadata

- **Last Updated:** 2026-10-28 (T044 = I4 implemented; PR #21 to `dev`
  for review)
- **Active Role:** Developer
- **Mode:** EXECUTION
- **Session span:** 2026-10-22 to 2026-10-25 (T006–T031, CI fixes 1–3,
  GHCR) and 2026-10-26 to 2026-10-27 (deployment Stages 6.1–6.3: RCA-005,
  ADR-030, production on macedonianserver, home Wi-Fi access) and
  2026-10-27 to 2026-10-28 (T032 writing bank, T033 tutor service,
  ADR-031, production rollout of both) and 2026-10-28 (T036 student
  attempt data foundation, feature branch only)

## Current Objective

**T036 — student attempt data foundation (ADR-032): merged into `dev`,
not deployed.** PR #11 merged as `dab1550` (2026-10-28); `dev` push CI
[40694417061](https://github.com/jonnabio/Mentor-Pro/actions/runs/40694417061)
green (506 passed, 102 skipped; image build, `GET /` and tutor smoke; no
publication from `dev`). PO decisions: (1) refuse startup on an unmigrated
schema — APPROVED; (2) attempt-level uniqueness replaces
`uq_submission_exercise` — APPROVED; (3) attempt 1 follows editorial
revisions until submitted, revisions pinned — APPROVED; (4) merge to `dev`
— done (CI cannot run on PRs into `dev`; PO chose merge then verify the
push CI); (5) production migration, deployment, merge to `main`,
infrastructure — NOT AUTHORIZED. Details:
[T036 result](../progress/task_T036_result.md).

**T037 — "Mejorar mi respuesta": merged into `dev`, not deployed.** PR #13
merged as `6ed9703`; `dev` CI
[40745285425](https://github.com/jonnabio/Mentor-Pro/actions/runs/40745285425)
green (519 passed, 102 skipped; image built and smoke-tested; GHCR publish
skipped). [T037 result](../progress/task_T037_result.md).

**T038 — tutor re-evaluation: merged into `dev`, not deployed.** PR #14
(head `13851f4` unchanged) merged as `b0a3509`; `dev` CI
[40760514180](https://github.com/jonnabio/Mentor-Pro/actions/runs/40760514180)
green (524 passed, 102 skipped; image built, both smoke tests passed; GHCR
login and publish skipped). Integrated.
[T038 result](../progress/task_T038_result.md).

**T040 — deployment assessment: merged into `dev`.** PR #15 (docs only)
merged as `e368c9c`; `dev` CI 40770016065 green (524 passed).
[ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md) accepted as
the direction (PO 2026-10-28): `release.env` exception, tags
`vYYYY.MM.DD-N` and immutable manifests, rehearsal with a production
dump copy in principle (only with controls R4 to R6), primary
administrator as the only operator, retention of ten routine plus all
pre-migration dumps without automatic deletion. Refinements R1 to R8
recorded. Approval is not authorization for every increment.
[T040 result](../progress/task_T040_result.md).

**T041 — ADR-033 I1: merged into `dev`.** PO corrections (tutor health
check only on 403; `status` never reports unknown as healthy) applied;
PR #16 merged as `cf43e91`; `dev` CI 40781126775 green (539 passed).
Compose CLI validation not run locally (no Docker); a Docker-gated test
is in T042. [T041 result](../progress/task_T041_result.md).

**T042 — ADR-033 I2 (restore-checked backup): merged and verified.** PO
pre-merge changes (full fingerprint scope, unexpected or missing schemas
fail, mandatory Docker tests in CI, limits documented) applied; local
gate 651 passed. PR #17 merged as `4efed63`; `dev` CI 40787440842 green
(542 passed, 111 skipped), both Docker tests executed and passed.
[T042 result](../progress/task_T042_result.md).

**T043 — ADR-033 I3: merged and verified on `dev`.** PR #19 (head
`e6a9877`) merged as `474774e`; `dev` CI 40809496126 green (568 passed,
Docker tests mandatory, `LABELS OK`, both smoke tests, `MANIFEST OK`
dry-run; publish and Tag and Release skipped; no tag or release exists).
Not release-ready: `v*` ruleset missing, real GHCR digest path and
partial-release recovery unverified. Plan PR #18 merged as `22a6847` (`dev` CI 40790275976
green). Release identity before the build, OCI labels with the
code-defined schema range, validated manifests (dry-run artifact off
`main`), guarded publication and tag/release on pushes to `main` only,
serialized `main` runs, least privilege, PR CI for `dev`. Local gate 677
passed; PR CI 40792928230 green (first `pull_request` run into `dev`).
`v*` tag ruleset **not configured** (API `[]`); required before the first
authorized release. [T043 plan](../planning/2026-10-28-T043-release-metadata-plan.md),
[T043 result](../progress/task_T043_result.md).

**T044 — ADR-033 I4: implemented, PR #21 to `dev` awaiting PO
approval.** PR #20 merged as `0bcf64d`. `deploy/mentorpro
preflight|deploy|rollback` by digest: manifest file validated (dry-run
refused), registry digest and tag mapping, labels, read-only live schema
(fresh/legacy/current/drifted/corrupt/unreadable), six-hour preflight and
backup evidence bound to the deployment, compatibility rechecked in the
lock, window and PO references recorded (not verified), app and tutor
only, manual rollback only. PR CI 40811750620 green (636 passed; Docker
cycle test with local registry ran). Nothing run on the server. PO
corrections (2026-10-29) applied in `70fa714`: compose failures recorded
as FAILED, final registry identity check under the lock, rollback
provenance (stored manifest or `adopt-legacy`, plus a prior OK run). ACE
gate 754 passed; PR CI 40890220768 green (646 passed).
[T044 result](../progress/task_T044_result.md).

**Release constraints (PO):** T037 and T038 only together; T039 must fix
progress counting of repeated attempts first; the T036 migration needs a
verified backup, isolated restore rehearsal, approved procedure and
explicit production authorization.

**T040 — deployment simplification and repeatability assessment:
registered, pending; approved to start once T038 is reviewable**
(assessment only, no infrastructure or production change).

Milestones: learning — Write → Tutor Feedback → Revise → Resubmit → Tutor
Re-evaluation (needs T038); operational — a predictable, reproducible,
recoverable production deployment (T040).

**T032 + T033 release — deployed; awaiting real-user acceptance.** PR #9
merged as `2f6a4b3`; CI
[40582892305](https://github.com/jonnabio/Mentor-Pro/actions/runs/40582892305)
green. Image
`ghcr.io/jonnabio/mentor-pro@sha256:5d69fe6c2560626afe78a61b04e64e5c81b59eff4b2a73f6bd0327756a6e1137`.

Production rollout (administrator-run, PO-authorized, 2026-10-28 server
time), observed results:

1. Backup: `mentor_pro_2026-10-28_002257.dump`, `BACKUP OK`, 127791 bytes,
   `600 root`, `pg_restore --list` passed.
2. App: digest updated (only the image line changed); `/`,
   `/api/subjects`, `/api/dashboard`, `/api/writing/levels` 200 and
   `/tutor`, `/api/tutor/queue` 404 on `127.0.0.1:8080` and
   `192.168.50.229:8080`; PostgreSQL healthy.
3. Bank: dry run 11 imported / 0 rejected; import 11; re-import 0
   imported / 11 unchanged; student records untouched; L1 3, L2 3, L3 3,
   L4 2, L5 0; no references in student API; quarantined 404.
4. Tutor: pre-checks passed (no tutor key in `app.env`, gateway
   `172.19.0.1`, no host networking); `tutor.env` root `600`, token 48
   characters (never displayed); bound to `127.0.0.1:8081` only; refused on
   Wi-Fi, Tailscale and wired addresses; no token / wrong token / forged
   `X-Forwarded-For` 403, valid token 200; student routes 404; token absent
   from logs; requests from the gateway. Defect T035: a 1–15 character
   token exits 1 instead of 78 (still refused to start).

| State | T032 writing bank | T033 tutor service |
| --- | --- | --- |
| Implemented / tested / published | yes | yes |
| Deployed | yes (11 exercises) | yes (`127.0.0.1:8081`) |
| Validated by real users | no | no |

Release entry written to `/opt/mentor-pro/RELEASES`
(`2026-10-28T01:10:25+00:00`); temporary stage scripts and bank reports
removed from `/tmp` (both checked over SSH).

**T032/T033 are implemented, tested and deployed, but have not yet passed
the real-user production acceptance test.** Remaining: the student writes,
reloads and submits; the parent reviews through the SSH tunnel; the
feedback survives an app restart (Next Steps 1–4).

**Stage 6.3 closing / Stage 6.4 next** (deployment track). Mentor Pro runs
in production on macedonianserver and is reachable from the house Wi-Fi.
Remaining for Stage 6.3: the student's first real practice from the
student's own device (criterion 8 of ADR-030) and the initial-content
decisions below. Stage 6.4: controlled promotion of approved images to the
server with health checks and a tested rollback.

Still queued: **Task 3 — CI maintenance** (`actions/checkout@v4` and
`actions/setup-python@v5` upgrades, review `docker/*` actions, pin
`ubuntu-24.04`, optional image slimming keeping `.ace/schemas/`).

Standing rule: plan each Product Owner task with an ADR first. Do not start
L5, 10–30 question sets or new features without approval.

## Handoff Summary

### Completed

Baseline before this session: ACE 2.7.0 reset, T001 skills and checker
(ADR-005), T002 baseline `PNE2026-SUM-v1.0` (ADR-006), T003 PostgreSQL
catalog (ADR-007), T004 configuration API and UI (ADR-008), T005 OpenRouter
client and budgets (ADR-009).

This session (reports in `docs/progress/task_T0xx_result.md`):

Multiple choice and learning data

- **T006** — single grounded question for M02, C01, EL01, ES01
  ([ADR-010](../adr/ADR-010-single-question-generation.md)).
- **T007** — validated 5-question practice sets, checker 1.5.0
  ([ADR-011](../adr/ADR-011-validated-practice-sets.md)).
- **T008** — bounded parallel slots, atomic `BudgetGate`
  ([ADR-012](../adr/ADR-012-controlled-parallel-generation.md)).
- **T009** — checker 1.6.0 maths proofs; RCA-002 and guard.
- **T010** — student practice in the web page; `practice_e2e.py`
  ([ADR-013](../adr/ADR-013-student-practice-sessions.md)).
- **T011–T012** — generation token limit 4000, truncation detection, menu
  navigation, Super VL excluded from generation.
- **T013** — validated question bank
  ([ADR-014](../adr/ADR-014-validated-question-bank.md)).
- **T014** — learning dashboard, six statuses
  ([ADR-015](../adr/ADR-015-repeat-aware-learning-status.md)).
- **T015** — "Salir de la práctica" with confirmation.
- **T016** (PO T014.1) — automation uses only `mentor_pro_test`
  ([ADR-016](../adr/ADR-016-test-database-isolation.md)).
- **T017** — historical test sessions classified out of learning metrics
  ([ADR-017](../adr/ADR-017-session-classification.md)).
- **T018** — dashboard click race fixed; gate keeps per-gate logs
  ([RCA-003](../rca/RCA-003-intermittent-gate-and-browser-failures.md)).
- **T019** — "Practicar / Repasar este objetivo" from the dashboard
  ([ADR-018](../adr/ADR-018-dashboard-driven-practice.md)).

Producción escrita (Español, written rubric EE01–EE20)

- **T020** — verbatim MEP 2026 rubric, five levels, contracts, `writing`
  schema ([ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)).
- **T021** — OpenRouter generation of one exercise (L2)
  ([ADR-020](../adr/ADR-020-writing-exercise-generation.md)).
- **T022** — student writing screen: drafts, one submission
  ([ADR-021](../adr/ADR-021-student-writing-practice.md)).
- **T023** — Nivel 1 correction exercises with tutor-only references
  ([ADR-022](../adr/ADR-022-nivel-1-correction-exercises.md)).
- **T024** — L1 editor prefilled with the text; versioned editorial
  revisions; checks W13–W15
  ([ADR-023](../adr/ADR-023-l1-editor-and-editorial-revisions.md)).
- **T025** — L2 and L3 inventory; checks W13–W18 for composed paragraphs;
  ADR-020 amended.
- **T026** — tutor review at `/tutor` with official descriptors, partial
  save, single completion; student feedback
  ([ADR-024](../adr/ADR-024-tutor-writing-evaluation.md)).
- **T027** — Producción escrita as the fifth tab of "Mi progreso":
  activity, coverage, per-criterion latest/best, dimension averages from
  evaluated criteria only
  ([ADR-025](../adr/ADR-025-writing-learning-dashboard.md)).
- **T028** — Nivel 4 guided composition: one real L4 exercise, five-stage
  editor with section drafts, tutor review with optional EE07–EE18
  ([ADR-026](../adr/ADR-026-guided-composition-l4.md)); writing reviews by
  the generator are refused
  ([RCA-004](../rca/RCA-004-writing-review-not-independent.md)).
- **T029** — RCA-004 remediation: eligibility events, independent
  revalidation with the generator excluded, L1 review limit 6000 tokens;
  3 exercises reinstated, `PE-L1-feria-ciencia-escuela-c9576f` still
  quarantined, L1 replacement `PE-L1-huerta-escolar-8c310b`
  ([ADR-027](../adr/ADR-027-writing-exercise-eligibility.md)).
- **T030** — reliable drafts: ordered saves (`client_seq`), autosave in
  L1–L4, keepalive flush on hide/close, "Guardando… / Guardado / No se pudo
  guardar" with retry ([ADR-028](../adr/ADR-028-reliable-draft-saving.md)).
- **T031** — second writing reviewer: `OPENROUTER_WRITING_REVIEW_MODELS`,
  `review_route()` with generator and variant exclusion, revalidation cap 6,
  `benchmark_writing_reviewers.py`; **no candidate qualified** (dots 4/8
  defects; xing and gemma HTTP 429)
  ([ADR-029](../adr/ADR-029-writing-review-fallback.md)).

CI/CD (branch `dev`, merged to `main` by PR #2, merge commit `517a502`)

- **CI Fix 1** (`c41e2d0`) — `QuestionBank` creates the generation tables
  (`GenerationStore`) before its own.
- **CI Fix 2** (`ecf7a31`, `6c6858b`) — both shared `catalog` fixtures skip
  when the baseline workbook is absent (excluded from Git).
- **CI Fix 3** (`e0f06e8`) — `validate_skills.py` accepts the excluded
  `references/original/` when `references/MANIFEST.sha256` exists.
- **GHCR** (`9f69f44`, `4a4014e`) — Docker job logs in and pushes only on
  push to `main`; `.dockerignore` excludes `references/original/` and
  `docs/`. First image published by run 40253896144:
  `ghcr.io/jonnabio/mentor-pro:testing` and
  `:sha-517a50283b7ac720c87e76f551f08f6ed55504a7` (digest
  `sha256:4ab51ff3…a787`); anonymously pullable (public).
- **RCA-005** (2026-10-26, `dev`) — that image cannot start
  (`jsonschema` only in `requirements-dev.txt`); found by the Stage 6.2
  preview on macedonianserver. `jsonschema` moved to `requirements.txt`;
  `docker-build` now builds once, smoke-tests `GET /` (HTTP 200 within
  60 s) and pushes that same image only on `main`;
  `tests/app/test_runtime_dependencies.py`; guard RCA-005
  ([RCA-005](../rca/RCA-005-published-image-cannot-start.md)).
  Merged by PR #4 (`7e45376`); replacement image
  `sha256:486dcc0a…5e20` published after a passing smoke test.

Producción escrita release (T032 + T033, 2026-10-27 to 2026-10-28,
`main` `2f6a4b3`, deployed `sha256:5d69fe6c…1137`; real-user acceptance
pending)

- **T032** — `app/writing/bank.py` (export, import with `--dry-run`,
  inventory) and `tests/app/test_writing_bank.py` (7); rehearsal with the
  real curriculum imported 11, rerun 11 unchanged; runbook section H.
  Tutor root cause: in Docker every request (loopback and Wi-Fi) arrives
  from the bridge gateway `172.19.0.1` and production has no tutor token
  (`/tutor` 404) → ADR-031 (later accepted; T033)
  ([result](../progress/task_T032_result.md)). Import checks: current
  revision contracts, rubric hash and curriculum baseline match, accepted
  generation attempt, RCA-004 independence (or a passed revalidation),
  L1 references, quarantine excluded; one transaction, advisory lock,
  existing records never overwritten, student tables counted before and
  after. PR #6 merged to `main` (`5615eeb`, CI 40519852040).
- **T033** — `app/tutor_main.py` (tutor-only routes; token of at least 32
  characters; allowed hosts exact IPs; fails closed with exit 78;
  `proxy_headers=False`; defined 503 `database_unavailable`) and
  `tests/app/test_tutor_service.py` (37: LAN, other containers, Tailscale,
  absent or wrong tokens, forged forwarding headers, wrong gateway)
  ([ADR-031](../adr/ADR-031-tutor-access-in-production.md) accepted with PO
  security amendments; [result](../progress/task_T033_result.md)). PR #7
  (`5ba650e`) and PR #8 (`079387d`: CI step "Smoke test tutor entrypoint"
  on the same candidate image before publication; RCA-005 gates kept).
- **PR #9** `dev` → `main` merged at approved head `079387d` as `2f6a4b3`;
  CI 40582892305 green on the first attempt (480 passed, 102 skipped; ACE
  skills; `GET /` 200; tutor smoke passed); one build; published
  `ghcr.io/jonnabio/mentor-pro@sha256:5d69fe6c2560626afe78a61b04e64e5c81b59eff4b2a73f6bd0327756a6e1137`
  (tags `testing`, `sha-2f6a4b3…`; confirmed in GHCR).
- **Production rollout** (PO-authorized per stage, administrator-run with
  `sudo`, each result checked over SSH; details in Current Objective):
  backup `BACKUP OK`; app digest updated; 11 exercises imported and the
  re-import unchanged; tutor service provisioned and verified; `RELEASES`
  entry; `/tmp` cleaned.
- **Runbook corrections** (PR #10): section B `pg_dump … </dev/null`
  (compose `exec` read the pasted script and hung); section H bundle owned
  by uid 1000 (container user `mentor`; root-owned gave Permission denied)
  and `run -T … </dev/null`; section J notes T035. Tracker: T034 and T035
  added (pending).

Guided writing revision (ADR-032, 2026-10-28, feature branch)

- **ADR-032** proposed (`e7afb13`) with plan (`d99186d`); PO approved the
  architecture principles and T036 implementation.
- **T036** — `writing.student_attempt`; drafts keyed by attempt;
  `uq_submission_attempt` replaces `uq_submission_exercise`; composite FKs
  keep draft/submission exercise equal to the attempt's; evaluation keys
  unchanged. Versioned migration `0001_student_attempts`
  (`app/writing/migrations.py`, CLI `app/writing/migrate.py`): one
  transaction, preconditions, attempt 1 backfill, before/after digests of
  student tables, ledger `writing.schema_migration`, dry run, rollback
  while only attempt 1 exists. Store: exercise-level methods = attempt 1
  only; `save_attempt_draft`, `submit_attempt`, `start_revision` (no
  route). Tests 19 new; runbook section K (not authorized). Commits
  `1652181`, `8bd806f`, `ce0fa5c` + docs.
- **T036 PO review** — startup guard in both apps (`check_schema()` in the
  lifespan; tutor exit 78 "tutor start refused"; unreachable or
  unconfigured database still 503 on first request); 503
  `schema_migration_required`; old image on a migrated database observed
  (recreates `uq_submission_exercise`, draft saves and new submissions
  fail; startup DDL fails once a revision exists) → state `drifted`
  refused, `python -m app.writing.migrate repair` (`bf2fdb4`); ADR-032
  accepted for T036; runbook K; 26 attempt tests; gate 608 passed; browser
  447/447. Merged by PR #11 (`dab1550`).

Deployment on macedonianserver (2026-10-26 to 2026-10-27)

- **Stage 6.1** — server pulls the image by digest (`linux/amd64`).
- **Stage 6.2** — preview exposed RCA-005; the corrected image serves `/`.
- **ADR-030** (accepted, with runbook corrections)
  ([ADR-030](../adr/ADR-030-production-provisioning-and-deployment.md),
  [runbook](../runbooks/production-deployment.md)): workbook copied under
  its manifest name and checked (`sha256sum -c`), one-time idempotent
  import through the pinned image (`imported`, then `unchanged`), secrets
  moved to `/etc/mentor-pro/app.env` and `postgres.env` (root `0600`; app
  uses `DATABASE_URL` without password plus `PGPASSWORD`), compose file
  without secrets or `${}` interpolation, image pinned by digest, backup
  gate, release log.
- **Stage 6.3 checks** — `/`, `/api/subjects`, `/api/dashboard`,
  `/api/writing/levels` 200 after start, `docker restart` and
  `--force-recreate`; curriculum 98 assertions / 344 evidences unchanged;
  Uptime Kuma and `smbd` unaffected; API practice test (Matemáticas)
  graded and persisted, then classified `automated_test`.
- **ADR-030 section 10** (`5f3843d`) — app also published on the server's
  Wi-Fi address `192.168.50.229:8080` (DHCP reservation), with
  `net.ipv4.ip_nonlocal_bind=1`; verified HTTP 200 from another Wi-Fi
  device, wired address refused. No login (accepted: family-only Wi-Fi).

### Current State

- **T032/T033 are implemented, tested and deployed, but have not yet
  passed the real-user production acceptance test.** No writing draft,
  submission or evaluation exists in production yet.
- **Production (ADR-030, ADR-031):** macedonianserver, project
  `mentor-pro`, `/opt/mentor-pro/compose.deploy.yml`. `mentor-pro-app-1`
  and `mentor-pro-tutor-1` both run
  `ghcr.io/jonnabio/mentor-pro@sha256:5d69fe6c2560626afe78a61b04e64e5c81b59eff4b2a73f6bd0327756a6e1137`
  (`2f6a4b3`); `mentor-pro-postgres-1` (`postgres:17.6`, healthy, volume
  `mentor-pro_postgres_data`, unchanged). App ports `127.0.0.1:8080` and
  `192.168.50.229:8080`; students open `http://192.168.50.229:8080/`
  (tutor routes 404 there). Tutor on `127.0.0.1:8081` only, through
  `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`.
- **Tutor boundary:** token (48 characters, `/etc/mentor-pro/tutor.env`,
  root `0600`, never in `app.env`) plus client address equal to the
  compose gateway `172.19.0.1`; forwarded headers ignored. Verified in
  production: refused on Wi-Fi, Tailscale and wired addresses; no token,
  wrong token and forged `X-Forwarded-For` 403; valid token 200; token not
  in logs.
- Production data: curriculum `PNE2026-SUM-v1.0` (98/344); writing bank
  L1 3, L2 3, L3 3, L4 2, L5 0 (11 eligible, ADR-027); quarantined
  `PE-L1-feria-ciencia-escuela-c9576f` not exported (404 in production);
  one practice session (`0cd5fb94…`, `automated_test`); no student
  sessions or writing work yet.
- Server files: secrets `/etc/mentor-pro/{app,postgres,tutor}.env` (root
  `0600`); bank bundle `/opt/mentor-pro/baseline/writing-bank.json` (uid
  1000, `0600`, contains tutor references; never in Git) next to the
  workbook; compose copies `.pre-t033` (before the digest update),
  `.pre-tutor` (before the tutor service) and older `.bak`, `.pre-adr030`,
  `.pre-wifi`; backups in `/var/backups/mentor-pro/` (root `0700`):
  `mentor_pro_2026-10-28_002257.dump` (127791 bytes, verified, taken
  before the import) and `mentor_pro_2026-10-26_223101.dump` (905 bytes,
  empty database); release log `/opt/mentor-pro/RELEASES` (last entry
  `5d69fe6c…`, 2026-10-28T01:10:25Z); `/etc/sysctl.d/99-mentor-pro.conf`.
- Server access: SSH key login from this PC (`jonnabio@100.64.84.15`);
  `jonnabio` is in the `docker` group (root-equivalent); compose commands
  need `sudo` (root-only env files); the agent cannot use `sudo`.
- Repository: `main` at `2f6a4b3` (the release, unchanged); `dev`
  `dab1550` = `main` + PR #10 (docs) + PR #11 (T036); this closure on
  branch `docs/T036-closure` (PR to `dev`); no task in progress; this repository
  has no lock or lane files; no local server, browser or generation job and
  no production command left running.
- Multiple choice: unchanged since T019 — free models only (paid
  disabled), checker 1.6.0, prompts generation 1.3.0 / rubric 1.1.0,
  generation limit 4000 tokens, daily request budget 1000, daily USD 0.
- Student database: 381 multiple-choice answers (dashboard counts only the
  2 `student` sessions, T017); 0 writing drafts, submissions and
  evaluations.
- Writing bank (eligible, ADR-027): L1 3 (`futbol-comunidad`,
  `manglares-terraba`, `huerta-escolar`), L2 3, L3 3, L4 2
  (`uso-responsable-materiales`, `uso-responsable-redes`), L5 none.
  Quarantined: `PE-L1-feria-ciencia-escuela-c9576f` (no independent review
  yet). Eligibility is the latest row of `writing.eligibility_event`;
  revalidations in `writing.independent_validation`.
- Writing app: main menu → levels → exercises → editor (L1 prefilled; L2–L3
  one text area; L4 five stages with section drafts) → one submission →
  `/tutor` review (L4: EE01–EE06 required, EE07–EE18 optional) → student
  feedback → "Mi progreso" tab "Producción escrita" (ADR-025).
- Drafts (ADR-028): ordered by `writing.draft.client_seq`, autosave 2 s in
  L1–L4, keepalive flush on tab hidden/close, indicator "Guardando… /
  Guardado / No se pudo guardar" with "Reintentar"; DB errors answer 503.
- Writing generation: prompts `writing-1.3` (L2–L5; L4 paragraph plan,
  W19) and `writing-edit-1.1` (L1); checks W01–W19; reviews exclude the
  generator (`route(exclude=…)`, RCA-004); L1 review limit 6000 tokens.
- PostgreSQL `writing` schema adds `eligibility_event`,
  `independent_validation`, `draft.sections/client_seq/exercise_revision`,
  `submission.sections`.
- Writing reviewers (ADR-029): local `.env`
  `OPENROUTER_WRITING_REVIEW_MODELS=nvidia/nemotron-3.5-super-vl:free`
  (primary only); append a model only after it passes the benchmark.
  `minimax/minimax-m3.1-flash:free` is configured but no longer listed.
- CI (GitHub Actions, `.github/workflows/ci.yml`): Python Tests on
  PostgreSQL 17.6 service (102 skipped: no workbook in CI), then Validate
  and Publish Docker Image: build once, smoke test `GET /` (HTTP 200 within
  60 s), tutor entrypoint smoke (exit 78; 403, 404 and 503 boundary
  checks), push that same image to GHCR only on push to `main` (RCA-005).
  Triggers: push to `dev` or `main`, PRs into `main` only.
- T036 verification: `test_writing_attempts.py` 26 passed; ACE gate
  608 passed (`VERIFY_RESULT=pass gate=all`); mocked browser 447/447;
  `dev` CI 506 passed, 102 skipped. Migration exercised only on
  `mentor_pro_test` (synthetic history), never on student or production
  data.
- Tests before T036: 582 passing locally (T032 bank, T033 tutor service); CI 480
  passed, 102 skipped; browser (mocked,
  `mentor_pro_test`) 447/447; live
  draft restart check 4/4; ACE gate `VERIFY_RESULT=pass gate=all`.

### Next Steps

0. **PO review of PR #21 (T044, I4).** Owner to create the `v*` tag
   ruleset, then verify it; validate the real GHCR digest on the first
   authorized release. I5 needs its own approval; I6 onward change
   production. T039 (progress counting) before any T037+T038 release;
   both released together.
   Do not start an image containing T036 in production; a production
   migration needs a restore rehearsal and separate approval (runbook K).
1. **Real-user acceptance test.** On the student's own device
   (`http://192.168.50.229:8080`): Producción escrita → an exercise → type
   a short text → wait for "Guardado" → reload (text remains) → submit →
   status "Pendiente de revisión del tutor".
2. **Parent tutor review.** SSH tunnel, `http://127.0.0.1:8081/tutor`,
   token from `sudo cat /etc/mentor-pro/tutor.env` (kept in a password
   manager); score the rubric, save feedback, mark complete; the student
   sees it.
3. **Persistence.** `sudo docker restart mentor-pro-app-1`; the submission
   and evaluation are still shown. Optional: from the student device
   `http://192.168.50.229:8081/` must fail.
4. **Record acceptance** in this file and the T032/T033 notes from observed
   outcomes only; on a failure open a focused defect and keep the evidence.
5. **Maintenance after acceptance:** T035 (tutor exit 78 for tokens of
   1–15 characters), T034 (deterministic practice-set test), then assess
   CI for PRs into `dev`; each a separate verified change.
6. Stage 6.3 close: the student completes a five-question Matemáticas
   practice from the student's own device at `http://192.168.50.229:8080/`,
   sees the result, and the progress survives an app restart (ADR-030
   criterion 8). Record it in ACTIVE_CONTEXT.
7. Initial content decision (ADR-030 section 7, no new ADR): pre-generate
   a small Matemáticas bank so practice does not wait about 5 minutes
   (writing is provisioned: 11 exercises).
8. Stage 6.4: superseded by ADR-033 (Proposed) increments I1 to I8.
9. Clean up on the server once stable: `*.pre-adr030`, `.bak`,
   `.pre-wifi`, `.pre-t033` and `.pre-tutor` copies.
10. Task 3 — CI maintenance (see Current Objective).
11. Earlier backlog: L5 examination simulation candidate; reopening a
   completed evaluation; rerun `benchmark_writing_reviewers.py` when the
   free listing changes; revalidate `PE-L1-feria-ciencia-escuela-c9576f`
   (local database); `fail_interrupted()` follow-up (T018); suite slowdown.

### Blockers/Issues

- T036: an image containing it refuses to start on the unmigrated
  production database until `migrate apply` runs (fail closed, by design);
  never run a pre-T036 image on a migrated database (ADR-032);
  progress and tutor queue will count revision submissions as activity
  until T039.
- Production practice generation takes about 5 minutes per new set and
  may return `partial` (4 of 5 in the test) until the bank fills.
- **Blocker for closing the release:** the real-user acceptance test
  (student and parent) has not been performed; nothing is marked accepted.
- T035 (maintenance, pending): a tutor token of 1–15 characters refuses
  startup but exits 1 (`ValueError` while importing `app.main`) instead of
  78. Consistency defect; no listener starts; no authentication bypass.
- T034 (maintenance, pending):
  `test_transient_failure_then_success_completes` is nondeterministic with
  parallel slots (failed once in CI 40534292823; the rerun passed).
- CI does not run on PRs into `dev` (only on the push after the merge);
  separate improvement.
- No L5 writing exercises (L5 shows 0).
- No login on the app; anyone on the house Wi-Fi can use it and see
  progress (accepted; revisit if guests join or for outside access).
- `macedonianserver.local` did not resolve for `curl` on this Windows PC;
  use the IP address unless a browser resolves the name.
- After a server reboot, Wi-Fi publication relies on `ip_nonlocal_bind`;
  not yet tested with a real reboot.
- CI skips 102 tests (22 writing tests need the baseline workbook, which is
  not in Git); a green CI run is not a full release gate. Curriculum
  provisioning for CI and the deployed app is still to be decided.
- The GHCR image is public (kept public by decision: no token on the
  server).

- **One generator and one independent reviewer** (free models); a reviewer
  outage blocks new exercises and revalidations (reported as unavailable,
  never bypassed).
- `PE-L1-feria-ciencia-escuela-c9576f` quarantined (RCA-004).
- Draft limits (ADR-028): keepalive bodies above 64 KiB may not arrive on
  close; a crash keeps only server-confirmed text (up to 2 s lost).
- Writing checks are partly keyword-based (W04, W13 voseo list, W16, W19).
- Tutor boundary is a shared token plus the gateway address, not user
  accounts (ADR-024, ADR-031); a completed evaluation cannot be reopened.
  Residual risk: a host-network container or server process reaches
  `127.0.0.1:8081` as the gateway (it still needs the token); recheck the
  gateway if the compose network is recreated (a wrong one fails closed).
- The unexplained T016 `gate=test` failure was never reproduced
  (RCA-003); full logs are kept if it recurs.
- 14 quarantined practice sessions await an optional human review (T017).
  Backup `%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T017_2026-10-24.dump`;
  rollback `scripts/dev/classify_sessions.py --rollback T017-2026-10-24`.
- Property detection (T009) is keyword-based.
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Edge cannot start under automation; browser tests use installed Chrome.
- Docker not installed on this PC; the repository's `docker-compose.yml`
  is untested (production uses the server's `compose.deploy.yml`).
- Student first name in pushed commit `42adbe7`; rewrite needs approval.
- Remote branch `origin/copilot/clean-repository` (merged PR #1) remains.
- Framework markdown lint debt (`docs/TODO-markdown-lint.md`).
- The session-start prompt's `scripts/pubs/check_lane.py` step belongs to
  another project; skip it here.

### Notes

- App: `.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
  (student database; reads `.env`). Restart after code changes. A server
  start marks `queued`/`running` practices as interrupted.
- Tutor review: `http://127.0.0.1:8000/tutor`, code `MENTOR_PRO_TUTOR_TOKEN`
  in the local `.env` (git-ignored; empty disables review).
- Browser tests: `.venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR`
  (mocked; writing, tutor, L4, quarantine and draft scenarios; resets the
  test database's `writing` schema) and `--live`. Live draft check:
  `scripts/dev/draft_restart_check.py DIR` (uvicorn on port 8010, test
  database). All use only `TEST_DATABASE_URL`. Never create artificial
  submissions in the student database.
- Writing commands: `scripts/dev/seed_writing_l1.py`,
  `scripts/dev/seed_writing_l2_l3.py` (L2–L4; `--inventory` read-only),
  `scripts/dev/remediate_writing_review.py [--dry-run]`,
  `scripts/dev/revise_writing_l1.py [--specs FILE] [--dry-run]`,
  `scripts/dev/generate_writing_exercise.py`.
- Backups before real-database changes:
  `%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T029_2026-10-25.dump`
  (`writing`, `llm`); `pg_dump` is in `C:\Program Files\PostgreSQL\17\bin`.
- Release procedure used on 2026-10-28: runbook sections B (backup), F
  (start and verify), H (writing bank:
  `python -m app.writing.bank export|import [--dry-run]|inventory`; local
  export, `scp`, install as uid 1000 `0600`, dry run → import → re-import)
  and J (tutor service). The agent cannot `sudo`: it prepares a script, the
  administrator saves it with a heredoc and runs `bash /tmp/stageN.sh`,
  then the agent verifies over SSH. Lessons: pasted scripts need
  `compose exec/run -T … </dev/null` (otherwise they read the terminal and
  hang); bind-mounted files must be readable by uid 1000; under `set -e`,
  `grep -c` with 0 matches exits 1. Never `docker compose down -v`, never
  restore over the live database, never print env values or the token.
- Production runbook: `docs/runbooks/production-deployment.md`
  (variables `COMPOSE`, `WB`, `WB_SHA`, `DIGEST`; gates `BACKUP OK`,
  `sha256sum -c` OK, `DB OK`). Diagnostics only with redaction; never
  share `docker compose config`, `docker inspect` env or `env` output.
- Server checks without sudo: over `ssh jonnabio@100.64.84.15`, `curl`
  `/`, `/api/subjects`, `/api/dashboard`, `/api/writing/levels` on
  `http://127.0.0.1:8080` (all 200), and `docker port mentor-pro-app-1`.
- Test sessions in production must be classified `automated_test`
  (`practice.session_classification` + `classification_audit`, ADR-017).
- Gate: `bash .ace/scripts/verify.sh`; check its exit code (not a piped
  `tail`) before committing; logs in `.ace/logs/verify/<run>/`.
- Key settings: `OPENROUTER_FREE_MODELS`, `OPENROUTER_GENERATION_MAX_TOKENS`,
  `OPENROUTER_GENERATION_EXCLUDED_MODELS`, `OPENROUTER_MAX_REQUESTS_PER_DAY`,
  `QUESTION_GENERATION_CONCURRENCY`, `MENTOR_PRO_MASTERY_*`,
  `MENTOR_PRO_TUTOR_TOKEN` (see `.env.example`).
- Tracker IDs `^T[0-9]{3}$`; PO labels kept in task names and notes.
- Never expose keys, student data or tutor references; never put the
  student's name in code, tests or commits; `approved_baseline` items are
  not official MEP wording; learning statuses and writing indicators are
  not official MEP grades.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-031](../adr/ADR-031-tutor-access-in-production.md)
- Regression guards: `docs/rca/regression-guards.yaml` (RCA-001 to RCA-005)
