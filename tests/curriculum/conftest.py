"""Fixtures for curriculum catalog tests."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from workbook_fixtures import PgTarget, catalog_rows, drop_target, evidence_rows, new_target, register, write_workbook


@pytest.fixture()
def build(tmp_path) -> Callable[..., tuple[Path, Path]]:
    """Return a builder: build(cat=None, ev=None, register_it=True) -> (workbook, manifest)."""
    manifest = tmp_path / "MANIFEST.sha256"
    manifest.write_text("# test manifest\n", encoding="utf-8")
    counter = {"n": 0}

    def _build(cat=None, ev=None, cat_headers=None, register_it=True):
        counter["n"] += 1
        workbook = write_workbook(tmp_path / f"wb{counter['n']}.xlsx",
                                  cat if cat is not None else catalog_rows(),
                                  ev if ev is not None else evidence_rows(), cat_headers)
        if register_it:
            register(manifest, workbook)
        return workbook, manifest

    return _build


@pytest.fixture()
def db() -> PgTarget:
    """A fresh PostgreSQL schema in the test database; fails (never skips) if unreachable."""
    import psycopg

    target = new_target()
    try:
        psycopg.connect(target.url, connect_timeout=5).close()
    except psycopg.OperationalError as exc:
        pytest.fail(f"PostgreSQL test database unreachable ({type(exc).__name__}); set TEST_DATABASE_URL")
    yield target
    drop_target(target)
