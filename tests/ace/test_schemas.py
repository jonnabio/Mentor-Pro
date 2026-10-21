"""Example data validates against the question-engine JSON Schemas."""

import json

import jsonschema
import pytest

from conftest import EXAMPLES, SCHEMAS, load

CASES = [
    ("curriculum-record.schema.json", "curriculum-records.json"),
    ("question-item.schema.json", "items-valid.json"),
    ("validation-result.schema.json", "validation-result.json"),
    ("coverage-plan.schema.json", "coverage-plan.json"),
    ("llm-usage-record.schema.json", "llm-usage-records.json"),
]


def validator_for(schema_name: str) -> jsonschema.Draft202012Validator:
    schema = load(SCHEMAS / schema_name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


@pytest.mark.parametrize(("schema_name", "example_name"), CASES)
def test_examples_are_valid(schema_name, example_name):
    validator = validator_for(schema_name)
    data = load(EXAMPLES / example_name)
    for instance in data if isinstance(data, list) else [data]:
        errors = list(validator.iter_errors(instance))
        assert not errors, [e.message for e in errors]


def test_every_schema_has_an_example():
    schemas = {p.name for p in SCHEMAS.glob("*.schema.json")}
    assert schemas == {s for s, _ in CASES}


def test_usage_record_rejects_student_fields():
    validator = validator_for("llm-usage-record.schema.json")
    record = load(EXAMPLES / "llm-usage-records.json")[0]
    record["student_name"] = "Ana"
    assert list(validator.iter_errors(record))


def test_curriculum_record_rejects_bad_ids_and_checksums():
    validator = validator_for("curriculum-record.schema.json")
    record = load(EXAMPLES / "curriculum-records.json")[2]
    bad_id = dict(record, record_id="PNE2025-PRI-MAT-B1-A3-E2")
    bad_sum = json.loads(json.dumps(record))
    bad_sum["source"]["file_sha256"] = "abc"
    assert list(validator.iter_errors(bad_id))
    assert list(validator.iter_errors(bad_sum))


def test_item_difficulty_cannot_be_mixed_but_request_can():
    item_validator = validator_for("question-item.schema.json")
    plan_validator = validator_for("coverage-plan.schema.json")
    item = load(EXAMPLES / "items-valid.json")[0]
    item["difficulty"] = "mixed"
    assert list(item_validator.iter_errors(item))
    assert not list(plan_validator.iter_errors(load(EXAMPLES / "coverage-plan.json")))


def test_example_records_match_manifest_checksum():
    from conftest import REPO_ROOT

    manifest = (REPO_ROOT / "references" / "MANIFEST.sha256").read_text(encoding="utf-8")
    for record in load(EXAMPLES / "curriculum-records.json"):
        assert f"{record['source']['file_sha256']} *{record['source']['file_name']}" in manifest
