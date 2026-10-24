"""API acceptance on the real baseline PNE2026-SUM-v1.0 (needs the workbook; see curriculum acceptance)."""

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from workbook_fixtures import baseline_workbook, drop_target, new_target

from app.main import create_app
from curriculum import importer

WORKBOOK = baseline_workbook()
pytestmark = pytest.mark.skipif(WORKBOOK is None, reason="baseline workbook not present in references/original/")
V = importer.DEFAULT_VERSION
EXPECTED = {"espanol": 8, "matematicas": 22, "ciencias": 19, "estudios_sociales": 29}


@pytest.fixture(scope="module")
def client():
    target = new_target()
    importer.import_workbook(WORKBOOK, target.url, V, schema=target.schema)
    with TestClient(create_app(target.url, target.schema, V)) as test_client:
        yield test_client
    drop_target(target)


def test_four_subjects_with_78_objectives(client):
    subjects = client.get("/api/subjects").json()["subjects"]
    assert {s["code"]: s["objective_count"] for s in subjects} == EXPECTED
    assert sum(EXPECTED.values()) == 78


def test_every_objective_individually_configurable(client):
    seen = []
    for subject in EXPECTED:
        objectives = client.get("/api/objectives", params={"subject": subject}).json()["objectives"]
        assert not any(o["code"].startswith("EE") for o in objectives)
        for objective in objectives:
            data = client.post("/api/practice/configure", json={
                "subject": subject, "scope": "single_objective", "objective_codes": [objective["code"]],
                "difficulty": "easy", "question_count": 5}).json()
            row = data["allocation"][0]
            assert (row["workbook_code"], row["questions"], row["evidences_total"]) == (
                objective["code"], 5, objective["evidence_count"])
            assert row["text_es"] == objective["text_es"]
            seen.append(objective["code"])
    assert len(seen) == len(set(seen)) == 78


def test_multiple_and_all_objectives(client):
    multi = client.post("/api/practice/configure", json={
        "subject": "matematicas", "scope": "selected_objectives", "objective_codes": ["M07", "M01", "M22"],
        "difficulty": "mixed", "question_count": 10}).json()
    assert {a["workbook_code"]: a["questions"] for a in multi["allocation"]} == {"M01": 4, "M07": 3, "M22": 3}

    for subject, total in EXPECTED.items():
        for n in (5, 10, 20, 30):
            data = client.post("/api/practice/configure", json={
                "subject": subject, "scope": "subject_simulation", "objective_codes": [],
                "difficulty": "mixed", "question_count": n}).json()
            assert data["objectives_selected"] == total
            assert sum(a["questions"] for a in data["allocation"]) == n
            assert len(data["covered_codes"]) == min(n, total)
            assert len(data["covered_codes"]) + len(data["uncovered_codes"]) == total
            per = Counter(a["questions"] for a in data["allocation"])
            assert max(per) - min(per) <= 1  # balanced


def test_evidence_ids_belong_to_their_objective(client):
    data = client.post("/api/practice/configure", json={
        "subject": "ciencias", "scope": "subject_simulation", "objective_codes": [],
        "difficulty": "hard", "question_count": 30}).json()
    for row in data["allocation"]:
        catalog_id_prefix = row["slots"][0]["evidence_id"].rsplit("-E", 1)[0]
        assert all(s["evidence_id"].startswith(catalog_id_prefix + "-E") for s in row["slots"])


def test_dashboard_covers_all_78_objectives_with_six_statuses(client):
    data = client.get("/api/dashboard").json()
    assert {s["subject"]: s["objective_count"] for s in data["subjects"]} == EXPECTED
    assert [s["code"] for s in data["statuses"]] == ["unpracticed", "insufficient_evidence", "needs_reinforcement",
                                                       "in_progress", "good_proficiency", "consolidated_mastery"]
    for subject in data["subjects"]:
        assert set(subject["status_counts"]) == {s["code"] for s in data["statuses"]}
        assert sum(subject["status_counts"].values()) == subject["objective_count"]
