# T045 Result: Isolated Migration Rehearsal and Gated Migration (ADR-033 I5)

- **Date:** 2026-10-29
- **Role:** Developer
- **Branch:** `feature/T045-migration-rehearsal` (from `dev` at `148b918`)
- **Status:** implemented; PR #23 into `dev` for PO review, not merged.
  Synthetic data only. Nothing run on the server or against production
  data; nothing published.

## Thought

PR #22 (head `b0ec3fb`, documentation only) merged as `148b918`. The PO
approved the I5 design with decisions: no published ports, final
rehearsal in the same window on the exact migration backup, app and
tutor stopped before that backup, files under
`/var/lib/mentor-pro/rehearsal`, 60-minute downtime with a 40-minute
checkpoint, no automatic restore or rollback.

## Action

- `deploy/mentorpro_migrate.py` (python3 standard library), called by
  `deploy/mentorpro maintenance|rehearse|migrate`:
  - `maintenance start`: references, lock; records the window (time,
    image, live schema); stops app and tutor, verifies them stopped and
    PostgreSQL running;
  - `rehearse <manifest> <dump>`: full image identity check; backup
    record (BACKUP OK, database, `legacy` or `current`, six hours,
    checksum); space per filesystem (copy, restore estimate, migration,
    margin; fail closed); private project `mentorpro-rehearsal-<id>` from
    `deploy/compose.rehearsal.yml` with generated credentials; resolved
    configuration and running containers checked (own names, own internal
    network only, own volume only, no published port, env files only in
    the rehearsal directory); dump copy 0600; restore must reproduce the
    backup's data fingerprint; dry run, `apply`, schema `current 0001`,
    writing counts and relationships, attempt-1 backfill, nothing changed
    outside the migration; app and tutor started; checker container
    inside the network (student 200s, no tutor routes on the student
    service, tutor 403s, production database and outside address
    unreachable); cleanup by project label and marked directory, then
    verified; `REHEARSAL OK` or `FAILED` record with measured durations,
    bound to the release digest and dump checksum;
  - `migrate <manifest> --backup <dump>` (G2): under the T044 lock,
    re-entrant in one process; same window reference; no running app or
    tutor and no other database session; backup taken after the window
    started; `REHEARSAL OK` for the same digest and dump, six hours;
    live schema `legacy` and live fingerprint equal to the backup's;
    counts equal to the rehearsal's; space; 40-minute checkpoint and
    60-minute projection (twice the rehearsal's remaining steps). Dry run
    (a failure here is `MIGRATE REFUSED before apply`, schema checked
    unchanged), migration marker, `apply`, verification against the
    rehearsal, preflight record, T044 deploy path without a rollback
    proposal. A failure during or after `apply` stops app and tutor and
    reports `DATABASE RECOVERY DECISION REQUIRED`; no restore, no
    rollback;
  - `maintenance end`: refused once a migration started; otherwise
    requires the schema and `release.env` unchanged since the start, then
    starts the previous release, waits for health and runs smoke.
- `deploy/mentorpro_deploy.py`: lock re-entrant within one process;
  `deploy_locked` and `write_preflight` factored out; the backup record
  reader keeps `created` and `fingerprint`.
- `deploy/mentorpro`: dispatch and usage; `tests/app/test_deploy.py`
  unknown-command example is now `restore`.
- `tests/app/test_deploy_migrate.py`: 85 unit tests and two Docker
  tests.
- ADR-033 "I5 decisions"; plan status, PO decisions and implementation
  changes.

## Observation

| Check | Result |
| --- | --- |
| Unit tests (local) | 85 passed; 2 Docker tests and 1 POSIX-mode test skipped (Windows, no Docker) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` (logs `.ace/logs/verify/20261029-104707-26`, and `20261029-110938-925` with the documents) |
| PR CI 40914816729 | failed: seed container could not import the application (test harness); fixed |
| PR CI 40915643538 | failed: test-project cleanup bug (test harness); fixed |
| PR CI [40916932558](https://github.com/jonnabio/Mentor-Pro/actions/runs/40916932558) (head `49ebfdc`) | success: 734 passed, 111 skipped with Docker mandatory (+88: 85 unit + 2 Docker + 1 POSIX test; skips unchanged, so both Docker tests ran and passed); `LABELS OK`; both smoke tests; `MANIFEST OK` (`pr23-49ebfdc`); publish and release skipped |

The Docker tests build a real image from this repository, push it with a
label-less pre-T036 stand-in to a local registry, and seed a synthetic
legacy database (curriculum, practice, generation, llm, writing; three
exercises with drafts, submissions, one completed evaluation and two
criterion scores) in project `mentorpro-i5test-<id>`.

Window test:

- migrate outside a window refused; a refusal inside one, then
  `maintenance end` on the unchanged schema restarts the previous
  release;
- backup with services stopped; migrate without a rehearsal refused;
- rehearsal refused before start: production network in the compose
  file (isolation check, cleanup verified), insufficient space, tampered
  dump, mismatched labels; no rehearsal resource remained;
- `REHEARSAL OK`: isolation verified, smoke 9/9 inside the network
  (including production database and outside address unreachable),
  cleanup verified, backup kept, production schema and PostgreSQL
  container unchanged;
- migrate refused for another dump, a stale rehearsal, a projection over
  60 minutes, the 40-minute checkpoint passed, data changed after the
  backup, a running tutor, another window reference and a missing
  authorization; schema still `legacy`;
- `MIGRATE OK` and `DEPLOY OK`: schema `current 0001`; writing counts
  and relationships unchanged; three attempt-1 records, none other; app
  and tutor on the release digest; PostgreSQL never recreated; window
  closed;
- rollback to the pre-T036 image refused as incompatible; no row text,
  database URL or token in `RELEASES` or output; both backups kept.

Failure test:

- injected dry-run failure (the migration cannot reach the database):
  `MIGRATE REFUSED before apply`, old schema confirmed unchanged;
- injected failure after apply (tutor token too short, so the tutor
  service cannot start): `MIGRATE FAILED at deploy`, app and tutor
  stopped, schema `current` with records intact, no restore, no
  rollback proposal;
- `maintenance end`, a second migrate and a rollback refused.

Durations: the window test writes the rehearsal's measured durations to
the CI job summary. They come from a three-exercise synthetic database,
so they show the fixed cost of the steps, not the size of a real window.

## Not verified

- Nothing ran on the server: root ownership of
  `/var/lib/mentor-pro/rehearsal`, the Docker data directory, free space,
  the compose plugin's `config --format json` and `--wait` there are
  assumptions until an authorized dry run.
- Restore and migration time on a production-sized dump: a real window
  can only be proposed after measuring it, which requires separate
  authorization of a rehearsal on a real production backup.
- The restore estimate (ten times the compressed dump plus 256 MiB) and
  the projection factor (two) are conservative choices, not
  measurements.
- Release prerequisites remain open: T039, T032/T033 acceptance, the
  `v*` tag protection, the real GHCR release path, and separate
  authorization for server adoption, production backup rehearsal,
  migration and deployment.

## Next

PO review of PR #23. Merge only with approval.
