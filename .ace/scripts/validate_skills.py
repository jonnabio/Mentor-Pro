"""Validate ACE skills: structure, metadata, references and discovery.

Checks every .ace/skills/*/SKILL.md:
  - frontmatter with `name` (== folder name) and non-empty `description`
  - exactly one H1 heading
  - every `.ace/...`, `docs/...` or `references/...` path in backticks exists
  - every `.aceconfig` skill_triggers path exists

Question-engine skills (listed in the Scope table of
.ace/standards/question-engine.md) must additionally:
  - contain the required sections (REQUIRED_SECTIONS)
  - name only existing skills in their Dependencies section
  - be reachable from at least one `.aceconfig` trigger

Standard library only. Exit code 0 = valid, 1 = problems found.

Usage: python .ace/scripts/validate_skills.py [repo_root]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REQUIRED_SECTIONS = (
    "Purpose", "Activation", "Inputs", "Outputs", "Procedures",
    "Dependencies", "Failure Handling", "Examples", "Common Pitfalls", "Invocation",
)
PATH_PATTERN = re.compile(r"`((?:\.ace|docs|references|tests)/[^`\s]+)`")
SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def parse_frontmatter(text: str) -> dict[str, str] | None:
    text = text.lstrip("﻿")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fields: dict[str, str] = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def h2_sections(text: str) -> dict[str, str]:
    body = strip_code_blocks(text)
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.MULTILINE)
    return {parts[i].strip(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def domain_skills(root: Path) -> list[str]:
    standard = root / ".ace" / "standards" / "question-engine.md"
    if not standard.exists():
        return []
    scope = h2_sections(standard.read_text(encoding="utf-8")).get("Scope", "")
    return re.findall(r"^\|\s*`([a-z0-9-]+)`\s*\|", scope, flags=re.MULTILINE)


def trigger_paths(root: Path) -> dict[str, str]:
    config = root / ".aceconfig"
    triggers: dict[str, str] = {}
    in_block = False
    for line in config.read_text(encoding="utf-8").splitlines():
        if line.startswith("skill_triggers:"):
            in_block = True
            continue
        if in_block:
            if line and not line.startswith(" "):
                break
            m = re.match(r"^\s+([\w-]+):\s*(\S+)", line)
            if m:
                triggers[m.group(1)] = m.group(2)
    return triggers


def validate(root: Path) -> list[str]:
    problems: list[str] = []
    skills_dir = root / ".ace" / "skills"
    existing = {p.name for p in skills_dir.iterdir() if p.is_dir()}
    triggers = trigger_paths(root)
    domain = domain_skills(root)

    for keyword, path in triggers.items():
        if not (root / path).is_file():
            problems.append(f".aceconfig trigger {keyword!r} -> missing {path}")

    for folder in sorted(skills_dir.iterdir()):
        if not folder.is_dir():
            continue
        skill_md = folder / "SKILL.md"
        rel = skill_md.relative_to(root).as_posix()
        if not skill_md.is_file():
            problems.append(f"{folder.name}: SKILL.md missing")
            continue
        text = skill_md.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        if meta is None:
            problems.append(f"{rel}: frontmatter missing")
            continue
        if meta.get("name") != folder.name:
            problems.append(f"{rel}: name {meta.get('name')!r} != folder {folder.name!r}")
        if not SKILL_NAME_PATTERN.match(folder.name):
            problems.append(f"{rel}: folder name is not kebab-case")
        if not meta.get("description"):
            problems.append(f"{rel}: description missing")
        h1_count = len(re.findall(r"^# ", strip_code_blocks(text), flags=re.MULTILINE))
        if h1_count != 1:
            problems.append(f"{rel}: expected one H1, found {h1_count}")
        if folder.name not in domain:
            continue

        for ref in PATH_PATTERN.findall(text):
            target = ref.split("#", 1)[0].rstrip("/")
            if any(ch in target for ch in "*<>{}"):
                continue
            # Original curriculum documents are intentionally excluded
            # from Git. Their SHA-256 manifest must still exist.
            if target == "references/original":
                if not (root / "references/MANIFEST.sha256").is_file():
                    problems.append(
                        "references/MANIFEST.sha256 is missing"
                    )
                continue
            if not (root / target).exists():
                problems.append(
                    f"{rel}: referenced path does not exist: {ref}"
                )

        sections = h2_sections(text)
        missing = [s for s in REQUIRED_SECTIONS if s not in sections]
        if missing:
            problems.append(f"{rel}: missing sections {missing}")
        for dep in re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", sections.get("Dependencies", "")):
            if dep not in existing:
                problems.append(f"{rel}: dependency {dep!r} is not an installed skill")
        if not any(Path(p).parent.name == folder.name for p in triggers.values()):
            problems.append(f"{rel}: no .aceconfig skill_trigger points to this skill")

    for name in domain:
        if name not in existing:
            problems.append(f"question-engine standard lists {name!r} but the skill folder is missing")
    return problems


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[2]
    problems = validate(root)
    for problem in problems:
        print(f"[!] {problem}")
    skills = sum(1 for p in (root / ".ace" / "skills").iterdir() if p.is_dir())
    print(f"VALIDATE_SKILLS={'pass' if not problems else 'fail'} skills={skills} problems={len(problems)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
