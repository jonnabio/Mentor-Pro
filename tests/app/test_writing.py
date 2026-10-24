"""Producción escrita foundation (T020, ADR-019): rubric, levels, contracts, evaluations, progress, storage."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import psycopg
import pytest

from app.writing import contracts, progress
from app.writing.store import InvalidRecord, WritingStore

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "curriculum"))
from workbook_fixtures import TEST_DATABASE_URL, baseline_workbook, drop_target, new_target  # noqa: E402

EXAMPLES = REPO / ".ace" / "schemas" / "writing" / "examples"
ALL = [f"EE{n:02d}" for n in range(1, 21)]
# The only wording difference between the rubric PDF and the baseline record (baseline unchanged, ADR-019).
KNOWN_STATEMENT_DIFFERENCES = {
    "EE05": ("Redacta con cohesión dos párrafos de desarrollo y cada uno con su idea principal",
             "Redacta con cohesión dos párrafos de desarrollo, cada uno con su idea principal"),
}


def load(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def exercises():
    return {e["exercise_id"]: e for e in load("exercises.json")}


@pytest.fixture()
def evaluations():
    return load("evaluations.json")


# ---------------------------------------------------------------- rubric and levels

def test_rubric_and_levels_validate_against_their_schemas():
    for name, record in (("writing-rubric", contracts.rubric()), ("writing-levels", contracts.levels())):
        assert not list(contracts.schema_validator(name).iter_errors(record)), name


def test_rubric_has_all_twenty_criteria_with_five_descriptors():
    rubric = contracts.rubric()
    assert [c["code"] for c in rubric["criteria"]] == ALL
    assert all(c["rubric_number"] == int(c["code"][2:]) for c in rubric["criteria"])
    assert all(len(c["descriptors_es"]) == 5 and all(d.startswith("El texto ") for d in c["descriptors_es"])
               for c in rubric["criteria"])
    assert [d["weight_pct"] for d in rubric["dimensions"]] == [20, 20, 40, 15, 5]
    per_dimension = {d: [c["code"] for c in rubric["criteria"] if c["dimension"] == d] for d in range(1, 6)}
    assert per_dimension == {1: ["EE01", "EE02"], 2: ["EE03"], 3: ["EE04", "EE05", "EE06"],
                             4: [f"EE{n:02d}" for n in range(7, 19)], 5: ["EE19", "EE20"]}
    assert contracts.descriptor("EE01", 0) == "El texto presenta menos de 50 palabras."
    assert contracts.descriptor("EE13", 4) == "El texto evidencia los usos normativos de la rrr."  # verbatim


def test_rubric_checksum_matches_the_reference_manifest():
    manifest = (REPO / "references" / "MANIFEST.sha256").read_text(encoding="utf-8")
    source = contracts.rubric()["source"]
    assert f"{source['file_sha256']} *{source['file_name']}" in manifest
    pdf = REPO / "references" / "original" / source["file_name"]
    if pdf.is_file():  # the reference files are not in Git
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == source["file_sha256"]


@pytest.mark.skipif(baseline_workbook() is None, reason="baseline workbook not present in references/original/")
def test_rubric_statements_match_the_imported_baseline_records():
    from curriculum import importer

    target = new_target()
    try:
        importer.import_workbook(baseline_workbook(), target.url, "PNE2026-SUM-v1.0", schema=target.schema)
        with psycopg.connect(target.url) as conn:
            rows = conn.execute(
                f"""SELECT a.workbook_code, a.id, a.text_es, b.assessment_type FROM {target.schema}.assertion a
                    JOIN {target.schema}.block b ON b.id = a.block_id AND b.baseline_version = a.baseline_version
                    WHERE a.workbook_code LIKE 'EE%%'""").fetchall()
    finally:
        drop_target(target)
    baseline = {code: (aid, text, kind) for code, aid, text, kind in rows}
    assert sorted(baseline) == ALL and {kind for _, _, kind in baseline.values()} == {"written_rubric"}
    for c in contracts.rubric()["criteria"]:
        aid, text, _ = baseline[c["code"]]
        assert aid == f"PNE2026-PRI-ESP-PE-B{c['dimension']}-A{c['rubric_number']}"
        if c["code"] in KNOWN_STATEMENT_DIFFERENCES:
            pdf_start, baseline_start = KNOWN_STATEMENT_DIFFERENCES[c["code"]]
            assert c["statement_es"].startswith(pdf_start) and text.startswith(baseline_start)
        else:
            assert text == c["statement_es"], c["code"]


def test_five_levels_account_for_all_twenty_criteria():
    lv = contracts.levels()["levels"]
    assert [x["code"] for x in lv] == ["writing_conventions", "idea_development", "paragraph_writing",
                                      "guided_composition", "full_composition"]
    assert [x["ordinal"] for x in lv] == [1, 2, 3, 4, 5]
    assert sorted({c for x in lv for c in x["allowed_criteria"]}) == ALL
    assert lv[4]["core_criteria"] == ALL  # the full composition scores every criterion
    for x in lv:
        core = set(x["core_criteria"]) | {c for v in x.get("type_core_criteria", {}).values() for c in v}
        assert core <= set(x["allowed_criteria"]), x["code"]
        assert set(x.get("type_core_criteria", {})) <= set(x["exercise_types"])
    hand = contracts.handwritten_criteria()
    assert hand == {"EE19", "EE20"}
    assert [x["code"] for x in lv if hand & set(x["allowed_criteria"])] == ["guided_composition", "full_composition"]


# ---------------------------------------------------------------- exercise contract

def test_example_exercises_are_valid(exercises):
    assert {e["level"] for e in exercises.values()} == {"idea_development", "full_composition"}
    for exercise in exercises.values():
        assert contracts.validate_exercise(exercise) == [], exercise["exercise_id"]


@pytest.mark.parametrize("change,expected", [
    (lambda e: e["target_criteria"].append("EE01"), "not allowed for level"),
    (lambda e: e["target_criteria"].remove("EE04"), "core criteria missing"),
    (lambda e: e.update(exercise_type="full_composition"), "not allowed for level"),
    (lambda e: e["evaluation"]["parameters"][0].update(rubric_ref="MEP-RUBRICA-PE-2026#EE09"), "does not resolve"),
    (lambda e: e["evaluation"].update(rubric_sha256="0" * 64), "current rubric"),
    (lambda e: e["provenance"]["curriculum_records"][0].update(assertion_id="PNE2026-PRI-ESP-PE-B1-A1"),
     "does not match"),
    (lambda e: e.update(language="es-ES"), "schema"),
])
def test_invalid_short_exercises_are_rejected(exercises, change, expected):
    exercise = copy.deepcopy(exercises["PE-L2-ambiente-intro-001"])
    change(exercise)
    problems = contracts.validate_exercise(exercise)
    assert any(expected in p for p in problems), problems


def test_typed_full_composition_marks_handwriting_criteria_not_evaluable(exercises):
    exercise = copy.deepcopy(exercises["PE-L5-agua-salud-001"])
    exercise["deliverable"]["evidence_mode"] = "typed"
    problems = contracts.validate_exercise(exercise)
    assert sorted(p.split(":")[0] for p in problems) == ["EE19", "EE20"]
    for p in exercise["evaluation"]["parameters"]:
        if p["criterion"] in ("EE19", "EE20"):
            p.update(applicability="not_evaluable", not_evaluable_reason="handwritten_evidence_required")
    assert contracts.validate_exercise(exercise) == []


# ---------------------------------------------------------------- human evaluation

def test_example_evaluations_are_valid(exercises, evaluations):
    for evaluation in evaluations:
        assert contracts.validate_evaluation(evaluation, exercises[evaluation["exercise_id"]]) == []


def test_evaluation_rules(exercises, evaluations):
    short = exercises["PE-L2-ambiente-intro-001"]
    full = exercises["PE-L5-agua-salud-001"]
    bad = copy.deepcopy(evaluations[0])
    bad["criterion_scores"][3]["points"] = 4  # two non-normative uses mean 2 points
    assert any("correspond to 2 points" in p for p in contracts.validate_evaluation(bad, short))
    bad = copy.deepcopy(evaluations[0])
    bad["criterion_scores"].pop()
    assert any("exactly once" in p for p in contracts.validate_evaluation(bad, short))
    bad = copy.deepcopy(evaluations[0])
    bad["criterion_scores"][0] = {"criterion": "EE03", "status": "pending"}
    assert any("pending" in p for p in contracts.validate_evaluation(bad, short))
    bad = copy.deepcopy(evaluations[0])
    bad["criterion_scores"][0]["points"] = 5
    assert any(p.startswith("schema") for p in contracts.validate_evaluation(bad, short))
    typed_full = copy.deepcopy(full)
    typed_full["deliverable"]["evidence_mode"] = "typed"
    typed_eval = copy.deepcopy(evaluations[1])
    typed_eval["submission"]["evidence_mode"] = "typed"
    problems = contracts.validate_evaluation(typed_eval, typed_full)
    assert sorted(p.split(":")[0] for p in problems) == ["EE19", "EE20"]  # scored legibility from typed text


def test_evaluation_records_hold_no_student_identity(evaluations):
    validator = contracts.schema_validator("writing-evaluation")
    record = copy.deepcopy(evaluations[0])
    record["student_name"] = "Ana"
    assert list(validator.iter_errors(record))
    record = copy.deepcopy(evaluations[0])
    record["evaluator"]["name"] = "Docente"
    assert list(validator.iter_errors(record))


# ---------------------------------------------------------------- progress (separate from mastery)

def test_progress_per_criterion_and_dimension(evaluations):
    typed = copy.deepcopy(evaluations[1])
    typed.update(evaluation_id="EV-agua-typed-002", evaluated_at="2026-10-26T09:00:00-06:00")
    typed["submission"].update(submission_id="SUB-agua-typed-002", evidence_mode="typed")
    typed["criterion_scores"] = [
        {"criterion": code, "status": "not_evaluable", "not_evaluable_reason": "handwritten_evidence_required"}
        if code in ("EE19", "EE20") else {"criterion": code, "status": "scored", "points": 4 if code == "EE15" else 3}
        for code in ALL]
    summary = progress.summary(evaluations + [typed, {**evaluations[0], "status": "pending"}])
    rows = {r["code"]: r for r in summary["criteria"]}
    assert sorted(rows) == ALL
    assert (rows["EE15"]["evaluations"], rows["EE15"]["latest_points"], rows["EE15"]["best_points"]) == (3, 4, 4)
    assert (rows["EE19"]["evaluations"], rows["EE19"]["latest_points"], rows["EE19"]["not_evaluable"]) == (1, 4, 1)
    assert rows["EE04"]["latest_points"] == 3 and rows["EE04"]["evaluations"] == 3
    dims = {d["ordinal"]: d for d in summary["dimensions"]}
    assert dims[5]["criteria_with_evidence"] == 2 and dims[4]["criteria"] == 12
    assert "no son una calificación oficial" in summary["notice_es"]


def test_progress_with_no_evaluations_lists_every_criterion_unscored():
    summary = progress.summary([])
    assert len(summary["criteria"]) == 20 and all(r["latest_points"] is None for r in summary["criteria"])
    assert all(d["latest_points_ratio"] is None for d in summary["dimensions"])


def test_writing_code_never_touches_practice_or_mastery():
    import re

    for name in ("contracts.py", "progress.py", "store.py"):
        source = (REPO / "app" / "writing" / name).read_text(encoding="utf-8")
        assert not re.search(r"(FROM|JOIN|INTO|UPDATE|TABLE)\s+(practice|curriculum|generation)\.", source), name
        assert not re.search(r"^\s*(from|import)\s+app\.practice", source, flags=re.M), name


# ---------------------------------------------------------------- PostgreSQL storage (test database)

@pytest.fixture()
def store():
    def drop():
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    drop()
    yield WritingStore(TEST_DATABASE_URL)
    drop()


def test_store_round_trip_and_progress(store, exercises, evaluations):
    for exercise in exercises.values():
        store.add_exercise(exercise)
    store.add_submission(evaluations[0]["submission"], "PE-L2-ambiente-intro-001", text_es="Texto de prueba.")
    store.add_submission(evaluations[1]["submission"], "PE-L5-agua-salud-001", handwritten_ref="scan-0001.png")
    for evaluation in evaluations:
        store.add_evaluation(evaluation)
    stored = store.evaluations()
    assert [e["evaluation_id"] for e in stored] == ["EV-ambiente-intro-001", "EV-agua-salud-001"]
    assert progress.summary(stored) == progress.summary(evaluations)
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        assert conn.execute("SELECT COUNT(*) FROM writing.criterion_score").fetchone()[0] == 25


def test_store_rejects_invalid_records_and_inconsistent_rows(store, exercises, evaluations):
    bad = copy.deepcopy(exercises["PE-L2-ambiente-intro-001"])
    bad["target_criteria"].append("EE20")
    with pytest.raises(InvalidRecord):
        store.add_exercise(bad)
    store.add_exercise(exercises["PE-L2-ambiente-intro-001"])
    with pytest.raises(psycopg.errors.CheckViolation):  # typed submissions need their text
        store.add_submission(evaluations[0]["submission"], "PE-L2-ambiente-intro-001")
    store.add_submission(evaluations[0]["submission"], "PE-L2-ambiente-intro-001", text_es="Texto.")
    wrong = copy.deepcopy(evaluations[0])
    wrong["criterion_scores"][3]["points"] = 4
    with pytest.raises(InvalidRecord):
        store.add_evaluation(wrong)
    with psycopg.connect(TEST_DATABASE_URL) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO writing.evaluation VALUES ('EV-x', 'SUB-ambiente-intro-001', 'completed', "
                     "'tutor', 'r', 's', NULL, '{}', '{}')")
