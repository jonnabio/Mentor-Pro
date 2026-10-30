# T045 Plan: Isolated Migration Rehearsal and Gated Migration (ADR-033 I5)

- **Date:** 2026-10-29
- **Role:** Architect
- **Status:** APPROVED by the PO (2026-10-29) with decisions and
  safeguards recorded in ADR-033 "I5 decisions"; implemented in T045
  (synthetic data only). Not authorized: any run on the server, real
  production data, the production migration or deployment.
- **Decision record:** [ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md)
  decision 6 (G2), PO decision 4 (rehearsal on a production dump copy,
  in principle), refinements R4 to R7; ADR-032 (migration `0001`);
  ADR-030 section 6 (database restore)
- **Builds on:** T042 (`backup`, `verify-backup`), T043 (manifests),
  T044 (`preflight`, `deploy`, `rollback`, evidence records, lock)

## Analyze

Production runs a pre-T036 image on a `legacy` writing schema. Any image
with T036 needs migration `0001_student_attempts`, which I4 refuses with
`MIGRATION REQUIRED (G2)`. The T036 release condition is a restore
rehearsal that proves the migration on real data before production.

What exists:

- `python -m app.writing.migrate status|apply [--dry-run]|repair|
  rollback`, in the image; `apply` reports per-table fingerprints and
  refuses on a mismatch (ADR-032);
- restore-checked dumps with `<dump>.verify` (database, schema state,
  fingerprint, verification time);
- the I4 evidence pattern: records bound to a digest and a dump, six
  hours, lock, `RELEASES`, references recorded but not verified.

Missing: an isolated place to restore a dump and run the target image,
the `REHEARSAL OK` evidence, and the `migrate` command with gate G2.

## Discuss (design)

### 1. `mentorpro rehearse <manifest.json> <dump>`

Proves that **this release** migrates and runs on **this dump**. It
never connects to production.

1. Checks before anything starts: the manifest passes the I4 identity
   checks (registry digest, tag, labels); the dump passes `verify-backup`
   (checksum and full restore check, T042); the dump's schema state is
   `legacy` or `current`.
2. Copy (R4): the dump is copied on the server only, root-owned `0600`,
   into a `0700` directory `/var/lib/mentor-pro/rehearsal/<id>/`. Never
   off the server, into Git, CI, logs or chat.
3. Isolation (R5): a compose project `mentorpro-rehearsal-<id>` from a
   new `deploy/compose.rehearsal.yml`:
   - its own PostgreSQL and volume, and one network with
     `internal: true`; **no published ports at all**;
   - app and tutor of the target digest on that internal network;
   - generated env files in the rehearsal directory (random database
     password, random tutor token, rehearsal host names); no production
     env file is mounted or read;
   - before start, the script inspects the project and refuses if any
     container joins a non-rehearsal network or mounts a non-rehearsal
     volume, or if a name lacks the `mentorpro-rehearsal-` prefix.
4. Restore the copy; record `status` (expected `legacy`).
5. `migrate apply --dry-run`, then `migrate apply`, then `status` =
   `current`, all with the target image inside the rehearsal network.
   The application's own fingerprint comparison must pass, and the
   T042 fingerprint of every table outside `writing` must be unchanged.
6. Start app and tutor; smoke from a short-lived checker container on
   the internal network (student endpoints 200, tutor `/tutor` 403 from
   inside, tutor API 403 without the token, student service 404 on tutor
   routes).
7. Cleanup (R6), pass or fail: remove the project's containers, network
   and volume and the dump copy; list them again; fail if anything
   remains. Removal only by the rehearsal prefix and compose label;
   production resources are never named; no `down -v`.
8. Record `REHEARSAL OK` (or `FAILED` with the step) in
   `state/rehearsal/<digest>.json`: release, digest, dump file name and
   sha256, schema before and after, counts and digests only, times,
   operator, cleanup result. Appended to `RELEASES` as `action=rehearse`.

Output is counts, digests and step results only; never row data.

### 2. Maintenance window and `mentorpro migrate` (gate G2)

The only command that changes the production schema. Proposed flow, all
in one PO-approved window:

1. `mentorpro maintenance start --window <ref> --authorization <ref>`:
   `compose stop app tutor`; PostgreSQL keeps running; recorded in
   `RELEASES`. Students are offline from here. Data no longer changes.
2. `mentorpro backup`: `BACKUP OK` with the services stopped.
3. `mentorpro rehearse <manifest> <that dump>`: `REHEARSAL OK`.
4. `mentorpro migrate <manifest> --backup <that dump> --window <ref>
   --authorization <ref>`. Under the I4 lock it requires:
   - app and tutor stopped (maintenance recorded);
   - `REHEARSAL OK` for the **same digest** and the **same dump**;
   - that dump `BACKUP OK`, of the production database, at most six
     hours old;
   - the live fingerprint still equal to the dump's (nothing changed
     since the backup) and the live schema `legacy`;
   - the I4 identity check of the manifest again;
   - window and PO authorization references (recorded, not verified).

   Then `migrate apply --dry-run` and `migrate apply` with the target
   image (`compose run --rm --no-deps app python -m app.writing.migrate
   ...`), `status` = `current`, and the I4 `deploy` path (preflight
   under the same lock, health, smoke).
