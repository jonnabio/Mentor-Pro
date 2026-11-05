"""Versioned, explicit migrations of the `llm` schema (T055; same rules as app.writing.migrations, ADR-032/033).

Nothing here runs at application start. `UsageStore` still creates the original `llm.usage_record` table on an
empty database (pre-T055 behavior); every later change is applied only by an operator:

    python -m app.llm.migrate status
    python -m app.llm.migrate apply [--dry-run]
    python -m app.llm.migrate rollback

L001_paid_cost_tracking (additive only):
- six nullable columns on `llm.usage_record`: subject, objective_code, reasoning_tokens, failure_category,
  authorization_id, liability_usd (worst-case USD held for a paid attempt whose cost is not yet known);
- table `llm.paid_authorization`.

Compatibility (no change to the writing schema range 0001..0001, so `deploy/` is unchanged):
- an image with T055 runs on an unmigrated database: usage rows are written without the new columns and every
  paid command refuses ("L001 not applied"), so it behaves free-only exactly as before;
- an older image runs on a migrated database: its inserts name their columns, and the new ones are nullable.
`apply` is one transaction under an advisory lock, idempotent (a second run reports `already_applied`), and
checks that existing usage rows are unchanged (count and digest of the original columns). `rollback` removes
L001 only while no paid authorization exists and no row uses a new column; otherwise it refuses (data would be
lost). Take a verified backup before `apply` (runbook: production-deployment.md, T055).
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

L001 = "L001_paid_cost_tracking"
MIGRATIONS = (L001,)
LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('bootstrap:llm'))"
NEW_COLUMNS = {"subject": "TEXT", "objective_code": "TEXT",
               "reasoning_tokens": "INTEGER CHECK (reasoning_tokens >= 0)", "failure_category": "TEXT",
               "authorization_id": "TEXT", "liability_usd": "NUMERIC(14, 8) CHECK (liability_usd >= 0)"}
ORIGINAL_COLUMNS = ("call_id", "request_id", "practice_set_id", "purpose", "attempt", "is_fallback",
                    "model_requested", "model_used", "provider", "tier", "tokens_in", "tokens_out", "cost_usd",
                    "cost_source", "latency_ms", "status", "error_kind", "generation_id", "started_at")

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS llm.schema_migration (
    migration_id  TEXT PRIMARY KEY,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    report        JSONB NOT NULL
);
"""

AUTHORIZATION_SQL = """
CREATE TABLE llm.paid_authorization (
    authorization_id  TEXT PRIMARY KEY,
    status            TEXT NOT NULL CHECK (status IN ('pending', 'declined', 'approved', 'in_use', 'consumed',
                                                      'stopped', 'expired')),
    subject           TEXT NOT NULL,
    objective_code    TEXT,
    questions         INTEGER NOT NULL CHECK (questions >= 1),
    model             TEXT NOT NULL,
    estimate          JSONB NOT NULL,
    ceiling_usd       NUMERIC(14, 8) CHECK (ceiling_usd > 0),
    reserved_usd      NUMERIC(14, 8) NOT NULL DEFAULT 0 CHECK (reserved_usd >= 0),
    spent_usd         NUMERIC(14, 8) NOT NULL DEFAULT 0 CHECK (spent_usd >= 0),
    unknown_cost_calls INTEGER NOT NULL DEFAULT 0,
    approver_role     TEXT CHECK (approver_role IN ('parent', 'administrator')),
    stop_reason       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at        TIMESTAMPTZ NOT NULL,
    decided_at        TIMESTAMPTZ,
    finished_at       TIMESTAMPTZ
)
"""

FINGERPRINT_SQL = ("SELECT count(*) AS n, md5(COALESCE(string_agg(row({cols})::text, '|' ORDER BY call_id), '')) "
                   "AS digest FROM llm.usage_record").format(cols=", ".join(ORIGINAL_COLUMNS))


class MigrationError(RuntimeError):
    """Refused or failed; the transaction was rolled back and nothing changed."""


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row)


def _exists(conn: psycopg.Connection, relation: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (relation,)).fetchone()["ok"]


