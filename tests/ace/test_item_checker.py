"""Deterministic item checker across all four subjects (question-quality-review)."""

import copy
import json

import pytest

import item_checker
from ace_paths import EXAMPLES, SCRIPTS


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


# ---------------------------------------------------------------- approved baseline (ADR-006)

def baseline_records(records_by_id, **overrides):
    records = copy.deepcopy(records_by_id)
    for rid in ("PNE2025-PRI-MAT-DIAG-B1-A3-E2",):
        records[rid].update({"provenance": "secondary", "baseline_status": "approved",
                             "verification_status": "unverified", **overrides})
    return records


def test_approved_baseline_secondary_record_grounds(item_by_subject, records_by_id, validator):
    result = run(item_by_subject["matematicas"], baseline_records(records_by_id), validator)
    assert result["deterministic_status"] == "pass", result["reasons"]
    g01 = next(c for c in result["checks"] if c["id"] == "G01")
    assert "approved_baseline" in g01["message"]


def test_withdrawn_baseline_record_does_not_ground(item_by_subject, records_by_id, validator):
    records = baseline_records(records_by_id, baseline_status="withdrawn")
    assert {"G01", "G02"} <= failing_ids(run(item_by_subject["matematicas"], records, validator))


def test_rubric_records_never_ground_items(item_by_subject, records_by_id, validator):
    records = baseline_records(records_by_id, assessment_type="written_rubric")
    assert "G01" in failing_ids(run(item_by_subject["matematicas"], records, validator))


