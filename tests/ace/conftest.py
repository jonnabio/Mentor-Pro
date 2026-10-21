"""Shared fixtures for question-engine skill tests."""

from __future__ import annotations

import copy

import pytest

from ace_paths import EXAMPLES, load


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
