# ADR-030: Production Curriculum Provisioning and Deployment Configuration

> **Status:** Proposed (CI/CD Stage 6.3; review before any server change)
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
- Compatibility: valid while the schema changes stay additive (current
  code). A release that changes the schema destructively must state its
  rollback path in its own ADR; the `pg_dump` taken before the deployment
  is the fallback.

### 7. Scope and cleanup

- The `mentor-pro-preview` container is removed when the compose `app`
  service passes its checks. Ports stay on `127.0.0.1` (8080); access is
  through the SSH tunnel.
- Stage 6.4 (automated promotion, post-deployment health checks, tested
  rollback) builds on this ADR and is not part of it.

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

Procedure and failure path: `docs/runbooks/production-deployment.md`.

---

## Consequences

- Deployment is reproducible from three inputs: an image digest, the
  registered workbook and the two env files.
- Secrets leave the compose file; the file can be reviewed and versioned.
- Every compose command needs `sudo` (reads root-only env files).

### Open items found while drafting (not solved by this ADR)

- **Empty content banks.** The production database has no validated
  questions and no writing exercises. Multiple choice can generate on
  demand (needs `OPENROUTER_API_KEY` and budget); the writing levels will
  list no exercises until they are generated on the server or migrated
  from the local database. This needs its own Product Owner decision.
- **Tutor review in a container.** `/tutor` accepts only loopback clients
  (ADR-024). Inside the container the client is the Docker bridge gateway,
  so tutor review will be refused through the published port. Changing
  that boundary needs its own decision.
