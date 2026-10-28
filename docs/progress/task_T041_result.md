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
  (`app`: `GET /` with Python; `tutor`: healthy only on exactly HTTP 403
  from `/tutor`, which its own loopback gets; 200, 500, 503 and no
  connection fail; PO correction 1). The image is the only interpolated
  value (`MENTOR_PRO_IMAGE` from `release.env`); secrets via `env_file`.
- `deploy/mentorpro` (POSIX sh, curl, docker inspect/exec only):
  - `status`: release.env image line, container image/state/health,
    writing `migrate status`, student and tutor HTTP codes, last three
    `RELEASES` lines, backup count, size and free space (R8). Each item
    is `OK`, `PROBLEM` or `UNKNOWN`; the verdict is `STATUS HEALTHY`
    (exit 0), `STATUS UNHEALTHY` (1) or `STATUS INCOMPLETE` (3). Missing
    Docker, an unreadable schema or a container without a health check is
    `UNKNOWN`, never healthy (PO correction 2);
  - `smoke`: four student endpoints 200, student `/api/tutor/queue` 404,
    tutor `/tutor` 200, tutor API 403 without the token, Wi-Fi student
    200 and Wi-Fi tutor refused; exit 1 on any failure.
- `tests/app/test_deploy.py` (15 tests): compose has no secrets and
  interpolates only the image; bindings match ADR-030/031; the tutor
  health check run against a local server answering 403 (pass), 200,
  500, 503 and no listener (fail); smoke and status against real student
  and tutor processes on `mentor_pro_test`; status verdicts with a Docker
  test double (healthy, unhealthy tutor, drifted schema, schema not
  reported, no health check) and with Docker absent.

## Observation

| Check | Result |
| --- | --- |
| `tests/app/test_deploy.py` | 15 passed |
| Tutor health check: 403 / 200 / 500 / 503 / no listener | pass / fail / fail / fail / fail |
| Status with Docker absent | exit 3, `STATUS INCOMPLETE`, never `HEALTHY` |
| Smoke on healthy services; rerun | `SMOKE PASS (7/7)`, identical output |
| Smoke with the tutor stopped | exit 1, `SMOKE FAIL (2 of 7 failed)` |
| Status | no token or database URL printed, test files unchanged |
| `bash .ace/scripts/verify.sh` (after PO corrections) | `VERIFY_RESULT=pass gate=all`, 641 passed (log `.ace/logs/verify/20261028-163135-3118`) |
| Docker Compose CLI validation (`docker compose config`) | **not run**: no Docker, WSL or Podman on this workstation |

Limits: Docker is not installed on this workstation (WSL is not
registered; no Podman). The compose file was **not** validated with a
Docker Compose CLI; it is checked as text, and the tutor health-check
command was executed directly with Python. The Docker parts of `status`
were exercised only through a test double. The Wi-Fi checks were skipped
locally. Compose CLI validation is still owed in an isolated environment
with Docker (CI in I3, or a rehearsal host). The production
compose file on the server was not read; equivalence is to the runbook
copy and must be confirmed (read-only `diff`) at I6.

No server, volume, secret, workflow, image or container change.

## Next

PO review of PR; I2 (restore-checked backup) only after a separate task
and approval; T039 before the T037+T038 release.
