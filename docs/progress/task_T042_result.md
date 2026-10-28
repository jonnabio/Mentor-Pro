# T042 Result: Restore-checked Backups (ADR-033 I2)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T042-restore-checked-backup` (from `dev` at `cf43e91`)
- **Status:** PO pre-merge changes applied and verified locally;
  merge authorized once local verification passes; **not verified** until
  post-merge CI runs both Docker tests. Not used on the server.

## Thought

T041 integrated first: PO corrections applied, PR #16 merged as
`cf43e91`; `dev` CI 40781126775 green (539 passed, 102 skipped; it ran
the new deploy tests on Linux under `sh`). ADR-033 refinements R1, R4,
R6 and R8 apply: idempotent, never overwrite, verified cleanup limited to
the run's own resources, counts and digests only.

## Action

`deploy/mentorpro` gains two commands:

- `backup`:
  1. new file `mentor_pro_<date>_<time>.dump` (`noclobber`: an existing
     file is never overwritten; folder `0700`, file `0600`);
  2. fingerprint of the live data **before and after** `pg_dump -Fc`:
     per table, row count and md5 of all rows ordered with
     `COLLATE "C"`, with time zone, date style and float output pinned,
     client encoding UTF-8; a change during the dump fails the backup;
  3. restore with `pg_restore --exit-on-error --single-transaction` into
     a disposable PostgreSQL, fingerprint again, compare;
  4. cleanup, then a check that nothing remains;
  5. `BACKUP OK <file> sha256:<…>` only after all of that.
- `verify-backup <dump>`: file checksum against the record, then the same
  restore and comparison; result appended to the record.
- Record `<dump>.verify`: file name, time, operator, schemas, bytes,
  sha256, table and row counts, per-table counts, overall fingerprint
  digest, result. No row data, no URL, no secret.
- Disposable instance: production provider `docker` (container, internal
  network and volume, all `mentorpro-verify-<id>`, nothing published,
  cleanup refuses any other name); test provider `local` (initdb cluster
  in a temporary folder with a marker file, loopback port; reads only a
  `*_test` database).
- `.gitattributes`: `deploy/mentorpro` and `deploy/*.yml` always LF.

Tests `tests/app/test_deploy_backup.py`: synthetic schema `t042_backup`
(accents, timestamps, JSON, NULLs, an empty table) in a dedicated
disposable database `mentor_pro_backup_test`, created and dropped by the
tests.

PO pre-merge changes (review of PR #17):

- **Scope (1, 2).** The fingerprint now covers every table in every user
  schema (all but `pg_*` and `information_schema`).
  `MENTORPRO_BACKUP_SCHEMAS` (default `curriculum practice generation llm
  writing`) is the expected set: a schema with tables outside it
  (including `public`) or a missing expected schema fails the backup with
  its name. Regression tests for both.
- **Mandatory Docker tests (3).** CI's Linux test job sets
  `MENTORPRO_REQUIRE_DOCKER=1`; there the Docker backup/restore test and
  the `docker compose config` test fail instead of skipping when Docker is
  unavailable. Elsewhere they skip.
- **Isolation (4).** Test containers are `mentorpro-test-live-*`,
  disposable resources `mentorpro-verify-*` (internal network, own
  volume, nothing published); production names are `mentor-pro-*`;
  cleanup refuses any other name.

## Observation

| Check | Result |
| --- | --- |
| Backup restored and compared; record without data; re-verify | pass |
| Same data twice: same fingerprint; one row changed: different | pass |
| Truncated dump | `VERIFY FAILED: file checksum differs` |
| Damaged dump with a matching checksum | `VERIFY FAILED` (not restorable or differs), cleanup verified |
| Record fingerprint not matching the restore | `VERIFY FAILED: restored data differs` |
| Unreadable source | `BACKUP FAILED: schema list not readable`, recorded, never OK |
| Tables in an unexpected schema (`t042_stray`, `public`) | `BACKUP FAILED: unexpected schema(s) with tables: public t042_stray`; with both listed, all 4 tables fingerprinted |
| Expected schema missing (`writing`) | `BACKUP FAILED: expected schema(s) missing: writing` |
| Docker tests with `MENTORPRO_REQUIRE_DOCKER=1` and no Docker | 2 errors (fail, not skip) |
| Existing dump names | refused, files untouched |
| Local provider on a non-test database | `BACKUP REFUSED`, nothing created |
| Docker provider end to end; `docker compose config` | **skipped**: no Docker on this workstation; they run on Linux CI after merge |
| `test_deploy_backup.py` | 10 passed, 2 skipped (Docker) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 651 passed, 2 skipped (Docker), 3.4 min (log `.ace/logs/verify/20261028-172307-6852`) |

## Limits of fingerprint-based checks

- Covers table rows only: sequence positions, large objects, roles,
  privileges, database settings and extensions are not compared (the dump
  carries them; restore uses `--no-owner --no-privileges`). Views and
  indexes are checked only by the restore succeeding.
- md5 per table is an integrity check against accidental corruption and
  incomplete restores, not against deliberate tampering.
- Consistency is proven by equal fingerprints before and after the dump,
  not by a shared snapshot: a write that is undone between the two reads
  could go unnoticed (the dump itself is internally consistent). Busy
  databases may fail with "data changed during the dump"; then retry or
  stop the app and tutor. No test forces a concurrent write.
- Row text depends on the PostgreSQL version's output format; the
  disposable instance must use the same major version (`postgres:17.6`).
- A partitioned table is counted both as the parent and as its
  partitions (none exist today).
- The expected schema set must be kept in step with the application; a
  new schema makes backups fail until it is added (deliberate).

No server, production volume, secret, workflow, image or container change.

## Next

PO review of the PR. After merge, check that CI ran the two Docker tests
(not skipped). I3 needs its own task and approval.
