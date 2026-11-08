# T057 Result: Matemáticas-Only Bank-Only Activation

- **Role:** Developer (fast track, PO 2026-11-07)
- **Status:** in progress (code ready; production activation waits for
  the M09 tutor verdict and a passing `compose-check`)

## Why

`MENTOR_PRO_BANK_ONLY_ENABLED` is global: every subject would become
bank-only (Español, Ciencias and Estudios Sociales have no bank and would
refuse every practice) and sizes 5-30 would be offered (T056 finding).

## Change

- `app/main.py`: `bank_only_config()` builds subject -> sizes from
  `MENTOR_PRO_BANK_ONLY_SUBJECTS` (`matematicas` means size 5). Default
  off; the T049 switch keeps its meaning when the list is absent; an
  invalid entry refuses to start. `/api/subjects` adds each subject's
  `practice`; the top-level `practice` is on only for the global switch.
- `app/practice/routes.py`: `source: bank_only` is refused (422
  `bank_only_disabled`) for a subject without the switch and (422
  `invalid_question_count`) for a size the subject does not offer.
- `app/static/app.js` (RCA-003 guarded): the size choices and the
  bank-only source follow the chosen subject. Menu handlers are
  unchanged; a hidden size falls back to 5.
- ADR-035 amendment T057.

## Tests

`tests/app/test_bank_only_practice.py`, 13 new cases: default off and
exact parsing (5), invalid configuration refuses to start (5), per-subject
switch and sizes in `/api/subjects`, Matemáticas size 5 composed from the
bank with no generation and sizes 10/30 refused with nothing created,
Español refuses bank-only and keeps the generated flow.

## Verification

- `tests/app`: 829 passed, 9 skipped.
- RCA-003: browser E2E (`scripts/dev/practice_e2e.py`, mock mode)
  `E2E=pass` (485 checks, 0 failed), including `[dashboard-early] opens
  before subjects load` and `[bank]`.
- Full gate tests (ace, curriculum, app): 1019 passed, 9 skipped.
- ACE gate: `VERIFY_RESULT=pass gate=all` (test 256 s, lint 1.7 s; log
  20261107-210342-841).

## Release

- PR #58 (CI 42441437450) merged into `dev` as `cd8d86a` (CI
  42444317937, green). Authorization `PO-T057-FASTTRACK-2026-11-07`.
- Release PR #60 merged into `main` as `5cae693` (CI 42445890606: tests,
  release identity, image, Tag and Release green). Tag `v2026.11.08-2`,
  digest `sha256:1f8b8d3a...5c66`, manifest sha256 `95e5becb...e9ed`
  (identical on the server).

## Deployment (2026-11-07 local, 2026-11-08 UTC)

- Before: `STATUS HEALTHY`. Preflight `DEPLOY COMPATIBLE`. Backup
  `mentor_pro_2026-11-08_042316.dump` (33 tables, 1045 rows, sha256
  `9cf262ad...c5a`) `VERIFY OK`.
- Window `T057-2026-11-07`: `DEPLOY OK`, smoke 9/9, `STATUS HEALTHY`,
  schema `current:0001`, L001 `current`.
- Switches: `MENTOR_PRO_BANK_ONLY_SUBJECTS` and
  `MENTOR_PRO_BANK_ONLY_ENABLED` absent; every subject `bank_only: false`,
  sizes `[5]`.
- `compose-check`: 16 eligible; mixed missing M09, largest size 0.
  Activation waits for the tutor verdict on `req-f2a9df9a48964c49`.

## M09 Tutor Verdict (2026-11-08)

- The tutor reviewed `req-f2a9df9a48964c49` (cell 41) and approved it as
  medium (first rated it hard; confirmed medium is fair). Recorded once
  with `item-review-record --reviewer tutor`: recorded 1, approved 1.
- `compose-check`: 17 eligible; M09 `medium: 1`; mixed size 5
  `missing_objectives: []`, `largest_size: 5`. Educational gate passed.
