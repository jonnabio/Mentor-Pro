# T040: Deployment Simplification and Repeatability Assessment

- **Date:** 2026-10-28
- **Role:** Architect
- **Status:** PROPOSED, for Product Owner review; nothing implemented
- **Decision record:** [ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md)
  (Proposed)
- **Scope:** assessment and design only. No server, database, image,
  workflow or configuration was changed, and nothing was deployed.

Sources reviewed: ADR-030, ADR-031, ADR-032, the runbook
`docs/runbooks/production-deployment.md` (sections A to K),
`.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml` (local),
`app/writing/migrate.py`, the start-up schema check in `app/main.py` and
`app/writing/store.py`, and the `scripts/dev` checks.

---

## 1. Current-state workflow and inventory

### 1.1 Inventory

| Item | Where | Versioned in Git |
| --- | --- | --- |
| Image build, tests, smoke tests (`/`, tutor entrypoint) | `ci.yml` | yes |
| GHCR publication (`:testing`, `:sha-<commit>`) | `ci.yml`, push to `main` only | yes |
| Production compose file (`app`, `tutor`, `postgres`) | `/opt/mentor-pro/compose.deploy.yml` on the server | **no** (copy in runbook C and J) |
| Secrets (`app.env`, `postgres.env`, `tutor.env`) | `/etc/mentor-pro/`, root `0600` | no (correct) |
| Release log | `/opt/mentor-pro/RELEASES`, hand-written line | no |
| Backups | `/var/backups/mentor-pro/*.dump`, root `0600` | no (correct) |
| Schema migration | `python -m app.writing.migrate status, apply, rollback, repair` | yes |
| Schema guard | app and tutor refuse to start on an unmigrated schema (T036) | yes |
| Curriculum import, exercise bank | one-off `compose run` commands (runbook E, H) | yes (commands) |
| Local database | `docker-compose.yml` (PostgreSQL only) | yes |

### 1.2 How a release reaches production today

1. Merge `dev` into `main`; CI tests, builds, smoke-tests and publishes.
2. The operator looks up the digest by hand in GHCR or the CI log.
3. On the server, over SSH, the operator pastes shell variables, then
   copy-pastes runbook blocks: A pre-flight, B backup, (K migration),
   `sed` of the digest into `compose.deploy.yml`, F start and verify,
   J tutor checks, and appends a line to `RELEASES`.
4. Rollback (G) is a `sed` back to an earlier digest from `RELEASES`.

The runbook has about 420 lines; a routine release uses about 40 shell
lines across six sections, each pasted by hand with `sudo`.

---

## 2. Complexity and risk assessment

Severity: H = can lose or corrupt student data or break the service;
M = slows recovery or allows drift; L = friction.

| # | Finding | Sev. |
| --- | --- | --- |
| R1 | **Incompatible versions are not prevented before deployment.** The T036 guard stops a new image on an old schema at start-up, which is safe but is an outage. Nothing stops a **rollback** to a pre-T036 image on a migrated schema: it recreates `uq_submission_exercise` and breaks drafts and submissions (ADR-032) until `repair` is run. | H |
| R2 | **The backup is checked, not restored.** `pg_restore --list` proves the archive is readable, not that it restores into a working database. The T036 condition (restore rehearsal) has no repeatable procedure. | H |
| R3 | **The production compose file is not in Git.** It exists only on the server and as copies in the runbook; drift is invisible and there is no review of changes to it. | M |
| R4 | **Manual digest handling.** The digest is copied by hand from GHCR into a `sed` command; a typo or a wrong digest is caught only when the container starts. There is no link from digest to commit, CI run and schema version except the hand-written `RELEASES` line. | M |
| R5 | **Health checks are manual and incomplete.** CI proves start-up without a database. In production, `curl` loops are read by eye; the tutor checks are separate; there is no compose `healthcheck` on `app` or `tutor`, so `depends_on` and `docker ps` cannot report them. | M |
| R6 | **Rollback is not rehearsed** and does not check schema compatibility (see R1). | M |
| R7 | **Many copy-paste steps with `sudo`**: each is a chance to skip a gate (for example deploying without `BACKUP OK`). The gates are prose, not enforced. | M |
| R8 | **No isolated environment can reproduce production**; the restore rehearsal, migration rehearsal and a new-server setup all lack a repeatable target. | M |
| R9 | **CI does not run on pull requests to `dev`**; feature PRs are verified locally only until merge. | L |
| R10 | **Image metadata is missing.** No OCI labels (revision, version, schema), so `docker inspect` cannot answer "what is running". | L |

Kept as they are (already sound): one image for app and tutor; digest
pinning; secrets in root `0600` env files without interpolation; the
tutor boundary (loopback, token, exact allowed hosts); explicit
migrations that are never run on start; refusal to start on an unmigrated
schema; `postgres_data` is never recreated.

