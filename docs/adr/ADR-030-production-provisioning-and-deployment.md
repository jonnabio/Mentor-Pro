# ADR-030: Production Curriculum Provisioning and Deployment Configuration

> **Status:** Accepted (CI/CD Stage 6.3, 2026-10-26, with runbook corrections)
> **Date:** 2026-10-26

---

## Context

The image published from `main` (`7e45376`, digest
`sha256:486dcc0a…5e20`) starts and serves `/` (RCA-005). A preview on
macedonianserver answers HTTP 500 on `/api/subjects`, `/api/dashboard` and
`/api/writing/levels`; the only logged error is
`ConfigurationError: DATABASE_URL is not set`.

State of the server on 2026-10-26 (read-only inspection, secrets redacted):

- `/opt/mentor-pro/compose.deploy.yml` (project `mentor-pro`) defines
  `app` (`ghcr.io/jonnabio/mentor-pro:testing`, `127.0.0.1:8080:8000`,
  `env_file: /etc/mentor-pro/app.env`) and `postgres` (`postgres:17.6`,
  volume `postgres_data`, health check).
- `DATABASE_URL` and `POSTGRES_PASSWORD` are written inline in that file.
- `mentor-pro-postgres-1` is running; `app` is not. Uptime Kuma runs in a
  separate project (`127.0.0.1:3001`).

What the code needs (verified in the repository):

- The curriculum comes only from the PNE Tracker workbook through
  `python -m curriculum.importer` (ADR-007). The importer refuses a workbook
  whose SHA-256 is not in `references/MANIFEST.sha256` (shipped in the
  image), aborts on any problem without writing, returns `unchanged` for
  the same version and checksum, and refuses a different checksum for an
  existing version. The registered workbook is
  `cce57db40afacdb2f6d2492c39ba9df6c1bc398941c1c7fb9cff8ec28bcc19d3`.
- The workbook is excluded from Git and from the image. Its `Logrado ✓`
  column holds student progress; the importer never stores it, but the file
  is student data.
- The schemas `curriculum`, `practice`, `generation`, `llm` and `writing`
  are created idempotently (`CREATE … IF NOT EXISTS`, advisory lock) on the
  first writable connection; there are no destructive migrations.
- Docker Compose reads `env_file` on the client, as the user running the
  command; `${VAR}` interpolation would place values in the rendered
  configuration.

---

## Decision

### 1. Curriculum source and integrity

- The workbook is copied from Windows to the server with `scp` over the
  Tailscale address into `/opt/mentor-pro/baseline/` (directory `0700`,
  file `0600`, owner `jonnabio`).
- Before the import, `sha256sum` on the server must equal the manifest
  entry above. A mismatch stops the deployment; nothing is imported.
- The importer repeats the check against the manifest inside the image
  (second, independent verification).

### 2. Import mechanism (one-time administrative operation)

- The importer never runs on application start. It runs once, by hand,
  through the same pinned image (`docker compose run --rm --no-deps` of the
  `app` service, running `python -m curriculum.importer --workbook … --version
  PNE2026-SUM-v1.0`; exact command in the runbook, section E).
- The workbook is mounted read-only into that one-off container only.
- Running the same command again must report `"status": "unchanged"`
  (idempotency proof). A future curriculum change is a new baseline
  version, never an overwrite.

### 3. Database

- The existing `postgres` service, container and `postgres_data` volume are
  kept. No `down -v`, no volume recreation, no password change (the
  password applies only when a volume is first initialized).
- Before the first import and before every application deployment:
  `pg_dump -Fc` of database `mentor_pro` to
  `/var/backups/mentor-pro/` (root, `0600`).
- Schema creation stays with the application code (idempotent bootstrap);
  the runbook validates the result by listing schemas and counting
  curriculum rows.

### 4. Secrets

- Two root-owned files, mode `0600`, never committed:
  - `/etc/mentor-pro/postgres.env`: `POSTGRES_USER`, `POSTGRES_PASSWORD`,
    `POSTGRES_DB` (postgres service only);
  - `/etc/mentor-pro/app.env`: `DATABASE_URL`, `OPENROUTER_API_KEY`,
    `MENTOR_PRO_TUTOR_TOKEN` and other settings (app service only).
- `compose.deploy.yml` uses `env_file:` only, with no `${…}` interpolation
  and no secret values. The values move unchanged from the current file.
- Compose commands that read these files run with `sudo`.
- `docker compose config`, `docker inspect` and `docker exec env` print the
  values: they are not run into logs, tickets or chat. Diagnostics use the
  redaction commands of the runbook.
- Accepted limit: members of the `docker` group (root-equivalent) can read
  any container's environment. File permissions protect against other
  local users, not against Docker administrators. Only trusted
  administrator accounts stay in that group.

### 5. Image reference

- `app.image` is the immutable digest
  `ghcr.io/jonnabio/mentor-pro@sha256:<digest>`, never `:testing`.
