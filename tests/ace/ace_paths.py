"""Paths and loaders shared by question-engine skill tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / ".ace" / "skills" / "question-quality-review" / "scripts"
EXAMPLES = REPO_ROOT / ".ace" / "schemas" / "question-engine" / "examples"
SCHEMAS = REPO_ROOT / ".ace" / "schemas" / "question-engine"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / ".ace" / "scripts"))


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

