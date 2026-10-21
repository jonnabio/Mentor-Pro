"""The skill validator passes on the repo and catches broken skills."""

import shutil

import pytest

import validate_skills
from conftest import REPO_ROOT

DOMAIN_SKILLS = [
    "mep-curriculum-grounding", "mep-question-design", "question-quality-review",
    "math-answer-verification", "evidence-coverage-planning", "question-evaluation",
    "openrouter-model-routing", "llm-cost-observability", "curriculum-data-ingestion",
]


def test_repository_skills_are_valid():
    assert validate_skills.validate(REPO_ROOT) == []


def test_standard_lists_all_domain_skills():
    assert sorted(validate_skills.domain_skills(REPO_ROOT)) == sorted(DOMAIN_SKILLS)


@pytest.mark.parametrize("skill", DOMAIN_SKILLS)
def test_domain_skill_is_discoverable(skill):
    triggers = validate_skills.trigger_paths(REPO_ROOT)
    assert f".ace/skills/{skill}/SKILL.md" in triggers.values()


@pytest.fixture()
def repo_copy(tmp_path):
    for part in (".ace", "references/MANIFEST.sha256", "tests", "docs"):
        src = REPO_ROOT / part
        dst = tmp_path / part
        if src.is_dir():
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    shutil.copy2(REPO_ROOT / ".aceconfig", tmp_path / ".aceconfig")
    return tmp_path


def test_detects_name_mismatch(repo_copy):
    path = repo_copy / ".ace/skills/question-evaluation/SKILL.md"
    path.write_text(path.read_text(encoding="utf-8").replace("name: question-evaluation", "name: other"), encoding="utf-8")
    assert any("name 'other'" in p for p in validate_skills.validate(repo_copy))


def test_detects_missing_section(repo_copy):
    path = repo_copy / ".ace/skills/question-evaluation/SKILL.md"
    path.write_text(path.read_text(encoding="utf-8").replace("## Failure Handling", "## Errors"), encoding="utf-8")
    assert any("missing sections" in p for p in validate_skills.validate(repo_copy))


def test_detects_unknown_dependency(repo_copy):
    path = repo_copy / ".ace/skills/question-evaluation/SKILL.md"
    text = path.read_text(encoding="utf-8").replace("| `model-evaluation` |", "| `model-scoring` |")
    path.write_text(text, encoding="utf-8")
    assert any("model-scoring" in p for p in validate_skills.validate(repo_copy))


def test_detects_broken_path(repo_copy):
    path = repo_copy / ".ace/skills/question-evaluation/SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nSee `docs/missing-file.md`.\n", encoding="utf-8")
    assert any("docs/missing-file.md" in p for p in validate_skills.validate(repo_copy))


def test_detects_missing_trigger(repo_copy):
    config = repo_copy / ".aceconfig"
    lines = [l for l in config.read_text(encoding="utf-8").splitlines() if "question-evaluation" not in l]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert any("no .aceconfig skill_trigger" in p for p in validate_skills.validate(repo_copy))
