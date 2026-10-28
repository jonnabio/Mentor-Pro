# ADR-033: Repeatable, Gated Deployment Workflow

> **Status:** Proposed (T040, 2026-10-28), awaiting Product Owner review.
> Nothing is implemented; no production change is authorized.
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

## Not decided here

Backup retention, the release tag format, whether the rehearsal may use
a copy of a production dump on the server, and a second operator
(assessment section 8).
