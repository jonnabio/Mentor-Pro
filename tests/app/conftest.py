"""Fixtures for API tests: a synthetic baseline in a throwaway PostgreSQL schema."""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

TESTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS / "curriculum"))

from workbook_fixtures import drop_target, new_target, register, write_workbook  # noqa: E402
from workbook_fixtures import catalog_rows, evidence_rows  # noqa: E402

from app.main import create_app  # noqa: E402
from curriculum import importer  # noqa: E402

SYNTHETIC = "TEST-v1"


@pytest.fixture(scope="module")
def synthetic_client(tmp_path_factory):
    """API client over the small synthetic workbook (Matemáticas M01–M03, EL01, EE01)."""
    target = new_target()
    try:
        psycopg.connect(target.url, connect_timeout=5).close()
    except psycopg.OperationalError as exc:
        pytest.fail(f"PostgreSQL test database unreachable ({type(exc).__name__}); set TEST_DATABASE_URL")
    folder = tmp_path_factory.mktemp("wb")
    manifest = folder / "MANIFEST.sha256"
    manifest.write_text("", encoding="utf-8")
    workbook = write_workbook(folder / "wb.xlsx", catalog_rows(), evidence_rows())
    register(manifest, workbook)
    importer.import_workbook(workbook, target.url, SYNTHETIC, manifest, target.schema)
    with TestClient(create_app(target.url, target.schema, SYNTHETIC)) as client:
        yield client
    drop_target(target)
