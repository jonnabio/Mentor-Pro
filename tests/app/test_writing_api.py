"""Producción escrita student API (T022): levels, exercises, drafts and one submission per exercise."""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.writing.store import WritingStore
from conftest import SYNTHETIC

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / ".ace" / "schemas" / "writing" / "examples"
GENERATED = REPO / "scripts" / "dev" / "fixtures" / "writing-exercise-T021.json"
HEALTHY = "PE-L2-alimentacion-saludable-rendimiento-19a72a"
FULL = "PE-L5-agua-salud-001"


@pytest.fixture()
def client(synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    store = WritingStore(url)
    for exercise in json.loads((EXAMPLES / "exercises.json").read_text(encoding="utf-8")):
        store.add_exercise(exercise)
    store.add_exercise(json.loads(GENERATED.read_text(encoding="utf-8")), generation_request_id="wreq-fixture")
    yield TestClient(create_app(url, schema, SYNTHETIC)), url
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")


def rows(url, sql, *args):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, args or None).fetchall()


def test_five_levels_with_counts_and_empty_levels(client):
    api, _ = client
    levels = api.get("/api/writing/levels").json()
    assert levels["component_es"] == "Producción escrita" and levels["subject_es"] == "Español"
    assert [(lv["label_es"], lv["exercise_count"]) for lv in levels["levels"]] == [
        ("Nivel 1: Convenciones de escritura", 0), ("Nivel 2: Desarrollo de ideas", 2),
        ("Nivel 3: Redacción de párrafos", 0), ("Nivel 4: Composición guiada", 0),
        ("Nivel 5: Composición expositiva completa", 1)]
    assert [lv["handwritten"] for lv in levels["levels"]] == [False, False, False, False, True]
    assert api.get("/api/writing/levels/paragraph_writing/exercises").json()["exercises"] == []
    l2 = api.get("/api/writing/levels/idea_development/exercises").json()["exercises"]
    assert {e["exercise_id"] for e in l2} >= {HEALTHY} and {e["state"] for e in l2} == {"new"}
    assert api.get("/api/writing/levels/xyz/exercises").status_code == 404


def test_exercise_view_hides_rubric_content(client):
    api, _ = client
    data = api.get(f"/api/writing/exercises/{HEALTHY}").json()
    assert data["topic_es"] == "La alimentación saludable y el rendimiento escolar"
    assert len(data["instructions_es"]) == 5 and data["communicative_situation_es"].startswith("Vos formás")
    assert data["deliverable"]["requirements_es"] == ["1 párrafo", "Escrito en la computadora"]
    assert data["handwritten"] is False and data["draft"] is None and data["submission"] is None
    text = json.dumps(data, ensure_ascii=False)
    for leaked in ("EE0", "rubric", "evaluation", "descriptor", "El texto evidencia", "puntos", "target_criteria"):
        assert leaked not in text, leaked
    assert api.get("/api/writing/exercises/PE-L2-nope-000").status_code == 404
    assert api.get("/api/writing/exercises/bad id").status_code == 422


def test_draft_is_saved_resumed_and_counted(client):
    api, url = client
    text = "La alimentación saludable ayuda a aprender.\n\nAdemás, da energía para jugar."
    saved = api.put(f"/api/writing/exercises/{HEALTHY}/draft", json={"text": text}).json()
    assert saved["word_count"] == 11
    again = api.put(f"/api/writing/exercises/{HEALTHY}/draft", json={"text": text + " Fin."}).json()
    assert again["word_count"] == 12
    data = api.get(f"/api/writing/exercises/{HEALTHY}").json()
    assert data["draft"]["text"] == text + " Fin." and data["draft"]["word_count"] == 12
    assert rows(url, "SELECT COUNT(*) FROM writing.draft")[0][0] == 1
    states = {e["exercise_id"]: e["state"] for e in
              api.get("/api/writing/levels/idea_development/exercises").json()["exercises"]}
    assert states[HEALTHY] == "draft"


def test_one_submission_per_exercise_then_pending_review(client):
    api, url = client
    text = "Una buena alimentación mejora la concentración. Además, ayuda a la memoria y a la convivencia."
    body = {"text": text, "client_request_id": str(uuid.uuid4())}
    first = api.post(f"/api/writing/exercises/{HEALTHY}/submit", json=body).json()
    assert first["created"] is True and first["status_es"] == "Pendiente de revisión del tutor"
    second = api.post(f"/api/writing/exercises/{HEALTHY}/submit",
                      json={"text": "otro texto", "client_request_id": str(uuid.uuid4())}).json()
    assert second["created"] is False and second["submitted_at"] == first["submitted_at"]
    [sub] = rows(url, "SELECT evidence_mode, text_es, word_count, paragraph_count FROM writing.submission")
    assert sub == ("typed", text, 15, 1)
    assert rows(url, "SELECT COUNT(*) FROM writing.evaluation")[0][0] == 0  # no automatic grading
    late = api.put(f"/api/writing/exercises/{HEALTHY}/draft", json={"text": "cambio"})
    assert late.status_code == 409 and "ya fue entregado" in late.json()["message_es"]
    view = api.get(f"/api/writing/exercises/{HEALTHY}").json()
    assert view["submission"]["status"] == "pending_review" and view["draft"]["text"] == text


def test_parallel_submissions_store_one(client):
    api, url = client
    results = []

    def submit():
        results.append(api.post(f"/api/writing/exercises/{HEALTHY}/submit",
                                json={"text": "Texto final.", "client_request_id": str(uuid.uuid4())}).json())

    threads = [threading.Thread(target=submit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r["created"] for r in results) == 1
    assert rows(url, "SELECT COUNT(*) FROM writing.submission")[0][0] == 1


def test_empty_and_invalid_submissions_are_refused(client):
    api, _ = client
    empty = api.post(f"/api/writing/exercises/{HEALTHY}/submit", json={"text": "   ", "client_request_id": "abcdefgh"})
    assert empty.status_code == 422
    assert api.post(f"/api/writing/exercises/{HEALTHY}/submit", json={"text": "x", "client_request_id": "x"}
                    ).status_code == 422


def test_handwritten_exercise_shows_conditions_and_takes_no_typed_text(client):
    api, url = client
    data = api.get(f"/api/writing/exercises/{FULL}").json()
    assert data["handwritten"] is True and "bolígrafo" in data["handwritten_es"] and "a mano" in data["handwritten_es"]
    assert data["deliverable"]["requirements_es"] == ["4 párrafos", "Al menos 200 palabras", "Tiempo: 90 minutos",
                                                      "Escrito a mano",
                                                      "Hoja de respuesta y bolígrafo de tinta azul o negra."]
    for call in (api.put(f"/api/writing/exercises/{FULL}/draft", json={"text": "hola"}),
                 api.post(f"/api/writing/exercises/{FULL}/submit", json={"text": "hola", "client_request_id": "abcdefgh"})):
        assert call.status_code == 409 and call.json()["error"] == "handwritten_only"
    assert rows(url, "SELECT COUNT(*) FROM writing.submission")[0][0] == 0


def test_multiple_choice_dashboard_is_unaffected(client):
    api, _ = client
    before = api.get("/api/dashboard").json()
    api.put(f"/api/writing/exercises/{HEALTHY}/draft", json={"text": "uno dos"})
    api.post(f"/api/writing/exercises/{HEALTHY}/submit", json={"text": "uno dos", "client_request_id": "abcdefgh"})
    after = api.get("/api/dashboard").json()
    assert before == after
    assert [s["code"] for s in api.get("/api/subjects").json()["subjects"]] == [
        "espanol", "matematicas", "ciencias", "estudios_sociales"]
