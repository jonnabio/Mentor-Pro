"""Tutor evaluation of writing submissions (T026, ADR-024): boundary, workflow, integrity, student feedback."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.writing import contracts
from app.writing.store import WritingStore
from conftest import SYNTHETIC

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "scripts" / "dev" / "fixtures"
TOKEN = "tutor-test-token-0123456789"
L1 = json.loads((FIXTURES / "writing-exercises-L1-T023.json").read_text(encoding="utf-8"))[0]  # fútbol, EE07+EE08
L23 = {r["exercise_type"]: r for r in json.loads((FIXTURES / "writing-exercises-L2L3-T025.json").read_text(
    encoding="utf-8"))}
REFERENCE = {"corrected_text_es": "REFERENCIA-SOLO-TUTOR: Los entrenadores voluntarios enseñan.",
             "corrections": [{"error": "las niños", "correction": "los niños", "criterion": "EE07"}],
             "ambiguities_es": ["Alternativa aceptada de prueba."]}
HEADERS = {"X-Tutor-Token": TOKEN}


@pytest.fixture()
def env(synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    store = WritingStore(url)
    store.add_exercise(L1, reference=REFERENCE)
    for record in L23.values():
        store.add_exercise(record)
    student = TestClient(create_app(url, schema, SYNTHETIC, tutor_token=TOKEN, tutor_hosts=frozenset({"testclient"})))
    yield student, store, url
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")


def submit(student, exercise_id, text="Texto corregido por el estudiante."):
    student.post(f"/api/writing/exercises/{exercise_id}/submit",
                 json={"text": text, "client_request_id": str(uuid.uuid4())})
    return student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"]


def sid_for(queue, exercise_id):
    return next(s["submission_id"] for s in queue if s["exercise_id"] == exercise_id)


# ---------------------------------------------------------------- boundary

def test_tutor_routes_do_not_exist_without_a_token(synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    app = TestClient(create_app(url, schema, SYNTHETIC, tutor_token=""))
    assert app.get("/api/tutor/queue", headers=HEADERS).status_code == 404
    assert app.get("/tutor").status_code == 404


def test_tutor_requires_token_and_local_address(env, synthetic_client):
    student, _, _ = env
    assert student.get("/api/tutor/queue").status_code == 403
    assert student.get("/api/tutor/queue", headers={"X-Tutor-Token": "wrong-token-0123456789"}).status_code == 403
    assert student.get("/api/tutor/queue", headers=HEADERS).status_code == 200
    url, schema = synthetic_client.app.state.catalog_target
    remote = TestClient(create_app(url, schema, SYNTHETIC, tutor_token=TOKEN))  # default: loopback only
    assert remote.get("/api/tutor/queue", headers=HEADERS).status_code == 403
    with pytest.raises(ValueError):
        create_app(url, schema, SYNTHETIC, tutor_token="short")
    assert student.get("/tutor").status_code == 200 and "Revisión del tutor" in student.get("/tutor").text
    assert "/tutor" not in student.get("/").text and "/api/tutor" not in student.get("/static/app.js").text


# ---------------------------------------------------------------- L1 workflow

def test_l1_evaluation_workflow(env):
    student, store, url = env
    eid = L1["exercise_id"]
    queue = submit(student, eid, L1["source_text_es"].replace("las niños", "los niños"))
    sid = sid_for(queue, eid)
    item = next(s for s in queue if s["submission_id"] == sid)
    assert item["status"] == "pending" and item["target_criteria"] == ["EE07", "EE08"]
    assert item["title_es"] == "El fútbol en mi comunidad" and item["level_es"].startswith("Nivel 1")

    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert detail["reference"]["corrected_text_es"] == REFERENCE["corrected_text_es"]
    assert detail["exercise"]["source_text_es"] == L1["source_text_es"] and "los niños" in detail["student_text"]
    for c in detail["criteria"]:
        official = contracts.criteria()[c["code"]]
        assert c["statement_es"] == official["statement_es"] and c["descriptors_es"] == official["descriptors_es"]
        assert c["applicability"] == "scored"

    partial = {"scores": {"EE07": 3}, "strengths": ["Corregiste la concordancia de «los niños»."]}
    assert student.put(f"/api/tutor/submissions/{sid}/evaluation", json=partial, headers=HEADERS).json()["status"] \
        == "in_progress"
    resumed = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()["evaluation"]
    assert resumed["status"] == "in_progress"
    assert {s["criterion"]: s.get("points") for s in resumed["record"]["criterion_scores"]} == {"EE07": 3, "EE08": None}
    assert student.get(f"/api/writing/exercises/{eid}").json()["feedback"] is None  # not yet visible

    incomplete = student.put(f"/api/tutor/submissions/{sid}/evaluation", json={**partial, "complete": True},
                             headers=HEADERS)
    assert incomplete.status_code == 422 and incomplete.json()["error"] == "incomplete"
    final = {"scores": {"EE07": 3, "EE08": 2}, "strengths": ["Corregiste la concordancia de «los niños»."],
             "improvements": ["Revisá la concordancia entre sujeto y verbo en «se reúne»."],
             "next_step": "Practicá otro texto de concordancia.", "complete": True}
    done = student.put(f"/api/tutor/submissions/{sid}/evaluation", json=final, headers=HEADERS)
    assert done.status_code == 200 and done.json()["status"] == "completed" and done.json()["evaluated_at"]
    again = student.put(f"/api/tutor/submissions/{sid}/evaluation", json=final, headers=HEADERS)
    assert again.status_code == 409 and again.json()["error"] == "evaluation_completed"
    assert student.put(f"/api/tutor/submissions/{sid}/evaluation", json=partial, headers=HEADERS).status_code == 409

    with psycopg.connect(url) as conn:
        rows = conn.execute("""SELECT v.status, v.exercise_revision, v.rubric_id, v.rubric_sha256, c.criterion_code,
                                      c.points, c.descriptor_ref FROM writing.evaluation v
                               JOIN writing.criterion_score c USING (evaluation_id) ORDER BY c.criterion_code""").fetchall()
        sub = conn.execute("SELECT text_es, exercise_revision FROM writing.submission").fetchone()
    assert [(r[4], r[5], r[6]) for r in rows] == [("EE07", 3, "MEP-RUBRICA-PE-2026#EE07@3"),
                                                  ("EE08", 2, "MEP-RUBRICA-PE-2026#EE08@2")]
    assert {r[0] for r in rows} == {"completed"} and {r[1] for r in rows} == {1}
    assert rows[0][3] == contracts.rubric()["source"]["file_sha256"]
    assert "los niños" in sub[0] and sub[1] == 1  # the submission itself is unchanged

    view = student.get(f"/api/writing/exercises/{eid}")
    data = view.json()
    assert data["submission"]["status_es"] == "Revisado por el tutor"
    fb = data["feedback"]
    assert [(s["points"], s["max_points"]) for s in fb["scores"]] == [(3, 4), (2, 4)]
    assert fb["scores"][0]["descriptor_es"] == contracts.descriptor("EE07", 3)
    assert fb["improvements_es"] == final["improvements"] and fb["next_step_es"] == final["next_step"]
    for body in (view.text, student.get("/api/writing/levels/writing_conventions/exercises").text):
        assert "REFERENCIA-SOLO-TUTOR" not in body and "Alternativa aceptada" not in body and "corrections" not in body
    queue = student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"]
    assert next(s for s in queue if s["submission_id"] == sid)["status"] == "completed"


# ---------------------------------------------------------------- L2 / L3 and handwriting

@pytest.mark.parametrize("kind", ["introduction_paragraph", "development_paragraphs", "conclusion_paragraph"])
def test_l2_and_l3_evaluation(env, kind):
    student, _, _ = env
    record = L23[kind]
    sid = sid_for(submit(student, record["exercise_id"], "Mi párrafo.\n\nOtro párrafo."), record["exercise_id"])
    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert detail["reference"] is None and [c["code"] for c in detail["criteria"]] == record["target_criteria"]
    scores = {code: 2 for code in record["target_criteria"]}
    done = student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": scores, "complete": True,
                       "improvements": ["Agregá una segunda idea complementaria."]}, headers=HEADERS)
    assert done.json()["status"] == "completed"
    fb = student.get(f"/api/writing/exercises/{record['exercise_id']}").json()["feedback"]
    assert [s["points"] for s in fb["scores"]] == [2] * len(scores)


def test_typed_submission_gets_no_handwriting_score(env):
    student, store, _ = env
    guided = copy.deepcopy(L23["introduction_paragraph"])
    codes = ["EE01", "EE02", "EE03", "EE04", "EE05", "EE06", "EE19"]
    guided.update(exercise_id="PE-L4-guiada-prueba-0001", level="guided_composition", exercise_type="guided_composition",
                  target_criteria=codes)
    guided["deliverable"].update(unit="paragraphs", min=4, max=4, words_target=200, evidence_mode="typed")
    guided["evaluation"]["parameters"] = [
        {"criterion": c, "rubric_ref": f"MEP-RUBRICA-PE-2026#{c}", "applicability": "scored"} if c != "EE19" else
        {"criterion": c, "rubric_ref": f"MEP-RUBRICA-PE-2026#{c}", "applicability": "not_evaluable",
         "not_evaluable_reason": "handwritten_evidence_required"} for c in codes]
    rubric = contracts.criteria()
    guided["provenance"]["curriculum_records"] = [
        {"workbook_code": c, "assertion_id": f"PNE2026-PRI-ESP-PE-B{rubric[c]['dimension']}-A{rubric[c]['rubric_number']}"}
        for c in codes]
    assert contracts.validate_exercise(guided) == []
    store.add_exercise(guided)
    sid = sid_for(submit(student, guided["exercise_id"]), guided["exercise_id"])
    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert next(c for c in detail["criteria"] if c["code"] == "EE19")["applicability"] == "not_evaluable"
    scores = {c: 3 for c in codes if c != "EE19"}
    refused = student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": {**scores, "EE19": 4},
                          "complete": True}, headers=HEADERS)
    assert refused.status_code == 422 and refused.json()["error"] == "handwriting_not_evaluable"
    done = student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": scores, "complete": True},
                       headers=HEADERS)
    assert done.json()["status"] == "completed"
    record = store.evaluation_for(sid)["record"]
    ee19 = next(s for s in record["criterion_scores"] if s["criterion"] == "EE19")
    assert ee19 == {"criterion": "EE19", "status": "not_evaluable", "not_evaluable_reason": "handwritten_evidence_required"}
    fb = student.get(f"/api/writing/exercises/{guided['exercise_id']}").json()["feedback"]
    assert next(s for s in fb["scores"] if s["status"] == "not_evaluable")["note_es"].startswith("No evaluable")


def test_invalid_scores_are_refused(env):
    student, _, _ = env
    sid = sid_for(submit(student, L1["exercise_id"]), L1["exercise_id"])
    url = f"/api/tutor/submissions/{sid}/evaluation"
    assert student.put(url, json={"scores": {"EE07": 5}}, headers=HEADERS).status_code == 422
    assert student.put(url, json={"scores": {"EE16": 2}}, headers=HEADERS).json()["error"] == "unknown_criteria"
    assert student.get("/api/tutor/submissions/SUB-nope", headers=HEADERS).status_code == 404
