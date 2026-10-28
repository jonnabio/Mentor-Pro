# T038 Result: Tutor Re-evaluation of Revisions (ADR-032)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T038-tutor-reevaluation` (from `dev` at `6ed9703`)
- **Status:** implemented and verified locally on `mentor_pro_test`; PR to
  `dev` open, not merged (needs PO approval); released only together with
  T037 and after T039 progress semantics; nothing deployed, migrated or
  published

## Thought

T037 integration verified first: PR #13 merged as `6ed9703`; `dev` CI
[40745285425](https://github.com/jonnabio/Mentor-Pro/actions/runs/40745285425)
green (519 passed, 102 skipped; image built, both smoke tests passed; GHCR
login and publish skipped). T038 was reserved by ADR-032 and not yet in
the tracker. The store already lists `attempt_number` in the tutor queue
and keeps completed evaluations locked; the tutor needed the previous
attempt in context, and the student needed to see the new review.

## Action

- ADR-032 T038 amendment (before code); T038 registered; T037 marked done.
- `app/writing/tutor.py`: queue `attempt_number`; detail `attempt_number`
  and `previous` (first response, L4 sections, completed evaluation with
  official descriptors and feedback). Evaluation saving unchanged.
- `app/static/tutor.html`, `tutor.js`, `styles.css`: "Mejora (versión 2)"
  badge and meta; read-only block "Primera respuesta del estudiante" and
  its locked evaluation above "Versión mejorada del estudiante".
- `app/static/index.html`, `app.js`: `renderWritingFeedback` takes an ID
  prefix; the review of the improvement appears under "Mi nueva versión"
  ("Revisión del tutor de mi mejora").
- Tests: `tests/app/test_writing_tutor_revision.py` (5);
  `scenario_revision` extended (tutor step, 4 checks per viewport);
  `scripts/dev/revision_restart_check.py` (live, real processes).

## Observation

| Check | Result |
| --- | --- |
| `test_writing_tutor_revision.py` | 5 passed |
| Browser suite (mocked, desktop + mobile) | `E2E=pass (481 checks, 0 failed)` incl. RCA-003 scenario |
| Live restart check (student app 8010 + tutor service 8011, three restarts) | `LIVE pass (10/10)` |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, test 626 passed, lint passed (log `.ace/logs/verify/20261028-123743-2102`) |

Covered: queue and detail identify the revision; previous response,
locked evaluation, descriptors and feedback shown; same rubric and pinned
exercise revision; in-progress review hidden from the student; completed
review visible through the existing feedback view; first submission,
evaluation and scores identical; a second completion of the first review
409 (also after restart); L1 reference only on the tutor side; L4 both
sets of sections; tutor service still needs the token and an allowed
address; student app serves no tutor data.

ADR-031 boundary unchanged (`tutor_main.py`, token and host checks not
modified). No new dependency. Progress untouched (T039).

## Risks

- **Release blocked on T039** (PO): progress and activity count revision
  submissions as additional work until T039.
- Production needs the T036 migration (verified backup, isolated restore
  rehearsal, approved procedure, explicit authorization).
- Only one revision per exercise (`MAX_ATTEMPTS = 2`).

## Next

PO merge approval for T038; then T040 deployment assessment (approved to
start once T038 is reviewable); T039 before any T037+T038 release.
