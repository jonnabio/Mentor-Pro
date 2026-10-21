"""Deterministic item checker across all four subjects (question-quality-review)."""

import copy
import json

import pytest

import item_checker
from conftest import EXAMPLES, SCRIPTS


def failing_ids(result: dict) -> set[str]:
    return {c["id"] for c in result["checks"] if c["status"] == "fail"}


def run(item, records, validator, **kwargs):
    return item_checker.check_item(item, records, validator=validator, **kwargs)


# ---------------------------------------------------------------- valid examples

def test_valid_examples_pass(valid_items, records_by_id, validator):
    for item in valid_items:
        result = run(item, records_by_id, validator)
        assert result["deterministic_status"] == "pass", (item["item_id"], result["reasons"])
        assert result["verdict"] == "pending"


def test_only_math_items_are_proven(item_by_subject, records_by_id, validator):
    math = run(item_by_subject["matematicas"], records_by_id, validator)
    reading = run(item_by_subject["espanol"], records_by_id, validator)
    assert math["math_proven"] is True and math["requires_independent_solve"] is False
    assert reading["math_proven"] is False and reading["requires_independent_solve"] is True


def test_ciencias_uses_fact_checks(item_by_subject, records_by_id, validator):
    item = copy.deepcopy(item_by_subject["estudios_sociales"])
    item["subject"] = "ciencias"
    result = run(item, records_by_id, validator)
    # Subject no longer matches the evidencia, and fact checks still run.
    assert "G01" in failing_ids(result)
    assert any(c["id"] == "F01" for c in result["checks"])


# ---------------------------------------------------------------- common failures

def test_wrong_math_key_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["answer_key"] = "A"
    item["distractor_rationales"] = {"B": "x x x", "C": "x x x", "D": "x x x"}
    result = run(item, records_by_id, validator)
    assert "M03" in failing_ids(result)
    assert result["verdict"] == "regenerate"


def test_grounding_failure_is_rejected_not_regenerated(item_by_subject, records_by_id, validator):
    item = item_by_subject["espanol"]
    item["source_refs"][0]["excerpt"] = "Texto inventado."
    assert run(item, records_by_id, validator)["verdict"] == "reject"