---

## 3. Proposed simplified architecture

The principle: **the same versioned files and one script do every step,
in production and in an isolated rehearsal, and the script enforces the
gates.** No new platform, orchestrator or service: Docker Compose,
PostgreSQL 17.6, GHCR and GitHub Actions only.

```text
GitHub Actions (main)                       Server (operator, over SSH)
---------------------                       ---------------------------
tests -> build once -> smoke                deploy/mentorpro <command>
      -> publish :sha-<commit>                 reads deploy/compose.yml (Git)
      -> release manifest (JSON)               reads /etc/mentor-pro/*.env
         digest, commit, run,                  writes /opt/mentor-pro/release.env
         schema_version, min_rollback          appends RELEASES (automatic)
```

Components:

1. **Versioned deployment files** in `deploy/`: `compose.yml`
   (`app`, `tutor`, `postgres`, same content as today, plus health
   checks), `compose.rehearsal.yml` (an override with another project
   name, other loopback ports, its own volume, no Wi-Fi binding) and the
   script `mentorpro`. The server keeps a Git checkout at a release tag or
   copies these files; the files hold no secrets.
2. **Image reference outside the compose file.** `release.env` on the
   server holds one non-secret line,
   `MENTOR_PRO_IMAGE=ghcr.io/jonnabio/mentor-pro@sha256:<digest>`, read
   with `--env-file`. ADR-030 forbids interpolation for **secrets**; a
   digest is not a secret, so this is a narrow, explicit exception.
   Secrets stay in `env_file:` exactly as now.
3. **Release manifest** produced by CI on `main` and attached to a GitHub
   release `vYYYY.MM.DD-N`: digest, commit, CI run, `schema_version`
   (latest writing migration in the image, today `0001`) and
   `min_rollback_schema` (the oldest schema an image can run on).
4. **Image labels**: `org.opencontainers.image.revision`,
   `org.opencontainers.image.version`, `mentorpro.schema_version`.
5. **Health checks** in `compose.yml` for `app` (`GET /`) and `tutor`
   (`GET /tutor`), using Python in the image (no `curl` added).

---

## 4. Recommended command interface

One script, `deploy/mentorpro`, POSIX shell, run as the operator with
`sudo` only where today's runbook already uses it. Every command prints
counts, digests and `PASS`/`FAIL`, never secrets, and exits non-zero on
failure. Read-only commands need no approval.

| Command | Does | Writes | Gate |
| --- | --- | --- | --- |
| `status` | running digest, release tag, schema `migrate status`, health of each service, last `RELEASES` lines | nothing | none |
| `preflight <release>` | fetches the manifest, pulls the image by digest, checks the label matches, compares `schema_version` with the database, prints the plan (`no migration` or `migration 0001 required`) | image cache | none |
| `backup` | `pg_dump -Fc`, `0600`, non-empty, `pg_restore --list`, then **restore check** (below) | `/var/backups/mentor-pro` | produces `BACKUP OK <file> <sha256>` |
| `rehearse <release> [dump]` | restores the dump into the isolated rehearsal project, runs `migrate apply --dry-run`, `apply`, starts app and tutor on rehearsal ports, runs `smoke`, tears the rehearsal down (its own volume only) | rehearsal project only | produces `REHEARSAL OK` |
| `migrate <release>` | refuses without a `BACKUP OK` and `REHEARSAL OK` for this release and dump from the last 24 h, and without `--authorized-by <name>`; stops `app` and `tutor`, dry run, apply, `status` = current | production schema | **G2 (PO authorization)** |
| `deploy <release>` | refuses without `BACKUP OK` from this session and a matching schema; writes `release.env`, `up -d app tutor`, waits for health, runs `smoke`, appends `RELEASES` | `release.env`, containers | G1 |
| `smoke [--rehearsal]` | student endpoints 200; tutor `/tutor` 200, API 403 without the token, student service 404 on tutor routes; tutor not published on the Wi-Fi address; curriculum counts unchanged | nothing | none |
| `rollback` | previous `RELEASES` entry whose `min_rollback_schema` accepts the current schema; refuses otherwise and prints the database-restore procedure | `release.env`, containers | G3 (operator) |

The restore check in `backup` runs `pg_restore` into a temporary
database in a **separate throwaway PostgreSQL container** on its own
network and volume (never the live server or volume), then compares
table row counts with the source and removes that container. That makes
every backup a tested backup.

---

## 5. Backup, migration and rollback design

### 5.1 Backup

- Before every deployment and every migration, enforced by the script.
- Verified by restore, not by listing (R2); the restored row counts are
  recorded next to the dump (`<dump>.verify`, counts only).
- Retention: keep the last ten and every pre-migration dump; never
  delete automatically in the first increment.

