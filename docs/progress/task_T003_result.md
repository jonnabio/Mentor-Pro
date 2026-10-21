# Task T003 Result: PostgreSQL Migration (Product Owner label T002.1)

> **Date:** 2026-10-21
> **Status:** Verified
> **Decision:** [ADR-007](../adr/ADR-007-postgresql-curriculum-catalog.md)

---

## Summary

The curriculum catalog moved from SQLite to PostgreSQL (schema `curriculum`)
with the same five-table model. Importer and catalog queries were adapted;
curriculum content, identifiers and provenance labels are unchanged.

---

## Migration Results

| Check | Result |
|-------|--------|
| Target | Local PostgreSQL 17.11, database `mentor_pro`, schema `curriculum`, UTF8 |
| Import (`DATABASE_URL` set) | `imported`: 98 assertions, 344 evidencias, 17 blocks, 3 source documents |
| Second import | `unchanged` (idempotent) |
| Workbook SHA-256 after import | `cce57db4…bcc19d3` (unchanged) |
| Multiple-choice objectives selectable | 78 / 78, each with its full evidence list |
| Rubric criteria separate | 20 |
| Text compared with workbook (afirmaciones, concepts, evidencias) | 0 differences |
| Foreign keys in schema | 4 |

### Component counts (unchanged from T002)

| Component | Objectives | Evidencias |
|-----------|-----------|-----------|
| Español — lectura (`EL`) | 8 | 53 |
| Español — escritura (`EE`, rubric) | 20 | 20 |
| Matemáticas | 22 | 108 |
| Ciencias | 19 | 82 |
| Estudios Sociales | 29 | 81 |

---

## Changes

| Area | Change |
|------|--------|
| `curriculum/schema.sql` | PostgreSQL DDL; `imported_at` is `TIMESTAMPTZ`; checksum regex check |
| `curriculum/db.py` | New: `DATABASE_URL` resolution, schema-scoped connections, read-only sessions |
| `curriculum/importer.py` | 2.0.0: psycopg; parse before connect; advisory-locked transaction |
| `curriculum/catalog.py` | psycopg; `open_catalog(url, schema)` read-only |
| `docker-compose.yml`, `db/init/` | Minimal PostgreSQL 17.6 with `mentor_pro` and `mentor_pro_test` |
| `.env.example` | `DATABASE_URL`, `TEST_DATABASE_URL` |
| `requirements.txt` | `psycopg[binary]==3.2.3` |
| Tests | PostgreSQL per-test schemas; SQLite removed |
| Removed | SQLite catalog file and `data/` ignore rule |

### Defect found during migration

A new concurrency test (three simultaneous imports) exposed that
`CREATE SCHEMA IF NOT EXISTS` is not race-safe in PostgreSQL. Schema bootstrap
is now serialized with an advisory lock; the test passes repeatedly.

---

## Test and Gate Results

| Check | Result |
|-------|--------|
| `pytest tests/ace tests/curriculum` | 143 passed, 0 skipped |
| Curriculum tests (incl. 9 acceptance on the real workbook) | 44 passed |
| New tests | Concurrent imports, `DATABASE_URL` resolution, no credential echo, schema-name injection |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |

---

## Limitations

| Topic | Note |
|-------|------|
| Docker Compose | Docker is not installed on this machine; the file was written but not run. Validation used native PostgreSQL 17. |
| Local auth | `pg_hba.conf` uses `trust`; no password exists yet for `mentor_pro_admin` |
| `.env` | Not created yet; run `python scripts/dev/setup_secrets.py` |
| Test database | `mentor_pro_test` (owner `mentor_pro_admin`) created on the native server |
