# ADR-033: Repeatable, Gated Deployment Workflow

> **Status:** Accepted as the architecture direction (PO, 2026-10-28),
> with the refinements below. Approval is not authorization to implement
> or deploy every increment: each increment is a separate task and PR;
> no production change is authorized.
> **Date:** 2026-10-28
> **Builds on:** ADR-030 (provisioning and deployment), ADR-031 (tutor
> service), ADR-032 (explicit writing migrations)

## Context

Assessment: `docs/planning/2026-10-28-deployment-simplification-assessment.md`.

Production runs `app`, `tutor` and `postgres` with Docker Compose on one
server. Releases are copy-pasted from a 420-line runbook. The main risks
found:

- no check before deployment or rollback that the image and the database
  schema are compatible; a rollback to a pre-T036 image on a migrated
  schema breaks writing (ADR-032);
- backups are listed, never restored, so the T036 restore rehearsal has
  no repeatable procedure;
- the production compose file is not in Git;
- digests, health checks, release records and gates are manual.

## Decision (proposed)

1. **Versioned deployment files.** `deploy/compose.yml` (production
   services as in ADR-030/031, plus health checks for `app` and `tutor`),
   `deploy/compose.rehearsal.yml` (isolated project, own volume,
   loopback ports only) and the script `deploy/mentorpro` live in Git.
   They contain no secrets.
2. **Image reference.** The digest is read from a non-secret
   `/opt/mentor-pro/release.env` (`MENTOR_PRO_IMAGE=...@sha256:...`).
   This is the only interpolated value; secrets stay in `env_file:` as
   ADR-030 section 4 requires.
3. **Release manifest.** CI on `main` attaches a manifest to a release
   tag `vYYYY.MM.DD-N`: digest, commit, CI run, `schema_version`,
   `min_rollback_schema`. The image carries the same values as OCI
   labels. Published tags are unchanged.
4. **Compatibility rule.** `deploy` and `rollback` refuse an image whose
   declared schema range does not include the live schema, before any
   container is changed. Crossing a migration backwards is a database
   restore into a new database (ADR-030 section 6), never an app
   rollback.
5. **Tested backups.** Every backup is restored into a throwaway
   PostgreSQL container on its own network and volume, and row counts
   are compared; only then is `BACKUP OK` issued.
6. **Gates enforced by the script.** G1 deploy requires `BACKUP OK`; G2
   migration requires `BACKUP OK`, `REHEARSAL OK` for the same release
   and a fresh dump, and a named PO authorization; G3 database restore
   requires PO approval; G4 acceptance stays manual.
7. **Operator-triggered only.** GitHub Actions never deploys to the
   server.
8. **Incremental delivery** I1 to I8 as in the assessment; I6 and later
   change production and each needs its own authorization.

## Consequences

- One command per step; the runbook shrinks to the commands plus an
  appendix with today's manual blocks.
- The T036 migration gets a repeatable rehearsal and an enforced gate.
- The same files reproduce the deployment on another isolated host.
- New code to maintain: one shell script and two compose files, covered
  by tests against an isolated local project.

## Product Owner decisions (2026-10-28)

1. ADR-033 approved as the direction.
2. The non-secret `release.env` interpolation exception to ADR-030
   section 4 is approved; secrets stay in protected files outside Git.
3. Release tags `vYYYY.MM.DD-N` and immutable release manifests approved.
4. Rehearsal with a copy of a production backup approved in principle,
   only with the access, isolation, cleanup and data-protection controls
   of refinements R4 to R6 implemented and verified.
5. Only the existing primary administrator operates deployments and
   rollbacks; no second operator.
6. Retention: last ten routine backups and all pre-migration backups, no
   automated deletion; storage monitored; later retention review.
7. Next: I1 only (task T041), on a feature branch, tested in an isolated
   local environment, submitted for review before merge.

## Refinements required before implementation

- **R1 Idempotency.** Every command can be rerun safely. `status` and
  `smoke` are read-only. `deploy` of the release already running and
  healthy reports `unchanged` and changes nothing. `backup` always
  creates a new, uniquely named file and never overwrites one.
  `migrate` on a current schema reports `current`. `rollback` with no
  compatible earlier release refuses and changes nothing.
- **R2 Supported-schema ranges.** Each image declares
  `schema_min` and `schema_max` (the writing migrations it can run on)
  in its OCI labels and the release manifest. Images without labels are
  treated as `schema_min = schema_max = none` (pre-T036). `deploy` and
  `rollback` require `schema_min <= live schema <= schema_max` before
  any container changes; the live schema comes from the database, not
  from a file.
- **R3 Publication is not authorization.** A release tag and manifest
  mean only that the image passed CI. Deploying it needs the operator to
  run `deploy` inside a window the PO approved; a migration needs a
  named PO authorization recorded with the release (refinement R7).
- **R4 Backup copies.** A production dump used for a rehearsal is
  copied only on the server, root-owned `0600`, into a dedicated
  `0700` rehearsal directory; it is never copied off the server, into
  Git, CI, logs or chat. Output is counts and digests only.
- **R5 No live connectivity from rehearsal.** Rehearsal containers run
  in a separate compose project on an `internal: true` network with
  their own PostgreSQL and volume; they receive no production env file,
  publish loopback ports only, and the script checks before starting
  that no production network or volume is attached.
- **R6 Verified cleanup.** After a rehearsal (pass or fail) the script
  removes the rehearsal containers, network, volume and dump copy, then
  lists them and fails if any remain. Production resources are never
  named in a removal command; `down -v` is never used on the production
  project.
- **R7 Operator and authorization are separate controls.** `RELEASES`
  records the operator (the account running the script) and, for a
  migration or database restore, the PO authorization reference passed
  with `--authorized-by` and `--authorization` (date and decision
  record). The script cannot supply the authorization itself.
- **R8 Storage and retention.** `status` and `backup` report backup
  count, total size and free space on the backup filesystem and warn
  below a threshold; nothing is deleted automatically. A manual
  retention review is scheduled after the first migration release.

## Not decided here

The storage warning threshold and the date of the retention review.