### 5.2 Migration

- Unchanged mechanism: explicit `app.writing.migrate` with the new image,
  never on start-up (ADR-032).
- New: the script derives whether a migration is needed from the
  manifest and `migrate status`, and refuses `migrate` without a
  same-release rehearsal on a fresh dump and a named PO authorization.
- Students are stopped only for the migration (minutes); the tutor
  service is stopped with them.

### 5.3 Compatibility (R1, R6)

Each image declares `schema_version` and `min_rollback_schema`:

| Image | runs on schema | refuses |
| --- | --- | --- |
| pre-T036 (current production) | none | `0001` (by the script; the image itself cannot check) |
| T036 and later | `0001` | none (refuses to start; guard already exists) |

`deploy` and `rollback` compare the target image's declaration with the
live schema **before** touching a container. A rollback across a
migration becomes a database restore, which stays a separate, approved
operation: restore the pre-migration dump into a **new** database,
review, then switch `DATABASE_URL` (ADR-030 section 6). Revision attempts
made after the migration are exported first (ADR-032).

### 5.4 Application rollback (same schema)

`mentorpro rollback`: restores the previous compatible `release.env`,
`up -d app tutor`, waits for health, runs `smoke`, records the result.
About one minute; no database change.

---

## 6. Operational approval gates

| Gate | When | Who approves | Evidence the script requires |
| --- | --- | --- | --- |
| G0 Release candidate | merge to `main` | PO (as today) | CI green, manifest published |
| G1 Deploy | each deployment | operator, inside an approved window | `preflight` plan, `BACKUP OK` (restore-checked) |
| G2 Migration | only when the plan says so | **PO, explicit and named** | G1 plus `REHEARSAL OK` for the same release and a fresh dump |
| G3 Rollback | smoke failure or incident | operator for same-schema; **PO** for a database restore | `smoke` failure or incident note |
| G4 Acceptance | after deployment | PO with real users | T032/T033-style evidence; never automatic |

Production deployment is never triggered from GitHub Actions. A
push-based deployment would need a server credential in GitHub and a
runner that reaches the Tailscale network, which widens the attack
surface for a single-server family deployment. The operator runs one
command per gate instead.

---

## 7. Incremental implementation plan

Each increment is a separate task with its own PR to `dev`, ACE gate and
PO approval. None changes the server until **I6**, which is itself a
production change needing authorization.

| Inc. | Content | Touches production | Test |
| --- | --- | --- | --- |
| I1 | `deploy/compose.yml` and `compose.rehearsal.yml` in Git (same services as the runbook, plus health checks); `mentorpro status` and `smoke` (read-only) | no | runs against a local isolated compose project |
| I2 | `backup` with restore check into a throwaway container | no | local isolated project with test data only |
| I3 | CI: OCI labels, release manifest, GitHub release on `main` (no change to the published tags); CI on pull requests to `dev` (R9) | no (GHCR only on approved `main` merges) | CI on a branch; manifest schema test |
| I4 | `preflight`, compatibility rule, `deploy`, `rollback` and automatic `RELEASES` | no | full cycle on the rehearsal project, including a refused rollback across `0001` |
| I5 | `rehearse` and `migrate` gates; T036 rehearsal on a **copy of a production dump** inside the isolated rehearsal project | no (reads a dump) | `REHEARSAL OK`; this is the T036 release precondition |
| I6 | Adopt on the server: check out `deploy/`, create `release.env` for the running digest, `status` and `smoke` only | **yes**, read-mostly | PO authorization |
| I7 | First release with the script: T037 + T038 + T039 together, migration 0001 under G2 | **yes** | PO authorization |
| I8 | Rewrite the runbook around the commands (sections B, F, G, K shrink to one command each); keep the manual blocks as an appendix | no | doc lint |

Reproducibility on another isolated environment follows from I1, I2 and
I5: a new host needs Docker, the `deploy/` files, the three env files
and either an empty volume or a restored dump.

Suggested order relative to the product work: I1 to I5 can proceed in
parallel with T039; I6 and I7 follow T039 and its PO approval.

---

## 8. Open questions for the Product Owner

1. Approve ADR-033 (Proposed) as the direction, including the narrow
   `release.env` interpolation exception to ADR-030 section 4?
2. Approve release tags `vYYYY.MM.DD-N` and the manifest on `main`?
3. May the rehearsal use a **copy of a production dump** inside an
   isolated project on the server (I5)? The data never leaves the server
   and the rehearsal volume is removed afterwards. The alternative is a
   synthetic dataset, which cannot prove the real migration.
4. Who is the second operator, if any, allowed to run G1 and G3?
5. Retention for backups (proposal: last ten plus every pre-migration
   dump, no automatic deletion at first).
