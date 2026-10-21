"""Fixtures for curriculum catalog tests."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from workbook_fixtures import catalog_rows, evidence_rows, register, write_workbook


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
def db(tmp_path) -> Path:
    return tmp_path / "catalog.sqlite"