def test_two_options_with_equal_value_fail(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["options"][2]["text"] = "12,0"
    assert "M02" in failing_ids(run(item, records_by_id, validator))


def test_ambiguous_number_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["options"][3]["text"] = "1.000"
    assert "M02" in failing_ids(run(item, records_by_id, validator))


def test_math_without_expression_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    del item["subject_checks"]
    assert "M01" in failing_ids(run(item, records_by_id, validator))


def test_banned_option_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["options"][3]["text"] = "Todas las anteriores"
    assert "C05" in failing_ids(run(item, records_by_id, validator))


def test_duplicate_options_fail(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["options"][1]["text"] = "el escudo"
    assert "C04" in failing_ids(run(item, records_by_id, validator))


def test_key_without_option_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["options"] = item["options"][:3]
    item["answer_key"] = "D"
    assert "C03" in failing_ids(run(item, records_by_id, validator))


def test_option_count_is_enforced(item_by_subject, records_by_id, validator):
    result = run(item_by_subject["estudios_sociales"], records_by_id, validator, option_count=5)
    assert "C02" in failing_ids(result)


def test_missing_distractor_rationale_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    del item["distractor_rationales"]["A"]
    assert "C06" in failing_ids(run(item, records_by_id, validator))


def test_stem_referring_to_missing_image_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["stem"] = "Observe la imagen. ¿Cuál símbolo nacional se representa?"
    assert "C08" in failing_ids(run(item, records_by_id, validator))


def test_image_stimulus_without_assets_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["stimulus"] = {"type": "image"}
    assert "C08" in failing_ids(run(item, records_by_id, validator))


def test_schema_violation_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["espanol"]
    item["difficulty"] = "mixed"
    assert "C01" in failing_ids(run(item, records_by_id, validator))


# ---------------------------------------------------------------- grounding

def test_paraphrased_excerpt_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["espanol"]
    item["source_refs"][0]["excerpt"] = "Identifica la idea principal de un texto."
    assert "G02" in failing_ids(run(item, records_by_id, validator))


def test_unknown_evidencia_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["curriculum_ref"]["evidencia_id"] = "PNE2025-PRI-MAT-DIAG-B1-A3-E9"
    assert "G01" in failing_ids(run(item, records_by_id, validator))


def test_secondary_source_fails(item_by_subject, records_by_id, validator):
    records = copy.deepcopy(records_by_id)
    records["PNE2025-PRI-MAT-DIAG-B1-A3-E2"]["provenance"] = "secondary"
    result = run(item_by_subject["matematicas"], records, validator)
    assert {"G01", "G02"} <= failing_ids(result)


def test_application_mismatch_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["curriculum_ref"]["application"] = "sumativa"
    assert "G01" in failing_ids(run(item, records_by_id, validator))


# ---------------------------------------------------------------- subject-specific

def test_reading_item_needs_passage(item_by_subject, records_by_id, validator):
    item = item_by_subject["espanol"]
    item["stimulus"] = {"type": "none"}
    item["stem"] = "¿Cuál es la idea fundamental?"
    assert "R01" in failing_ids(run(item, records_by_id, validator))


def test_reading_key_support_must_be_verbatim(item_by_subject, records_by_id, validator):
    item = item_by_subject["espanol"]
    item["subject_checks"]["reading"]["key_support_span"] = "las playas deben cuidarse"
    assert "R03" in failing_ids(run(item, records_by_id, validator))


def test_fact_terms_must_be_grounded(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["subject_checks"]["facts"]["support_terms"] = ["Guaria Morada"]
    assert "F01" in failing_ids(run(item, records_by_id, validator))


def test_reviewed_facts_can_ground_terms(item_by_subject, records_by_id, validator):
    item = item_by_subject["estudios_sociales"]
    item["subject_checks"]["facts"]["support_terms"] = ["música y letra"]
    ungrounded = run(item, records_by_id, validator)
    grounded = run(item, records_by_id, validator, facts=["El Himno Nacional tiene música y letra."])
    assert "F01" in failing_ids(ungrounded)
    assert "F01" not in failing_ids(grounded)


# ---------------------------------------------------------------- duplicates

def test_exact_duplicate_in_bank_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    twin = copy.deepcopy(item)
    twin["item_id"] = item["item_id"][:-8] + "00000000"
    assert "D01" in failing_ids(run(item, records_by_id, validator, bank=[twin]))


def test_near_duplicate_in_bank_fails(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    twin = copy.deepcopy(item)
    twin["item_id"] = item["item_id"][:-8] + "00000000"
    twin["stem"] = twin["stem"].replace("¿Cuántos grupos se forman?", "¿Cuántos grupos se pueden formar?")
    assert "D01" in failing_ids(run(item, records_by_id, validator, bank=[twin]))


# ---------------------------------------------------------------- CLI

def test_cli_exit_codes(tmp_path, valid_items, capsys):
    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps(valid_items, ensure_ascii=False), encoding="utf-8")
    records = str(EXAMPLES / "curriculum-records.json")
    assert item_checker.main([str(items_file), "--records", records]) == 0
    output = json.loads(capsys.readouterr().out)
    assert len(output) == 3

    valid_items[0]["answer_key"] = "C"
    items_file.write_text(json.dumps(valid_items, ensure_ascii=False), encoding="utf-8")
    assert item_checker.main([str(items_file), "--records", records]) == 1
    capsys.readouterr()

    assert item_checker.main([str(tmp_path / "missing.json"), "--records", records]) == 2


def test_cli_detects_sibling_duplicates(tmp_path, valid_items, capsys):
    twin = copy.deepcopy(valid_items[0])
    twin["item_id"] = twin["item_id"][:-8] + "00000000"
    items_file = tmp_path / "items.json"
    items_file.write_text(json.dumps([valid_items[0], twin], ensure_ascii=False), encoding="utf-8")
    code = item_checker.main([str(items_file), "--records", str(EXAMPLES / "curriculum-records.json")])
    output = json.loads(capsys.readouterr().out)
    assert code == 1
    assert "D01" in failing_ids(output[1])


def test_checker_scripts_are_in_skill_folder():
    assert (SCRIPTS / "item_checker.py").is_file() and (SCRIPTS / "cr_math.py").is_file()


@pytest.mark.parametrize("subject", ["espanol", "matematicas", "ciencias", "estudios_sociales"])
def test_every_subject_has_subject_checks(subject, item_by_subject, records_by_id, validator):
    base = item_by_subject["estudios_sociales" if subject == "ciencias" else subject]
    item = copy.deepcopy(base)
    item["subject"] = subject
    ids = {c["id"][0] for c in run(item, records_by_id, validator)["checks"]}
    expected = {"espanol": "R", "matematicas": "M", "ciencias": "F", "estudios_sociales": "F"}[subject]
    assert expected in ids
