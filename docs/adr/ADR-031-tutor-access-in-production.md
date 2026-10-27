# ADR-031: Tutor Review Access in Production

> **Status:** Accepted with security amendments (Product Owner,
> 2026-10-27); implemented in T033. Changes the ADR-024 tutor boundary as
> deployed by ADR-030.
> **Date:** 2026-10-27

---

## Context

ADR-024 serves tutor review (`/tutor`, `/api/tutor/*`) only when
`MENTOR_PRO_TUTOR_TOKEN` is set, and only to requests whose client address
is loopback and that carry the token. ADR-030 kept that boundary.

Verified on macedonianserver on 2026-10-27 (read-only):

- `GET /tutor` and `GET /api/tutor/queue` answer 404: no tutor token is
  configured in production, so the tutor router does not exist.
- The app logs every request, from `127.0.0.1:8080` and from the Wi-Fi
  address `192.168.50.229:8080`, as coming from `172.19.0.1`, the gateway
  of the compose bridge network. Docker's userland proxy (`docker-proxy`,
  3 processes running) relays published ports and replaces the client
  address.

Root cause: inside the container no request is ever loopback, so setting
the token alone still rejects every tutor request (403). Trusting
`172.19.0.1` in the same app is not acceptable: the student's Wi-Fi
requests arrive from the same address, so the tutor API would be reachable
from the house Wi-Fi with only the token in between. `X-Forwarded-For` is
forgeable without a trusted proxy and is not used.

## Decision

Separate the tutor by port and container, not by client address in the
student app:

1. **Student app unchanged.** The `app` service keeps no tutor token, so
   `/tutor` and `/api/tutor/*` do not exist on `127.0.0.1:8080` or
   `192.168.50.229:8080`.
2. **A `tutor` service** in `compose.deploy.yml`: the same image digest as
   `app`, the same database, its own env file
   `/etc/mentor-pro/tutor.env` (root, `0600`) holding
   `MENTOR_PRO_TUTOR_TOKEN` (at least 32 random characters) and
   `MENTOR_PRO_TUTOR_ALLOWED_HOSTS`. It is published on
   `127.0.0.1:8081:8000` only, never on the Wi-Fi or wired address.
3. **`MENTOR_PRO_TUTOR_ALLOWED_HOSTS`**: new optional setting, a
   comma-separated list of exact client IP addresses (no ranges, no
   names). Empty or absent keeps the ADR-024 loopback set. In the `tutor`
   service it names the bridge gateway (`172.19.0.1`, read from
   `docker network inspect mentor-pro_default` at deployment). The token
   check is unchanged and always required.
4. **Tutor use:** the parent opens an SSH tunnel from their own computer,
   `ssh -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`, then
   `http://127.0.0.1:8081/tutor`, and enters the token. Only someone with
   SSH access to the server (already an administrator) can reach the port.
5. The tutor service is started for a review session and may be stopped
   afterwards (`docker compose stop tutor`); student work is in PostgreSQL
   and is not affected.

## Alternatives Considered

| Option | Rejected because |
| --- | --- |
| Trust `172.19.0.1` in the `app` service | Wi-Fi students share that address |
| Trust `X-Forwarded-For` | Forgeable; no trusted proxy |
| Disable the userland proxy (`userland-proxy: false`) | Daemon-wide change; affects Uptime Kuma and other containers; hairpin traffic is still masqueraded |
| `network_mode: host` | Exposes every port; breaks the address binding ADR-030 relies on |
| Tutor review by `docker exec` and `curl` | No browser screen; not usable by a parent |
| Login for the student app | Larger change; not needed for one family |

## Security Properties

- The student ports never route to tutor endpoints (no token in `app`).
- The tutor port is bound to host loopback only. Docker-published ports
  bypass `ufw`, so the binding is the control, as in ADR-030 section 10.
- Defence in depth: the client address must be the bridge gateway (a
  request routed from the LAN to the container address keeps its LAN
  source and is refused), and the token is compared in constant time.
- The token is never in Git, compose files, logs or reports; the browser
  keeps it only in the tutor page's memory (ADR-024).

## Amendments (Product Owner, 2026-10-27) and Implementation

- **Dedicated entrypoint** `app.tutor_main` (`python -m app.tutor_main`):
  only `/tutor`, `/static` and `/api/tutor/*`; no student, practice,
  development or OpenAPI routes. The page `/tutor` also requires an
  allowed client address.
- **The student app never reads `MENTOR_PRO_TUTOR_ALLOWED_HOSTS`**: it keeps
  the fixed ADR-024 loopback set, so the setting cannot widen it even if
  it leaks into `app.env`.
- **Fails closed at startup** (`TutorConfigurationError`): token shorter
  than 32 characters; allowed hosts empty, a range, a name, a wildcard, an
  unspecified, multicast or broadcast address, or any malformed entry. A
  valid but wrong gateway answers 403 to everything.
- **Forwarded headers disabled** in the tutor server
  (`proxy_headers=False`). uvicorn otherwise trusts `X-Forwarded-For`
  from `127.0.0.1`; a real-socket test proves a forged header is ignored
  and fails when proxy headers are enabled (negative control run).
- **Isolation is tested at the application layer, not inferred from the
  port binding** (`tests/app/test_tutor_service.py`): LAN addresses
  (`192.168.50.x`, `192.168.100.x`), other containers (`172.19.0.2`,
  `172.19.0.3`, `172.17.0.1`), loopback inside the container and Tailscale
  addresses are refused on every tutor route even with the token; absent,
  truncated, extended or wrongly placed tokens are refused from the
  gateway; spoofed `X-Forwarded-For`, `X-Real-IP` and `Forwarded` are
  refused.
- Residual risk: a process on the server, or a container with host
  networking, reaches `127.0.0.1:8081` as the gateway and still needs the
  token. None uses host networking on 2026-10-27 (checked); the runbook
  pre-check stops if one appears. Server shell access is administrator
  access already.

## Acceptance Criteria

1. Without a token, `/api/tutor/queue` answers 404 on
   `192.168.50.229:8080` and `127.0.0.1:8080`.
2. Through the tunnel, `/api/tutor/queue` answers 403 without the token
   and 200 with it.
3. From another Wi-Fi device, `192.168.50.229:8081` is refused.
4. A tutor completes an evaluation; the student sees the feedback on the
   Wi-Fi address, and after `docker restart mentor-pro-app-1`.
5. Tests: allowed hosts parsed from the setting, default loopback, LAN and
   forwarded-header requests refused.

## Consequences

- One more container and env file on the server; the runbook gains a tutor
  section; Stage 6.4 promotion updates both services to the same digest.
- The gateway address must be checked if the compose network is ever
  recreated; a wrong address fails closed (403).
- Tutor review needs SSH access from the parent's computer.
