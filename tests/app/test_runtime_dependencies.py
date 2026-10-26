"""RCA-005: every third-party module the app imports at runtime is installed by requirements.txt.

The Docker image installs only requirements.txt; the test suite runs with requirements-dev.txt.
A runtime import satisfied only by a dev requirement passes every test and crashes the container.
"""

from __future__ import annotations

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# Code the container runs: the app, the catalog, and the checker loaded by app/generation/validation.py.
RUNTIME_SOURCES = ("app", "curriculum", ".ace/skills/question-quality-review/scripts")
LOCAL_MODULES = {"app", "curriculum", "item_checker", "cr_math"}


def _name(requirement: str) -> str:
    return re.split(r"[\s\[<>=!~;]", requirement.strip(), maxsplit=1)[0].lower().replace("_", "-")


def production_requirements() -> set[str]:
    lines = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {_name(line) for line in lines if line.strip() and not line.lstrip().startswith(("#", "-"))}


def installed_by(requirements: set[str]) -> set[str]:
    """The declared distributions plus everything they depend on (what `pip install -r` installs)."""
    seen, pending = set(), list(requirements)
    while pending:
        dist = pending.pop()
        if dist in seen:
            continue
        try:
            requires = metadata.requires(dist) or []
        except metadata.PackageNotFoundError:
            continue  # a marker-only dependency (e.g. python_version < "3.11") not needed here
        seen.add(dist)
        for req in requires:
            if "extra ==" not in req:
                pending.append(_name(req))
    return seen


def runtime_imports() -> dict[str, str]:
    """Top-level third-party module -> one file importing it (including imports inside functions)."""
    found: dict[str, str] = {}
    for source in RUNTIME_SOURCES:
        for path in sorted((REPO_ROOT / source).rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    top = module.split(".")[0]
                    if top not in sys.stdlib_module_names and top not in LOCAL_MODULES:
                        found.setdefault(top, path.relative_to(REPO_ROOT).as_posix())
    return found


def test_runtime_imports_are_installed_by_production_requirements():
    providers = metadata.packages_distributions()
    production = installed_by(production_requirements())
    missing = {}
    for module, where in runtime_imports().items():
        dists = {_name(d) for d in providers.get(module, [module])}
        if not dists & production:
            missing[module] = where
    assert not missing, f"imported at runtime but not installed by requirements.txt: {missing}"


def test_jsonschema_is_a_production_requirement():
    assert "jsonschema" in production_requirements()  # the RCA-005 image crashed without it
