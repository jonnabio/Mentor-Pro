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
    """Raised when DATABASE_URL (or TEST_DATABASE_URL) is missing."""


class UnsafeDatabaseError(RuntimeError):
    """Raised when automation is pointed at a database that may hold student data (ADR-016)."""


def _file_setting(name: str, env_file: Path) -> str | None:
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == name and value.strip():
                return value.strip()
    return None


def _setting(name: str, env_file: Path) -> str | None:
    return os.environ.get(name) or _file_setting(name, env_file)


def database_url(env_file: Path = REPO_ROOT / ".env") -> str:
    """Return DATABASE_URL from the environment, else from `.env`."""
    url = _setting("DATABASE_URL", env_file)
    if url:
        return url
    raise ConfigurationError("DATABASE_URL is not set (environment or .env); see .env.example")


def test_database_url(env_file: Path = REPO_ROOT / ".env") -> str:
    """Return TEST_DATABASE_URL from the environment, else from `.env` (automated runs only)."""
    url = _setting("TEST_DATABASE_URL", env_file)
    if url:
        return url
    raise ConfigurationError("TEST_DATABASE_URL is not set (environment or .env); see .env.example")


def database_name(url: str) -> str:
    """The database a URL connects to, parsed with libpq rules (so `?dbname=` overrides count)."""
    from psycopg.conninfo import conninfo_to_dict

    return str(conninfo_to_dict(url).get("dbname") or "")


def require_test_database(url: str, env_file: Path = REPO_ROOT / ".env") -> str:
    """Return `url` if automation may use it; never connects.

    The database name must end in `_test` and must not be the student database named by
    DATABASE_URL in `.env` or in the environment. An environment DATABASE_URL equal to `url`
    is the redirect made by the test harness itself and is not a student database.
    Credentials are never included in the error.
    """
    name = database_name(url)
    if not name.endswith("_test"):
        raise UnsafeDatabaseError(f"refusing to run automation against non-test database {name!r}")
    environment = os.environ.get("DATABASE_URL")
    students = [_file_setting("DATABASE_URL", env_file), environment if environment != url else None]
    if any(s and database_name(s) == name for s in students):
        raise UnsafeDatabaseError(f"refusing to run automation: {name!r} is also the student database")
    return url


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
