"""PostgreSQL connection helpers for the curriculum catalog (ADR-007).

Configuration comes from `DATABASE_URL` (environment first, then the
git-ignored `.env` at the repository root). Credentials are never logged.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_SCHEMA = "curriculum"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


class ConfigurationError(RuntimeError):
    """Raised when DATABASE_URL is missing."""


def database_url(env_file: Path = REPO_ROOT / ".env") -> str:
    """Return DATABASE_URL from the environment, else from `.env`."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "DATABASE_URL" and value.strip():
                return value.strip()
    raise ConfigurationError("DATABASE_URL is not set (environment or .env); see .env.example")


def _check_schema(schema: str) -> str:
    if not _SCHEMA_NAME.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    return schema


def connect(url: str, schema: str = DEFAULT_SCHEMA, *, read_only: bool = False) -> psycopg.Connection:
    """Open a connection with `search_path` set to `schema`.

    Writable connections create the schema and tables if missing. Read-only
    connections reject every write at the server (default_transaction_read_only).
    """
    schema = _check_schema(schema)
    options = f"-c search_path={schema}"
    if read_only:
        options += " -c default_transaction_read_only=on"
    conn = psycopg.connect(url, row_factory=dict_row, options=options, client_encoding="UTF8")
    if not read_only:
        with conn.transaction():
            # IF NOT EXISTS is not race-safe in PostgreSQL; serialize bootstrap per schema.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"bootstrap:{schema}",))
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
            conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    return conn