- Each deployment appends one line to `/opt/mentor-pro/RELEASES`
  (date, digest, git commit, operator, result).

### 6. Rollback

- Set `app.image` to the previous digest from `RELEASES`, then
  `docker compose up -d app`. The database is untouched.
- This is an **application** rollback only. It is safe only when the
  earlier image is compatible with the current database, which holds while
  schema changes stay additive (current code). Database rollback is a
  separate, deliberate operation: a release that changes the schema
  destructively states its database rollback in its own ADR, and the
  `pg_dump` taken before the deployment is restored only into a new
  database after review, never over the live one.

### 7. Initial content (minimum usable release)

- Multiple choice uses on-demand generation (ADR-010 to ADR-013) with the
  existing limits in `/etc/mentor-pro/app.env`: free models only
  (`OPENROUTER_ALLOW_PAID=false`, `OPENROUTER_MAX_USD_PER_DAY=0`) and a
  daily request cap. The OpenRouter key is checked before the practice
  test. A larger pre-validated question bank is later work, not a
  prerequisite.
- Writing practice is offered only if at least one reviewed (eligible,
  ADR-027) exercise is provisioned on the server; otherwise it is shown as
  not yet available. How exercises are provisioned (generation on the
  server or export from the local database) is decided when that step is
  executed and recorded in the runbook; no further ADR.

### 8. Tutor access

- The loopback-only tutor boundary (ADR-024) is kept unchanged. Tutor
  review through the published port is therefore unavailable for now; it
  is a separate administrator-only follow-up and does not block student
  practice.

### 9. Scope and cleanup

- The `mentor-pro-preview` container is removed when the compose `app`
  service passes its checks. Ports stay on `127.0.0.1` (8080); access is
  through the SSH tunnel. Superseded for the student by section 10.
- Stage 6.4 (automated promotion, post-deployment health checks, tested
  rollback) builds on this ADR and is not part of it.

### 10. Amendment 2026-10-27: access from the home Wi-Fi

Context: the SSH tunnel ties practice to a computer where an administrator
has opened it; the student must be able to use the app from any device
on the house Wi-Fi without help.

- The app is also published on the server's Wi-Fi address only:
  `192.168.50.229:8080` (`wlo1`, DHCP reservation in the router), in
  addition to `127.0.0.1:8080`. Never `0.0.0.0`, never the wired
  `192.168.100.x` network, never a router port forward.
- Address for devices: `http://192.168.50.229:8080/` or
  `http://macedonianserver.local:8080/` (mDNS, `avahi-daemon`).
- `net.ipv4.ip_nonlocal_bind=1` (`/etc/sysctl.d/99-mentor-pro.conf`) lets
  Docker publish on the Wi-Fi address even when `wlo1` comes up after
  Docker at boot; otherwise the app would fail to start after a reboot.
- Accepted risks (Product Owner, 2026-10-27): no login; anyone on the
  house Wi-Fi can use the app and see learning progress. Only family
  devices use that network. Plain HTTP inside the house. Docker-published
  ports bypass `ufw`, so the binding to one address is the control.
- Unchanged: tutor review answers only to loopback clients (ADR-024,
  section 8); `MENTOR_PRO_DEV_ENDPOINTS=false`.
- Revisit if guests or other people join the Wi-Fi, or before any access
  from outside the house (that needs authentication and its own ADR).

---

## Acceptance Criteria

1. Server `sha256sum` of the workbook equals the manifest entry.
2. First import reports `imported` with catalog counts; no existing data
   is replaced (pre-import inventory and backup recorded).
3. A second identical import reports `unchanged`.
4. `/api/subjects`, `/api/dashboard` and `/api/writing/levels` return
   HTTP 200 through `127.0.0.1:8080`.
5. `docker inspect` of the app container shows the pinned digest; after
   `docker compose restart app` the three endpoints return 200 again.
6. Recreating the app container (`up -d --force-recreate app`) leaves the
   curriculum counts unchanged.
7. `uptime-kuma` and Samba (`smbd`) are running before and after, with
   unchanged container IDs and service status.
8. Stage 6.3 success: the student opens Mentor Pro from the student's own
   computer, selects Matemáticas, completes a five-question practice,
   sees the result, and finds the progress preserved after the app is
   restarted.

Mandatory gates: backup (`BACKUP OK`), checksum (`sha256sum -c` OK) and
secrets (`DB OK` after the move). Procedure and failure path:
`docs/runbooks/production-deployment.md`.

---

## Consequences

- Deployment is reproducible from three inputs: an image digest, the
  registered workbook and the two env files.
- Secrets leave the compose file; the file can be reviewed and versioned.
- Every compose command needs `sudo` (reads root-only env files).
- Criterion 8 needs access from the student's computer; the app is bound
  to `127.0.0.1`, so that access path (SSH tunnel or another route) is
  settled during execution without exposing the port to the network.
