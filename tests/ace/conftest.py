"""Shared fixtures for question-engine skill tests."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".ace" / "skills" / "question-quality-review" / "scripts"
EXAMPLES = REPO_ROOT / ".ace" / "schemas" / "question-engine" / "examples"
SCHEMAS = REPO_ROOT / ".ace" / "schemas" / "question-engine"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / ".ace" / "scripts"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def records_by_id() -> dict:
    return {r["record_id"]: r for r in load(EXAMPLES / "curriculum-records.json")}


@pytest.fixture()
def valid_items() -> list[dict]:
    return copy.deepcopy(load(EXAMPLES / "items-valid.json"))


@pytest.fixture()
def item_by_subject(valid_items) -> dict[str, dict]:
    return {item["subject"]: item for item in valid_items}


@pytest.fixture(scope="session")
def validator():
    import item_checker

    return item_checker.load_validator()
