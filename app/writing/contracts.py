"""Load the rubric and level map; check exercise and evaluation records beyond their JSON Schemas.

JSON Schema covers the shape of each record (.ace/schemas/writing/). The rules here need more than one
record: an exercise must fit its level and point at real rubric criteria, and an evaluation must score
exactly the exercise's criteria with the official 0-4 scale.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "curriculum" / "writing"
SCHEMAS = REPO_ROOT / ".ace" / "schemas" / "writing"
RUBRIC_FILE = DATA / "MEP-RUBRICA-PE-2026.json"
LEVELS_FILE = DATA / "exercise-levels.json"
CONVENTION_CRITERIA = tuple(f"EE{n:02d}" for n in range(7, 19))  # descriptors count non-normative uses


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def schema_validator(name: str) -> jsonschema.Draft202012Validator:
    schema = _load(SCHEMAS / f"{name}.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@lru_cache(maxsize=None)
def rubric() -> dict[str, Any]:
    return _load(RUBRIC_FILE)


@lru_cache(maxsize=None)
def levels() -> dict[str, Any]:
    return _load(LEVELS_FILE)


def criteria() -> dict[str, dict[str, Any]]:
    return {c["code"]: c for c in rubric()["criteria"]}


def handwritten_criteria() -> set[str]:
    return set(levels()["rules"]["handwritten_criteria"])


def level(code: str) -> dict[str, Any]:
    return next(lv for lv in levels()["levels"] if lv["code"] == code)


def _schema_errors(name: str, record: dict[str, Any]) -> list[str]:
    return [f"schema: {'/'.join(map(str, e.path)) or '(root)'}: {e.message}"
            for e in schema_validator(name).iter_errors(record)]


def validate_exercise(exercise: dict[str, Any]) -> list[str]:
    """Problems with an exercise record; empty when valid."""
    errors = _schema_errors("writing-exercise", exercise)
    if errors:
        return errors
    lv = level(exercise["level"])
    targets = exercise["target_criteria"]
    known = criteria()
    if exercise["exercise_id"][3:5] != f"L{lv['ordinal']}":
        errors.append(f"exercise_id prefix does not match level {lv['ordinal']}")
    if exercise["exercise_type"] not in lv["exercise_types"]:
        errors.append(f"exercise_type {exercise['exercise_type']} not allowed for level {lv['code']}")
    outside = [c for c in targets if c not in lv["allowed_criteria"]]
    if outside:
        errors.append(f"criteria not allowed for level {lv['code']}: {outside}")
    core = set(lv["core_criteria"]) | set(lv.get("type_core_criteria", {}).get(exercise["exercise_type"], []))
    missing = sorted(core - set(targets))
    if missing:
        errors.append(f"core criteria missing for level {lv['code']}: {missing}")
    if len(targets) < lv["min_target_criteria"]:
        errors.append(f"level {lv['code']} needs at least {lv['min_target_criteria']} criteria")
    deliverable = exercise["deliverable"]
    if deliverable["evidence_mode"] not in lv["deliverable"]["evidence_modes"]:
        errors.append(f"evidence_mode {deliverable['evidence_mode']} not allowed for level {lv['code']}")
    if deliverable["min"] > deliverable["max"]:
        errors.append("deliverable min exceeds max")
    if deliverable["unit"] != lv["deliverable"]["unit"] or deliverable["min"] < lv["deliverable"]["min"] \
            or deliverable["max"] > lv["deliverable"]["max"]:
        errors.append(f"deliverable outside the range of level {lv['code']}")
    if exercise["exercise_type"] == "development_paragraphs" and (deliverable["min"], deliverable["max"]) != (2, 2):
        errors.append("development_paragraphs requires exactly two paragraphs (EE05)")
    if exercise["exercise_type"] == "conventions_editing" and not (exercise.get("source_text_es") or "").strip():
        errors.append("conventions_editing requires source_text_es (the text to correct)")
    if any(k in exercise for k in ("reference_text_es", "reference_correction", "corrections")):
        errors.append("the tutor-only reference correction must not be part of the exercise record")

    evaluation = exercise["evaluation"]
    if evaluation["rubric_id"] != rubric()["rubric_id"] or evaluation["rubric_sha256"] != rubric()["source"]["file_sha256"]:
        errors.append("evaluation does not reference the current rubric and checksum")
    params = {p["criterion"]: p for p in evaluation["parameters"]}
    if sorted(params) != sorted(targets) or len(params) != len(evaluation["parameters"]):
        errors.append("evaluation parameters must list each target criterion exactly once")
    typed = deliverable["evidence_mode"] == "typed"
    for code, p in params.items():
        if code not in known or p["rubric_ref"] != f"{rubric()['rubric_id']}#{code}":
            errors.append(f"{code}: rubric_ref does not resolve")
        needs_hand = code in handwritten_criteria()
        expected = "not_evaluable" if needs_hand and typed else "scored"
        if p["applicability"] != expected:
            errors.append(f"{code}: applicability must be {expected} for {deliverable['evidence_mode']} evidence")

    provenance = exercise["provenance"]
    if provenance["baseline_version"] != levels()["baseline_version"]:
        errors.append("provenance baseline_version differs from the level map")
    records = {r["workbook_code"]: r["assertion_id"] for r in provenance["curriculum_records"]}
    if sorted(records) != sorted(targets):
        errors.append("curriculum_records must cover exactly the target criteria")
    for code, assertion in records.items():
        c = known.get(code)
        if c and assertion != f"PNE2026-PRI-ESP-PE-B{c['dimension']}-A{c['rubric_number']}":
            errors.append(f"{code}: assertion_id {assertion} does not match the rubric dimension and number")
    if not any(s["role"] == "rubric" and s["document_id"] == rubric()["rubric_id"] for s in provenance["sources"]):
        errors.append("provenance must cite the rubric")
    return errors


def validate_evaluation(evaluation: dict[str, Any], exercise: dict[str, Any]) -> list[str]:
    """Problems with a human evaluation of a submission to `exercise`; empty when valid."""
    errors = _schema_errors("writing-evaluation", evaluation)
    if errors:
        return errors
    if evaluation["exercise_id"] != exercise["exercise_id"]:
        errors.append("evaluation is for a different exercise")
    if evaluation["rubric_id"] != exercise["evaluation"]["rubric_id"] \
            or evaluation["rubric_sha256"] != exercise["evaluation"]["rubric_sha256"]:
        errors.append("evaluation rubric differs from the exercise rubric")
    mode = evaluation["submission"]["evidence_mode"]
    if mode != exercise["deliverable"]["evidence_mode"]:
        errors.append(f"submission evidence {mode} differs from the exercise ({exercise['deliverable']['evidence_mode']})")
    scores = {s["criterion"]: s for s in evaluation["criterion_scores"]}
    if sorted(scores) != sorted(exercise["target_criteria"]) or len(scores) != len(evaluation["criterion_scores"]):
        errors.append("criterion_scores must list each target criterion exactly once")
    for code, s in scores.items():
        if code in handwritten_criteria() and mode == "typed" and s["status"] != "not_evaluable":
            errors.append(f"{code}: requires handwritten evidence; a typed submission is not_evaluable")
        if s["status"] == "not_evaluable" and (code not in handwritten_criteria() or mode != "typed"):
            errors.append(f"{code}: not_evaluable is only for handwritten criteria on typed submissions")
        uses = s.get("non_normative_uses")
        if uses is not None:
            if code not in CONVENTION_CRITERIA:
                errors.append(f"{code}: non_normative_uses applies only to EE07-EE18")
            elif s.get("points") is not None and s["points"] != max(0, 4 - uses):
                errors.append(f"{code}: {uses} non-normative uses correspond to {max(0, 4 - uses)} points, "
                              f"not {s['points']}")
        if evaluation["status"] == "completed" and s["status"] == "pending":
            errors.append(f"{code}: a completed evaluation has no pending criteria")
    return errors


def descriptor(code: str, points: int) -> str:
    """The official descriptor a score refers to."""
    return criteria()[code]["descriptors_es"][points]