def test_item_cannot_claim_official_basis_for_baseline_record(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["grounding_basis"] = "official"
    assert "G01" in failing_ids(run(item, baseline_records(records_by_id), validator))
    item["grounding_basis"] = "approved_baseline"
    assert "G01" not in failing_ids(run(item, baseline_records(records_by_id), validator))


# ---------------------------------------------------------------- comparison items and restated keys (T006)

def comparison_item(item_by_subject, select="min", key="B"):
    item = item_by_subject["matematicas"]
    item["stem"] = "Cuatro atletas registran estos tiempos en segundos. ¿Cuál es el menor tiempo?"
    item["options"] = [{"label": "A", "text": "12,8 s"}, {"label": "B", "text": "12,08 s"},
                       {"label": "C", "text": "12,18 s"}, {"label": "D", "text": "12,81 s"}]
    item["answer_key"] = key
    item["distractor_rationales"] = {l: "Confunde el valor posicional." for l in "ABCD" if l != key}
    item["subject_checks"] = {"math": {"select": select, "unit": "s"}}
    return item


def test_select_min_proves_comparison_key(item_by_subject, records_by_id, validator):
    result = run(comparison_item(item_by_subject), records_by_id, validator)
    assert result["deterministic_status"] == "pass", result["reasons"]
    assert result["math_proven"] is True


def test_select_detects_wrong_comparison_key(item_by_subject, records_by_id, validator):
    result = run(comparison_item(item_by_subject, select="max", key="B"), records_by_id, validator)
    assert "M03" in failing_ids(result)


def test_bare_number_expression_is_rejected(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["subject_checks"] = {"math": {"expression": "12"}}
    assert "M01" in failing_ids(run(item, records_by_id, validator))


def test_expression_and_select_together_are_rejected(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]
    item["subject_checks"] = {"math": {"expression": "144 / 12", "select": "max"}}
    assert "M01" in failing_ids(run(item, records_by_id, validator))


def test_expression_that_restates_key_is_not_a_proof(item_by_subject, records_by_id, validator):
    item = item_by_subject["matematicas"]  # stem mentions 144 and 12; key is 12
    item["subject_checks"] = {"math": {"expression": "1200 / 100"}}
    result = run(item, records_by_id, validator)
    assert result["deterministic_status"] == "pass"
    assert result["math_proven"] is False and result["requires_independent_solve"] is True
    assert any(c["id"] == "M04" and c["status"] == "warn" for c in result["checks"])


def test_expression_from_item_numbers_is_a_proof(item_by_subject, records_by_id, validator):
    result = run(item_by_subject["matematicas"], records_by_id, validator)  # "144 / 12"
    assert result["math_proven"] is True
    assert any(c["id"] == "M04" and c["status"] == "pass" for c in result["checks"])



# ---------------------------------------------------------------- C09 key-length cue (checker 1.4.0)

def c09_status(item_by_subject, records_by_id, validator, key_text, distractors):
    """Set the key's text and the three distractors' texts; return C09's status and the full result."""
    item = copy.deepcopy(item_by_subject["espanol"])
    others = iter(distractors)
    for option in item["options"]:
        option["text"] = key_text if option["label"] == item["answer_key"] else next(others)
    result = run(item, records_by_id, validator)
    return next(c["status"] for c in result["checks"] if c["id"] == "C09"), result


@pytest.mark.parametrize("key_text,distractors", [
    ("Una campaña escolar que promueve el reciclaje en toda la comunidad",
     ["Un paseo al río", "Una feria de ciencias", "Un torneo de fútbol"]),
    ("Porque el agua se evapora con el calor del sol y luego se condensa en nubes",
     ["Porque llueve", "Porque hace frío", "Porque el río crece"]),
])
def test_obvious_key_length_cue_fails(key_text, distractors, item_by_subject, records_by_id, validator):
    status, result = c09_status(item_by_subject, records_by_id, validator, key_text, distractors)
    assert status == "fail"
    assert result["verdict"] == "regenerate"


@pytest.mark.parametrize("key_text,distractors", [
    ("1,405 m", ["1,5 m", "1,45 m", "1,48 m"]),              # ratio 1.4x, gap 1 char
    ("12,5 kg", ["3 kg", "4 kg", "5 kg"]),                    # ratio 3.5x but only 3 chars longer
    ("La campaña de reciclaje escolar", ["El paseo anual de la escuela", "La feria de ciencias", "El torneo"]),
    ("Una campaña de reciclaje en la escuela y el barrio",   # much longer than two distractors, not the longest one
     ["Una feria de ciencias organizada por estudiantes", "Un paseo", "Un torneo"]),
    ("Respuesta", ["Una opción bastante más larga que la clave", "Otra opción larga de relleno", "Una tercera"]),
])
def test_acceptable_length_variation_passes(key_text, distractors, item_by_subject, records_by_id, validator):
    status, _ = c09_status(item_by_subject, records_by_id, validator, key_text, distractors)
    assert status == "pass"


# ---------------------------------------------------------------- L01-L03 linguistic clarity (checker 1.5.0)

def awkward_decimal_item(item_by_subject):
    """The T006 M02 item: announces results it never shows and drops the metre unit."""
    item = copy.deepcopy(item_by_subject["matematicas"])
    item["stimulus"] = {"type": "text", "text": "En la feria de la escuela, cuatro grupos midieron la longitud de "
                                                "sus cintas en metros y obtuvieron los siguientes resultados:"}
    item["stem"] = "¿Cuál de las siguientes longitudes es la mayor?"
    for option, text in zip(item["options"], ["12,35", "12,5", "12,3", "12,05"]):
        option["text"] = text
    item["answer_key"] = "B"
    item["subject_checks"] = {"math": {"select": "max"}}
    return item


def test_t006_awkward_math_item_fails_language_checks(item_by_subject, records_by_id, validator):
    failed = failing_ids(run(awkward_decimal_item(item_by_subject), records_by_id, validator))
    assert {"L01", "L02"} <= failed


def test_announced_data_without_numbers_fails(item_by_subject, records_by_id, validator):
    item = awkward_decimal_item(item_by_subject)
    item["stimulus"]["text"] = "Cuatro grupos midieron sus cintas y anotaron los siguientes resultados."
    item["stem"] = "¿Cuál longitud es la mayor?"
    assert "L01" in failing_ids(run(item, records_by_id, validator))


def test_shown_data_with_units_passes_language_checks(item_by_subject, records_by_id, validator):
    item = awkward_decimal_item(item_by_subject)
    item["stimulus"]["text"] = ("Cuatro grupos midieron sus cintas en metros y obtuvieron los siguientes "
                                "resultados: 12,35 m; 12,5 m; 12,3 m y 12,05 m.")
    for option in item["options"]:
        option["text"] += " m"
    item["subject_checks"]["math"]["unit"] = "m"
    result = run(item, records_by_id, validator)
    assert not {"L01", "L02", "L03"} & failing_ids(result), result["reasons"]


@pytest.mark.parametrize("stem", ["Cuál es la mayor?", "¿Cuál es la mayor", "¿Cuál es la mayor? Explique"])
def test_unpaired_or_incomplete_question_fails(stem, item_by_subject, records_by_id, validator):
    item = copy.deepcopy(item_by_subject["estudios_sociales"])
    item["stem"] = stem
    assert "L03" in failing_ids(run(item, records_by_id, validator))


def test_stem_referring_to_displayed_options_passes_l01(item_by_subject, records_by_id, validator):
    item = awkward_decimal_item(item_by_subject)
    item["stimulus"] = {"type": "none"}
    item["stem"] = "¿Cuál de los siguientes números es el mayor?"
    assert "L01" not in failing_ids(run(item, records_by_id, validator))


def test_property_selection_is_not_proven_by_an_expression(item_by_subject, records_by_id, validator):
    """T007 live item: "3 * 6" evaluates to the key but does not prove "múltiplo de 3 y par"."""
    item = copy.deepcopy(item_by_subject["matematicas"])
    item["stimulus"] = {"type": "text", "text": "En la feria de la escuela, cada puesto tiene un número."}
    item["stem"] = "¿Cuál de los siguientes números de puesto es múltiplo de 3 y a la vez es par?"
    for option, text in zip(item["options"], ["14", "15", "16", "18"]):
        option["text"] = text
    item["answer_key"] = "D"
    item["subject_checks"] = {"math": {"expression": "3 * 6"}}
    result = run(item, records_by_id, validator)
    assert result["math_proven"] is False and result["requires_independent_solve"] is True
    assert any(c["id"] == "M04" and c["status"] == "warn" for c in result["checks"])
