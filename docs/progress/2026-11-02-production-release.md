# Production Release v2026.11.02-1 (T047 + T048 + T049)

- **Date:** 2026-11-02
- **Role:** Architect
- **Authorization:** `PO-T047-T049-2026-11-02`, window
  `T047-T049-2026-11-02` (`authorization_verified=no`; a reference string
  does not prove the approval).
- **Operators:** the agent (`jonnabio`, `sudo -n` tool only); the
  administrator ran the switch check interactively.
- **Result:** `v2026.11.02-1` running in production, schema `current
  0001`, `STATUS HEALTHY`, bank-only practice **off**. PO browser
  acceptance (T050) **passed** 2026-11-02; release cycle T047–T050 closed.

## Release identity

| Item | Value |
| --- | --- |
| Source | `dev` `69e2c39` (T047 #42, T048 #43, T049 #44) plus handoff record `ae3e09b` (docs only) |
| Release PR | #45, head `ae3e09b`, CI 41517124354 green, merged with `--match-head-commit` |
| `main` commit | `166acdc`, CI 41518476299 green (Tag and Release included) |
| Tag | `v2026.11.02-1` (protected) → `166acdc` |
| Image | `ghcr.io/jonnabio/mentor-pro@sha256:738af74e68b212a74edba81ebc1785a1a77d2e092f9678bb9587b45fbc78547a` |
| Manifest | sha256 `459ce7b3f270f4897653a5b3db764250ea1d69fe39666e86fbbb1677bf67e35b`, same on GitHub and `/opt/mentor-pro/manifests/v2026.11.02-1.json`; schema `0001..0001` |

## Switch check (before deploy)

- Running containers (from `/etc/mentor-pro/app.env` at the 2026-10-31
  deploy): no `MENTOR_PRO_BANK_ONLY*` key (key names only).
- Administrator: `sudo grep -c '^MENTOR_PRO_BANK_ONLY_ENABLED='
  /etc/mentor-pro/app.env` returned `0`.

## Window (UTC)

| Step | Result |
| --- | --- |
| `status`, `smoke` | `STATUS HEALTHY` (`v2026.10.31-1`), `SMOKE PASS (9/9)` |
| `backup` | `BACKUP OK` `mentor_pro_2026-11-02_205333.dump`, 27 tables, 909 rows, 201,244 bytes, sha256 `ad991fc0…00ff` |
| `verify-backup` | `VERIFY OK`; verify container, volume and network removed |
| `preflight` | `PREFLIGHT OK: DEPLOY COMPATIBLE`, schema `0001` |
| `deploy` | 20:54:12 `DEPLOY OK: v2026.11.02-1 running and healthy, smoke passed`; previous `e7dd6edb…3215` |
| After | `SMOKE PASS (9/9)`, `STATUS HEALTHY` |

## Checks after deploy (non-destructive)

- `/api/subjects`: `practice: {bank_only: false, question_counts: [5]}`.
- `POST /api/practice/sessions` with 10 questions: 422
  `invalid_question_count`; with `source: bank_only`: 422
  `bank_only_disabled`. Both refused before any write.
- `/`, `/api/writing/levels`, `/api/writing/progress`: 200. Tutor
  `127.0.0.1:8081/tutor`: 200, "Volver a Mentor Pro" present.
- Not done: a real 5-question practice (it would generate questions, not
  authorized); no seeding, no writing submission.

## PO browser acceptance (T050, switch off)

Reported by the PO on 2026-11-02, after a production recheck
(`STATUS HEALTHY`, smoke 9/9, `bank_only: false`, sizes `[5]`). Results as
reported; none inferred from tests.

| Check | Result |
| --- | --- |
| Practice form: only size 5 and the note "Por ahora las prácticas tienen 5 preguntas." | PASS |
| Five-question practice generated, answered to the summary, "Mi progreso" updated | PASS |
| Navigation: "Salir de la práctica", "Volver al menú principal" | PASS |
| Writing workflow: exercise and earlier feedback visible | PASS |
| Tutor page through the 8081 tunnel, "Volver a Mentor Pro" | PASS |
| Failures | None |

The practice check was option (a) of the pending decision: the student
completed a real five-question practice while the PO watched (ADR-017). It
is genuine use and is kept as such, not a synthetic test. T047, T048 and
T049 are now `verified`.

## Rollback (kept)

- Rollback target: `v2026.10.31-1` (`e7dd6edb…3215`) with the dump above.
