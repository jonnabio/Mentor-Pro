# T058 Result: Tutor Web Access on the House Wi-Fi

- **Role:** Developer (PO request 2026-11-07, priority high)
- **Status:** in progress (repository change ready; production rollout
  needs the administrator's tool install, then a deployment)

## Findings

- The tutor service (`app.tutor_main`, ADR-031) already requires the
  tutor token (at least 32 characters, constant-time comparison) and an
  allowed client address; it was published on `127.0.0.1:8081` only and
  reached by SSH tunnel.
- Docker's userland proxy presents every published-port client as the
  bridge gateway, so a Wi-Fi binding passes the address check for every
  house device. No application change can tell the parent's devices apart
  without new infrastructure; the token stays the barrier.
- Production runs the root-owned copies of `deploy/compose.yml` and
  `deploy/mentorpro`; the smoke test required the tutor to be unreachable
  on the Wi-Fi address. A configuration-only change would fail the smoke
  test, so this is a repository change released normally.

## Change

- `deploy/compose.yml`: tutor also published on
  `192.168.50.229:8081:8000`. Student bindings unchanged.
- `deploy/mentorpro` smoke: the Wi-Fi tutor page answers 200 and the
  Wi-Fi tutor API refuses without the token (403); 10 checks.
- Tests: binding assertion updated; the isolated rollout and rehearsal
  tests strip both Wi-Fi bindings.
- ADR-031 amendment T058 (accepted weaker property and mitigations).
- No application code, generation, review, budget, bank-only or student
  data change.

## Verification

- `tests/app/test_deploy.py`, `test_deploy_migrate.py`,
  `test_deploy_rollout.py`, `test_tutor_service.py`: 243 passed, 4
  skipped.
- Full gate tests (ace, curriculum, app): 1019 passed, 9 skipped.
- ACE gate: `VERIFY_RESULT=pass gate=all` (log 20261107-215142-1365).
- Server (read-only): `wlo1` `192.168.50.229/24` up; nothing listening on
  `192.168.50.229:8081`; wired `192.168.100.41` not bound.
