"""Session-wide database isolation for every test suite (ADR-016).

Before any test module is imported, TEST_DATABASE_URL is validated with
`curriculum.db.require_test_database` and DATABASE_URL is redirected to it, so
code that falls back to the default URL can never reach the student database.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from curriculum import db  # noqa: E402

DEFAULT_TEST_DATABASE_URL = "postgresql://mentor_pro_admin@127.0.0.1:5432/mentor_pro_test"


def pytest_configure(config: pytest.Config) -> None:
    try:
        url = db.test_database_url()
    except db.ConfigurationError:
        url = DEFAULT_TEST_DATABASE_URL
    try:
        db.require_test_database(url)
    except db.UnsafeDatabaseError as exc:
        raise pytest.UsageError(f"{exc}; set TEST_DATABASE_URL to a dedicated *_test database") from None
    os.environ["TEST_DATABASE_URL"] = url
    os.environ["DATABASE_URL"] = url
