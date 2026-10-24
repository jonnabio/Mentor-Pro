"""Automation must refuse the student database (ADR-016, T014.1)."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from curriculum import db
from workbook_fixtures import REPO_ROOT

STUDENT = "postgresql://u@127.0.0.1:1/mentor_pro"


@pytest.fixture()
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(f"DATABASE_URL={STUDENT}\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("url", [
    STUDENT,
    "postgresql://u:s3cret@127.0.0.1:1/mentor_pro",
    "postgresql://u@127.0.0.1:1/mentor_pro_test?dbname=mentor_pro",  # libpq override
    "postgresql://u@127.0.0.1:1/test_mentor_pro",
])
def test_refuses_non_test_databases(url, env_file):
    with pytest.raises(db.UnsafeDatabaseError) as exc:
        db.require_test_database(url, env_file)
    assert "s3cret" not in str(exc.value)


def test_refuses_test_named_database_that_is_the_student_database(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://u@h:5432/school_test\n", encoding="utf-8")
    with pytest.raises(db.UnsafeDatabaseError, match="also the student database"):
        db.require_test_database("postgresql://other@h:5432/school_test", env_file)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h:5432/school_test")
    with pytest.raises(db.UnsafeDatabaseError, match="also the student database"):
        db.require_test_database("postgresql://other@h:5432/school_test", tmp_path / "missing.env")


def test_accepts_dedicated_test_database(env_file, monkeypatch):
    url = "postgresql://u@127.0.0.1:1/mentor_pro_test"
    monkeypatch.delenv("DATABASE_URL")
    assert db.require_test_database(url, env_file) == url
    monkeypatch.setenv("DATABASE_URL", url)  # the harness redirect itself is not a student database
    assert db.require_test_database(url, env_file) == url


def test_pytest_session_runs_on_the_test_database():
    assert db.database_name(os.environ["DATABASE_URL"]).endswith("_test")
    assert os.environ["DATABASE_URL"] == os.environ["TEST_DATABASE_URL"]
    assert db.database_url() == os.environ["TEST_DATABASE_URL"]


def _run(args: list[str], test_url: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TEST_DATABASE_URL": test_url, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, *args], cwd=REPO_ROOT, env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def test_browser_automation_refuses_student_database(tmp_path):
    """practice_e2e.py stops with exit code 2 before any connection (port 1 would fail slowly otherwise)."""
    for live in ([], ["--live"]):
        started = time.monotonic()
        result = _run(["scripts/dev/practice_e2e.py", "--out", str(tmp_path), *live], STUDENT)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "E2E=refused" in result.stdout and "mentor_pro" in result.stdout
        assert time.monotonic() - started < 60
        assert not list(tmp_path.glob("*.png"))


def test_pytest_refuses_student_database():
    result = _run(["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests/ace/test_schemas.py"],
                  STUDENT)
    assert result.returncode == 4, result.stdout + result.stderr  # pytest usage error: nothing collected or run
    assert "refusing to run automation" in result.stdout + result.stderr
