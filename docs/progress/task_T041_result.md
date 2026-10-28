# T041 Result: Versioned Deployment Compose, Read-only Status and Smoke

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T041-deploy-compose-status` (from `dev` at `e368c9c`)
- **Status:** implemented and verified locally; PR to `dev` for PO review,
  not merged. Not adopted on the server (increment I6 needs authorization).

## Thought

PR #15 (T040, documentation only, head `26a32ea` unchanged) merged as
`e368c9c`; `dev` CI 40770016065 green (524 passed, 102 skipped). PO
approved ADR-033 with refinements and I1 only. ADR-033 now records the
seven PO decisions and refinements R1 to R8 before any code. T039 is
reserved by ADR-032, so I1 is T041.

## Action

- `deploy/compose.yml`: the production `app`, `tutor` and `postgres`
  services exactly as runbook sections C and J, plus health checks
  (`app`: `GET /` with Python; `tutor`: any HTTP answer from `/tutor`,
  since its own loopback gets 403). The image is the only interpolated
  value (`MENTOR_PRO_IMAGE` from `release.env`); secrets via `env_file`.
- `deploy/mentorpro` (POSIX sh, curl, docker inspect/exec only):
  - `status`: release.env image line, container image/state/health,
    writing `migrate status` (or "not reported by this image"), student
    and tutor HTTP codes, last three `RELEASES` lines, backup count, size
    and free space (R8);
  - `smoke`: four student endpoints 200, student `/api/tutor/queue` 404,
    tutor `/tutor` 200, tutor API 403 without the token, Wi-Fi student
    200 and Wi-Fi tutor refused; exit 1 on any failure.
- `tests/app/test_deploy.py` (6 tests): compose has no secrets and
  interpolates only the image; bindings match ADR-030/031; tutor
  health-check code compiles; smoke and status run against real student
  and tutor processes on `mentor_pro_test`.

## Observation

| Check | Result |
| --- | --- |
| `tests/app/test_deploy.py` | 6 passed |
| Smoke on healthy services; rerun | `SMOKE PASS (7/7)`, identical output |
| Smoke with the tutor stopped | exit 1, `SMOKE FAIL (2 of 7 failed)` |
| Status | exit 0, no token or database URL, test files unchanged |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 632 passed (log `.ace/logs/verify/20261028-151756-2700`) |

Limits: Docker is not installed on this workstation, so the compose file
is checked as text and the Docker parts of `status` (containers, schema)
were not exercised; the Wi-Fi checks were skipped locally. The production
compose file on the server was not read; equivalence is to the runbook
copy and must be confirmed (read-only `diff`) at I6.

No server, volume, secret, workflow, image or container change.

## Next

PO review of PR; I2 (restore-checked backup) only after a separate task
and approval; T039 before the T037+T038 release.
