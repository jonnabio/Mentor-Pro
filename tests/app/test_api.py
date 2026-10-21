"""API behaviour on the synthetic baseline: endpoints, validation, Spanish errors."""

import pytest


def configure(client, **overrides):
    payload = {"subject": "matematicas", "scope": "single_objective", "objective_codes": ["M01"],
               "difficulty": "medium", "question_count": 10, **overrides}
    return client.post("/api/practice/configure", json=payload)


def test_subjects(synthetic_client):
    data = synthetic_client.get("/api/subjects").json()
    assert [s["name_es"] for s in data["subjects"]] == ["Español", "Matemáticas", "Ciencias", "Estudios Sociales"]
    counts = {s["code"]: s["objective_count"] for s in data["subjects"]}
    assert counts == {"espanol": 1, "matematicas": 3, "ciencias": 0, "estudios_sociales": 0}
    assert "No es material oficial del MEP" in data["notice_es"]


def test_objectives_exclude_rubric_and_keep_text(synthetic_client):
    data = synthetic_client.get("/api/objectives", params={"subject": "espanol"}).json()
    assert [o["code"] for o in data["objectives"]] == ["EL01"]
    assert data["objectives"][0]["text_es"] == "Distingue las ideas fundamentales en textos no literarios."
    maths = synthetic_client.get("/api/objectives", params={"subject": "matematicas"}).json()["objectives"]
    assert [(o["code"], o["evidence_count"]) for o in maths] == [("M01", 2), ("M02", 1), ("M03", 1)]


@pytest.mark.parametrize("params", [{"subject": "historia"}, {}])
def test_objectives_reject_bad_subject(synthetic_client, params):
    response = synthetic_client.get("/api/objectives", params=params)
    assert response.status_code == 422 and response.json()["message_es"]


def test_single_objective(synthetic_client):
    data = configure(synthetic_client).json()
    assert data["covered_codes"] == ["M01"]
    assert data["allocation"][0]["questions"] == 10
    assert data["allocation"][0]["evidences_total"] == 2
    assert data["allocation"][0]["text_es"] == "Resuelve problemas con números naturales."


def test_selected_objectives_including_identical_texts(synthetic_client):
    data = configure(synthetic_client, scope="selected_objectives", objective_codes=["M03", "M02"],
                     question_count=5).json()
    assert {a["workbook_code"]: a["questions"] for a in data["allocation"]} == {"M02": 3, "M03": 2}


def test_all_objectives(synthetic_client):
    data = configure(synthetic_client, scope="subject_simulation", objective_codes=[], difficulty="mixed",
                     question_count=20).json()
    assert data["objectives_selected"] == 3
    assert sum(a["questions"] for a in data["allocation"]) == 20


def test_configuration_is_deterministic(synthetic_client):
    first = configure(synthetic_client, scope="subject_simulation", objective_codes=[], difficulty="mixed").json()
    second = configure(synthetic_client, scope="subject_simulation", objective_codes=[], difficulty="mixed").json()
    assert first == second


@pytest.mark.parametrize(("overrides", "error"), [
    ({"objective_codes": []}, "no_objectives"),
    ({"objective_codes": ["M01", "M02"]}, "invalid_selection"),
    ({"scope": "selected_objectives", "objective_codes": ["M01"]}, "invalid_selection"),
    ({"scope": "selected_objectives", "objective_codes": ["M01", "M01"]}, "invalid_selection"),
    ({"objective_codes": ["EL01"]}, "invalid_selection"),
    ({"objective_codes": ["M99"]}, "invalid_selection"),
    ({"subject": "espanol", "objective_codes": ["EE01"]}, "invalid_selection"),
    ({"subject": "historia"}, "unknown_subject"),
    ({"difficulty": "extreme"}, "invalid_request"),
    ({"question_count": 15}, "invalid_request"),
    ({"question_count": "10"}, "invalid_request"),
    ({"scope": "everything"}, "invalid_request"),
    ({"subject": "ciencias", "scope": "subject_simulation", "objective_codes": []}, "invalid_selection"),
])
def test_invalid_configurations_are_rejected(synthetic_client, overrides, error):
    response = configure(synthetic_client, **overrides)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == error
    assert body["message_es"]


def test_rubric_rejection_message_is_spanish(synthetic_client):
    body = configure(synthetic_client, subject="espanol", objective_codes=["EE01"]).json()
    assert body["message_es"] == "Los criterios de producción escrita no se practican con preguntas de selección."


def test_ui_is_served(synthetic_client):
    page = synthetic_client.get("/")
    assert page.status_code == 200 and 'lang="es-CR"' in page.text and "Generar práctica" in page.text
    for asset in ("/static/app.js", "/static/styles.css"):
        assert synthetic_client.get(asset).status_code == 200
