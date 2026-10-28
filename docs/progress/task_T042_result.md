# T042 Result: Restore-checked Backups (ADR-033 I2)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T042-restore-checked-backup` (from `dev` at `cf43e91`)
- **Status:** implemented and verified locally with synthetic data; PR to
  `dev` for PO review, not merged. Not used on the server.

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

Tests `tests/app/test_deploy_backup.py` (synthetic schema `t042_backup`
in `mentor_pro_test`: accents, timestamps, JSON, NULLs, an empty table).

## Observation

| Check | Result |
| --- | --- |
| Backup restored and compared; record without data; re-verify | pass |
| Same data twice: same fingerprint; one row changed: different | pass |
| Truncated dump | `VERIFY FAILED: file checksum differs` |
| Damaged dump with a matching checksum | `VERIFY FAILED` (not restorable or differs), cleanup verified |
| Record fingerprint not matching the restore | `VERIFY FAILED: restored data differs` |
| Unreadable source | `BACKUP FAILED`, recorded, never OK |
| Existing dump names | refused, files untouched |
| Local provider on a non-test database | `BACKUP REFUSED`, nothing created |
| Docker provider end to end; `docker compose config` | **skipped**: no Docker on this workstation; they run on Linux CI after merge |
| `test_deploy_backup.py` + `test_deploy.py` | 23 passed, 2 skipped |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 649 passed, 2 skipped (log `.ace/logs/verify/20261028-165342-4767`); the test gate took 16.6 min locally |

Not tested: a change to the data during the dump (the before/after
comparison exists but no test forces a concurrent write).

No server, production volume, secret, workflow, image or container change.

## Next

PO review of the PR. After merge, check that CI ran the two Docker tests
(not skipped). I3 needs its own task and approval.