def usage_columns(conn: psycopg.Connection) -> set[str]:
    return {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'llm' "
        "AND table_name = 'usage_record'")}


def is_applied(conn: psycopg.Connection, migration_id: str = L001) -> bool:
    return _exists(conn, "llm.schema_migration") and conn.execute(
        "SELECT 1 FROM llm.schema_migration WHERE migration_id = %s", (migration_id,)).fetchone() is not None


def state(conn: psycopg.Connection) -> dict[str, Any]:
    """`none` (no usage table yet), `base` (pre-T055), `current` (L001) or `drifted` (partial, refused)."""
    if not _exists(conn, "llm.usage_record"):
        return {"state": "none", "applied": []}
    applied = is_applied(conn)
    present = set(NEW_COLUMNS) & usage_columns(conn)
    table = _exists(conn, "llm.paid_authorization")
    if applied and present == set(NEW_COLUMNS) and table:
        return {"state": "current", "applied": [L001]}
    if not applied and not present and not table:
        return {"state": "base", "applied": []}
    return {"state": "drifted", "applied": [L001] if applied else [],
            "columns": sorted(present), "authorization_table": table}


class _DryRun(Exception):
    def __init__(self, report: dict[str, Any]):
        self.report = report


def apply(url: str, dry_run: bool = False) -> dict[str, Any]:
    try:
        return _apply(url, dry_run)
    except _DryRun as done:  # raised inside the transaction, so everything was rolled back
        return {"result": "dry_run_ok", **done.report}


def _apply(url: str, dry_run: bool) -> dict[str, Any]:
    from app.llm.usage import SCHEMA_SQL as USAGE_SQL

    with _connect(url) as conn, conn.transaction():
        conn.execute(LOCK_SQL)
        before = state(conn)
        if before["state"] == "current":
            return {"result": "already_applied", "migration": L001}
        if before["state"] == "drifted":
            raise MigrationError(f"llm schema drifted, refusing: {before}")
        if before["state"] == "none":
            conn.execute(USAGE_SQL)
        rows = conn.execute(FINGERPRINT_SQL).fetchone()
        conn.execute(LEDGER_SQL)
        for name, kind in NEW_COLUMNS.items():
            conn.execute(f"ALTER TABLE llm.usage_record ADD COLUMN {name} {kind}")
        conn.execute(AUTHORIZATION_SQL)
        after = conn.execute(FINGERPRINT_SQL).fetchone()
        if dict(after) != dict(rows):
            raise MigrationError("usage rows changed during the migration; rolled back")
        report = {"migration": L001, "usage_rows": rows["n"], "usage_digest": rows["digest"],
                  "columns_added": list(NEW_COLUMNS), "tables_created": ["llm.paid_authorization"]}
        if dry_run:
            raise _DryRun(report)
        conn.execute("INSERT INTO llm.schema_migration (migration_id, report) VALUES (%s, %s)",
                     (L001, Jsonb(report)))
        return {"result": "applied", **report}


def rollback(url: str) -> dict[str, Any]:
    with _connect(url) as conn, conn.transaction():
        conn.execute(LOCK_SQL)
        if state(conn)["state"] != "current":
            raise MigrationError(f"{L001} is not applied")
        authorizations = conn.execute("SELECT count(*) AS n FROM llm.paid_authorization").fetchone()["n"]
        used = conn.execute("SELECT count(*) AS n FROM llm.usage_record WHERE " + " OR ".join(
            f"{c} IS NOT NULL" for c in NEW_COLUMNS)).fetchone()["n"]
        if authorizations or used:
            raise MigrationError(f"refused: {authorizations} authorizations and {used} usage rows use L001 data")
        conn.execute("DROP TABLE llm.paid_authorization")
        for name in NEW_COLUMNS:
            conn.execute(f"ALTER TABLE llm.usage_record DROP COLUMN {name}")
        conn.execute("DELETE FROM llm.schema_migration WHERE migration_id = %s", (L001,))
        return {"result": "rolled_back", "migration": L001}