5. `mentorpro maintenance end`: only while the schema is unchanged (a
   refusal, or a failure before `apply`); it checks the live schema is
   still `legacy`, then starts app and tutor with the unchanged
   `release.env` and runs smoke.

Failure handling: a failure before `apply` changes nothing in the
schema; services stay stopped until `maintenance end`. A failure in or
after `apply` is not undone by the script: `MIGRATE FAILED` with the
step, services stay stopped, and the database-restore procedure (G3,
PO approval) is printed, because an application rollback across `0001`
is refused by design.

### 3. What stays out

- No automatic database restore; G3 stays a separate PO-approved
  operation (ADR-030 section 6).
- No migration from GitHub Actions; operator-triggered only.
- `migrate rollback` and `repair` are not wrapped (manual, PO-approved).

## Test plan (synthetic only)

- Unit tests: rehearsal and migrate evidence binding (digest, dump
  sha256, schema states, age), project-name and mount guards, cleanup
  refusal for non-rehearsal names, command refusals without references.
- Docker tests, mandatory in CI, with the local registry pattern of T044
  and a **real image built from this repository** (needed for the actual
  migration code), on a synthetic legacy database created with the
  pre-T036 schema used by the T036 tests:
  1. `rehearse`: `REHEARSAL OK`; non-writing fingerprints unchanged;
     no published port; no container outside the project; cleanup
     verified;
  2. tampered dump, mismatched digest, a production-named network or
     volume in the project: refused before start;
  3. `migrate` with services running, without `REHEARSAL OK`, with
     another dump, data changed since the backup, stale evidence or
     missing references: refused, schema untouched;
  4. full window on the synthetic "production" project: maintenance
     start, backup, rehearse, migrate, `current`, deploy OK, smoke;
     and maintenance end after a refusal;
  5. injected migration failure: `MIGRATE FAILED`, no automatic
     rollback, restore procedure printed, PostgreSQL not recreated;
  6. production-named resources unchanged; all test resources removed.

## Not in I5

Any run on the server, use of a real production dump, the production
migration itself (I6 and later, each separately authorized), the `v*`
ruleset and the real GHCR release (open release prerequisites).

## PO decisions requested

1. Rehearsal with **no published ports** (smoke from a checker container
   on the internal network) instead of loopback ports. Proposed: yes.
2. Same-window flow (section 2) with the rehearsal on the dump taken
   with services stopped. The alternative, rehearsing earlier on a
   recent dump, shortens the outage but proves the migration on data
   that is not exactly what is migrated. Proposed: same window.
3. Maximum student downtime accepted for the migration window, and
   whether the tutor may stay up (proposed: both stopped; ADR-032).
4. Location and size limit for the rehearsal copy on the server
   (proposed `/var/lib/mentor-pro/rehearsal`, refuse below a free-space
   threshold of twice the dump size).
5. Approve I5 as task T045 on a feature branch, PR to `dev`, synthetic
   data only; the first rehearsal on a real production dump is a
   separate authorization.

## PO decisions (2026-10-29)

1. No published ports; smoke tests inside the isolated network: APPROVED.
2. Final rehearsal in the same window, on the exact backup intended for
   the migration: APPROVED.
3. Stop both student and tutor services before the final backup:
   REQUIRED. Planned student downtime at most 60 minutes, including
   backup, rehearsal, migration, startup and smoke tests; checkpoint at
   40 minutes if the migration has not begun; abort and reassess when the
   window cannot be met.
4. Rehearsal files under `/var/lib/mentor-pro/rehearsal`, root-owned,
   restricted, verified cleanup: APPROVED.
5. I5 as T045 on a feature branch, PR into `dev`, synthetic data only:
   APPROVED. Rehearsals on real production data, server changes, the
   production migration, deployment, GHCR publication and merge into
   `main` remain NOT AUTHORIZED.

## Changes from the design during implementation

- `rehearse` also requires window and PO authorization references
  (recorded like the others).
- `rehearse` does not run `verify-backup` again: it checks the backup
  record (BACKUP OK, database, schema state, six hours, archive
  checksum), then the restore into the rehearsal must reproduce the
  record's data fingerprint, which is the same proof.
- `migrate` additionally requires the backup to be taken after the
  window started, the live writing counts to equal the rehearsal's, and
  the migrated counts and attempts to equal the rehearsal's.
- The downtime projection uses the rehearsal's measured dry run, apply,
  verification, startup and smoke times, doubled.
- PR #23 review corrections: the maintenance window has an identity
  that `rehearse` records and `migrate` and `maintenance end` check; a
  `rehearse` needs the open window; missing, negative, nonnumeric or
  non-finite durations refuse the migration.
