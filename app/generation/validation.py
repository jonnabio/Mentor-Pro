"""Adapter to the shared deterministic checker owned by question-quality-review (ADR-005)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2] / ".ace" / "skills" / "question-quality-review" / "scripts"


def _load_checker():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))  # item_checker imports cr_math from its own folder
    spec = importlib.util.spec_from_file_location("item_checker", _SCRIPTS / "item_checker.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


item_checker = _load_checker()
_validator = item_checker.load_validator()
CHECKER_VERSION = item_checker.CHECKER_VERSION


def deterministic_check(item: dict[str, Any], records: list[dict[str, Any]], facts: list[str],
                        bank: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return item_checker.check_item(item, {r["record_id"]: r for r in records}, bank or [], facts,
                                   option_count=4, validator=_validator)


def duplicate_reason(item: dict[str, Any], bank: list[dict[str, Any]]) -> str | None:
    """D01 against `bank` alone; the reason if `item` duplicates a bank item, else None."""
    check = item_checker.check_duplicates(item, bank)[0]
    return f"D01: {check['message']}" if check["status"] == "fail" else None
