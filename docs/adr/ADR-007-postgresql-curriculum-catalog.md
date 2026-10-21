# ADR-007: PostgreSQL for the Curriculum Catalog

> **Status:** Accepted
> **Date:** 2026-10-21
> **Amends:** [ADR-006](ADR-006-curriculum-baseline-v1.md) section 6 (Storage)

---

## Context

T002 stored baseline `PNE2026-SUM-v1.0` in SQLite. ADR-004 already chose
PostgreSQL for application data. Before T003 (generation), the Product Owner
asked to migrate the catalog so the application uses one database.

---

## Decision

- PostgreSQL is the application database, configured only by `DATABASE_URL`
  (environment, else the git-ignored `.env`).
- The catalog lives in schema `curriculum`; the five-table logical model,
  columns, keys, uniqueness and check constraints are unchanged
  (`curriculum/schema.sql`).
- Driver: psycopg 3 (`psycopg[binary]==3.2.3`).
- Import guarantees kept and strengthened:
  - parse and validate the workbook before connecting (fail closed);
  - one transaction per import, all or nothing;
  - `pg_advisory_xact_lock` per (schema, baseline version), so concurrent
    imports cannot race; schema bootstrap is serialized the same way;
  - same checksum → `unchanged`; different checksum for the same version →
    refused.
- Catalog reads use server-enforced read-only sessions
  (`default_transaction_read_only`).
- Local setup: native PostgreSQL 17, or `docker-compose.yml`
  (`postgres:17.6`, host port 5433, test database created on init).
- Tests run against a database whose name must end in `_test`
  (`TEST_DATABASE_URL`), each test in its own throwaway schema; an unreachable
  test database fails the suite instead of skipping it.
- SQLite catalog code and files are removed.

---

## Alternatives Considered

### Alternative 1: Keep SQLite for the catalog

- **Pros:** Zero setup.
- **Cons:** Two databases; joins with future application data impossible.
- **Why rejected:** Product Owner decision; ADR-004.

### Alternative 2: ORM and migration framework (SQLAlchemy, Alembic)

- **Pros:** Managed schema evolution.
- **Cons:** New dependencies for five static tables.
- **Why rejected:** Not needed yet; revisit when application tables arrive.

---

## Consequences

### Positive

- One database for catalog and future application data.
- Concurrency-safe, idempotent imports.

### Negative

- Tests need a running PostgreSQL.

### Neutral

- Curriculum content, identifiers and provenance labels are unchanged.

---

## Related

- [ADR-004](ADR-004-web-app-stack.md), [ADR-006](ADR-006-curriculum-baseline-v1.md)
- Report: `docs/progress/task_T003_result.md`
