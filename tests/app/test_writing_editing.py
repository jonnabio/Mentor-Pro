"""Nivel 1 correction exercises (T023, ADR-022): generation checks, tutor-only reference, seeding, student API."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.llm.client import OpenRouterClient
from app.llm.settings import LlmSettings
from app.llm.usage import MemoryUsageStore
from app.main import create_app
from app.writing import contracts, editing, seeding
from app.writing.store import WritingStore
from curriculum import db, importer

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "curriculum"))
from workbook_fixtures import TEST_DATABASE_URL, baseline_workbook, drop_target, new_target  # noqa: E402

WORKBOOK = baseline_workbook()
pytestmark = pytest.mark.skipif(WORKBOOK is None, reason="baseline workbook not present in references/original/")
KEY = "sk-or-v1-test-key-not-real"
MODELS = {"data": [
    {"id": "gen/a:free", "context_length": 100000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "rev/b:free", "context_length": 50000, "pricing": {"prompt": "0", "completion": "0"}},
]}
SOURCE = ("Cada año, los estudiantes de sexto grado organizan una feria de reciclaje en la escuela. Ese día, las "
          "familias traen votellas, papel y cartón limpios. Los niños clasifican los materiales y explican por qué "
          "es importante reutilizarlos. Tambien preparan carteles para que nadie olvide separar los residuos en casa. "
          "Al final, todos aprenden que cuidar el ambiente es tarea de todos y que hay que acer el esfuerzo cada día.")
CORRECTIONS = [{"error": "votellas", "correction": "botellas", "criterion": "EE09"},
               {"error": "Tambien", "correction": "También", "criterion": "EE15"},
               {"error": "acer el", "correction": "hacer el", "criterion": "EE11"}]
REFERENCE = SOURCE.replace("votellas", "botellas").replace("Tambien", "También").replace("acer el", "hacer el")
SPELLING = {
    "title_es": "La feria de reciclaje", "topic_es": "El reciclaje en la escuela",
    "communicative_situation_es": ("Un estudiante escribió este texto para el boletín del grado, pero tiene errores "
                                   "de ortografía. Ayudalo a corregirlo antes de publicarlo."),
    "instructions_es": ["Leé con atención el texto.", "Corregí los errores de uso de b y v, de la h y de las tildes.",
                        "Escribí el texto completo corregido.", "No cambiés las ideas del texto."],
    "deliverable_description_es": "El texto completo, ya corregido.",
    "source_text_es": SOURCE, "reference_text_es": REFERENCE, "corrections": CORRECTIONS, "ambiguities_es": [],
}
REVIEW_OK = {k: 2 for k in editing.EDIT_REVIEW_KEYS} | {"notes": ""}


class FakeLlm:
    def __init__(self, generations, reviews=None):
        self.generations, self.reviews = list(generations), list(reviews or [REVIEW_OK])
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        body = json.loads(request.content)
        is_generation = body["messages"][0]["content"] == editing.SYSTEM
        source = self.generations if is_generation else self.reviews
        content = source.pop(0) if len(source) > 1 else source[0]
        self.calls.append("generation" if is_generation else "review")
        return httpx.Response(200, json={
            "id": f"gen-{len(self.calls)}", "model": body["model"], "provider": "Fake",
            "choices": [{"message": {"content": json.dumps(content, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 1200, "completion_tokens": 600, "cost": 0.0}})


def client_for(fake):
    return OpenRouterClient(LlmSettings(api_key=KEY), transport=httpx.MockTransport(fake), sleep=lambda s: None)


@pytest.fixture(scope="module")
def catalog():
    target = new_target()
    importer.import_workbook(WORKBOOK, target.url, "PNE2026-SUM-v1.0", schema=target.schema)
    conn = db.connect(target.url, target.schema, read_only=True)
    yield conn
    conn.close()
    drop_target(target)


@pytest.fixture()
def store():
    def drop():
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    drop()
    yield WritingStore(TEST_DATABASE_URL)
    drop()


def generate(catalog, store, fake, category="spelling"):
    return editing.generate_editing_exercise(client_for(fake), MemoryUsageStore(), catalog, store, category)


# ---------------------------------------------------------------- generation

def test_correction_exercise_is_accepted_with_separate_reference(catalog, store):
    fake = FakeLlm([SPELLING])
    outcome = generate(catalog, store, fake)
    assert outcome.status == "accepted" and fake.calls == ["generation", "review"]
    exercise = outcome.exercise
    assert (exercise["level"], exercise["exercise_type"]) == ("writing_conventions", "conventions_editing")
    assert exercise["target_criteria"] == ["EE09", "EE11", "EE15"] and exercise["source_text_es"] == SOURCE
    assert contracts.validate_exercise(exercise) == []
    assert REFERENCE not in json.dumps(exercise, ensure_ascii=False) and "corrections" not in exercise
    ref = store.reference_correction(exercise["exercise_id"])
    assert ref["corrected_text_es"] == REFERENCE and ref["corrections"] == CORRECTIONS
    stored = store.exercise(exercise["exercise_id"])
    assert "botellas" not in json.dumps(stored, ensure_ascii=False)
    [row] = store.generation_attempts()
    assert [c["id"] for c in row["checks"]] == ["W01", "W02", "W03", "W04", "W05", "W06", "W07",
                                               "W09", "W10", "W11", "W12", "W13", "W14", "W15", "W08"]
    assert row["reference"]["corrected_text_es"] == REFERENCE and row["prompt_version"] == "writing-edit-1.1"


@pytest.mark.parametrize("change,check", [
    ({"reference_text_es": REFERENCE.replace("Cada año", "Todos los años")}, "W10"),       # meaning edit
    ({"corrections": [dict(CORRECTIONS[0], criterion="EE15")] + CORRECTIONS[1:]}, "W11"),  # wrong criterion
    ({"corrections": CORRECTIONS[:2],
      "reference_text_es": SOURCE.replace("votellas", "botellas").replace("Tambien", "También")}, "W09"),  # EE11
    ({"corrections": CORRECTIONS + [{"error": "feria", "correction": "Feria", "criterion": "EE18"}]}, "W09"),
    ({"corrections": [dict(CORRECTIONS[0], error="vottellas")] + CORRECTIONS[1:]}, "W09"),  # not in the text
    ({"instructions_es": ["Leé con calma.", "Hacé lo necesario.", "Entregalo."],
      "deliverable_description_es": "Tu trabajo terminado."}, "W04"),
])
def test_invalid_correction_exercises_are_rejected_then_retried(catalog, store, change, check):
    outcome = generate(catalog, store, FakeLlm([{**SPELLING, **change}, SPELLING]))
    assert outcome.status == "accepted" and len(outcome.attempts) == 2
    assert any(r.startswith(check) for r in outcome.attempts[0].reasons), outcome.attempts[0].reasons
    assert store.reference_correction(outcome.exercise["exercise_id"]) is not None


def test_near_duplicate_text_is_rejected(catalog, store):
    generate(catalog, store, FakeLlm([SPELLING]))
    again = {**SPELLING, "title_es": "Otra feria", "topic_es": "Reciclar en la escuela"}
    outcome = generate(catalog, store, FakeLlm([again]))
    assert outcome.status == "rejected" and all(any(r.startswith("W12") for r in a.reasons)
                                                for a in outcome.attempts)


def test_review_flags_reject(catalog, store):
    low = REVIEW_OK | {"errors_genuine": 1, "notes": "«Tambien» lleva tilde, pero «acer» podría ser un nombre."}
    outcome = generate(catalog, store, FakeLlm([SPELLING], reviews=[low]))
    assert outcome.status == "rejected" and outcome.attempts[0].reasons[0].startswith("W08")
    assert store.exercises("writing_conventions") == []


@pytest.mark.parametrize("criterion,error,fix,ok", [
    ("EE09", "votellas", "botellas", True), ("EE09", "votellas", "botella", False),
    ("EE15", "Tambien", "También", True), ("EE15", "tambien", "Tambien", False),
    ("EE11", "acer", "hacer", True), ("EE10", "naturalesa", "naturaleza", True),
    ("EE12", "protejer", "proteger", True), ("EE13", "pero", "perro", True), ("EE14", "canpo", "campo", True),
    ("EE18", "costa rica", "Costa Rica", True), ("EE18", "costa", "costas", False),
    ("EE16", "jugar el", "jugar. El", True), ("EE16", "local, en", "local. En", True),
    ("EE16", "papel cartón", "papel, cartón", False), ("EE17", "papel cartón y", "papel, cartón y", True),
    ("EE17", "Que bonito!", "¡Qué bonito!", False), ("EE17", "Que bonito!", "¡Que bonito!", True),
    ("EE07", "las árbol alto", "los árboles altos", True), ("EE08", "las familias protege", "las familias protegen", True),
    ("EE08", "los niños es", "los niños son muy", False),
])
def test_change_fits_criterion(criterion, error, fix, ok):
    assert editing.change_fits_criterion(criterion, error, fix) is ok


# ---------------------------------------------------------------- seeding

def test_seeding_generates_only_missing_categories_and_is_idempotent(catalog, store):
    punctuation = {**SPELLING, "title_es": "El paseo al museo", "topic_es": "Una visita al museo",
                   "instructions_es": ["Leé el texto.", "Corregí las mayúsculas, los puntos, las comas y los signos.",
                                       "Escribí el texto completo corregido.", "No cambiés las ideas."],
                   "source_text_es": ("el martes visitamos el Museo Nacional en San José. Vimos piedras esferas, "
                                      "vasijas y joyas antiguas Una guía nos explicó cómo vivían los pueblos "
                                      "originarios. Qué interesante fue aprender sobre su historia! Al salir, "
                                      "comimos juntos en el parque y regresamos a la escuela en bus."),
                   "corrections": [{"error": "el martes", "correction": "El martes", "criterion": "EE18"},
                                   {"error": "piedras esferas, vasijas", "correction": "piedras, esferas, vasijas",
                                    "criterion": "EE17"},
                                   {"error": "antiguas Una", "correction": "antiguas. Una", "criterion": "EE16"},
                                   {"error": "Qué interesante", "correction": "¡Qué interesante",
                                    "criterion": "EE17"}]}
    punctuation["reference_text_es"] = punctuation["source_text_es"]
    for c in punctuation["corrections"]:
        punctuation["reference_text_es"] = punctuation["reference_text_es"].replace(c["error"], c["correction"], 1)
    generate(catalog, store, FakeLlm([SPELLING]))  # spelling already present
    fake = FakeLlm([punctuation])                    # agreement will fail (fake returns punctuation for it too)
    report = seeding.seed(client_for(fake), MemoryUsageStore(), catalog, store)
    status = {r["category"]: r["status"] for r in report["results"]}
    assert status == {"capitalization_punctuation": "accepted", "spelling": "present", "agreement": "rejected"}
    assert report["gap"] == ["agreement"] and report["totals"]["accepted"] == 1
    assert report["totals"]["calls"] >= 2 and report["totals"]["cost_usd"] == 0.0
    before = seeding.inventory(store)
    again = seeding.seed(client_for(FakeLlm([punctuation])), MemoryUsageStore(), catalog, store)
    assert seeding.inventory(store)["capitalization_punctuation"] == before["capitalization_punctuation"]
    assert {r["category"]: r["status"] for r in again["results"]}["spelling"] == "present"


# ---------------------------------------------------------------- student API confidentiality

def test_student_endpoints_never_expose_the_reference(catalog, store, synthetic_client):
    outcome = generate(catalog, store, FakeLlm([SPELLING]))
    eid = outcome.exercise["exercise_id"]
    url, schema = synthetic_client.app.state.catalog_target
    assert url == TEST_DATABASE_URL
    api = TestClient(create_app(url, schema, "TEST-v1"))
    secrets_ = [REFERENCE, "botellas", "También preparan", "hacer el", "corrections", "corrected_text"]
    responses = [api.get("/api/writing/levels"), api.get("/api/writing/levels/writing_conventions/exercises"),
                 api.get(f"/api/writing/exercises/{eid}"),
                 api.put(f"/api/writing/exercises/{eid}/draft", json={"text": "Borrador"}),
                 api.get(f"/api/writing/exercises/{eid}"),
                 api.post(f"/api/writing/exercises/{eid}/submit",
                          json={"text": "Texto corregido.", "client_request_id": str(uuid.uuid4())}),
                 api.get(f"/api/writing/exercises/{eid}"), api.get("/"), api.get("/static/app.js")]
    for response in responses:
        assert response.status_code in (200, 202), response.text
        for secret in secrets_:
            assert secret not in response.text, (response.url, secret)
    view = api.get(f"/api/writing/exercises/{eid}").json()
    assert view["source_text_es"] == SOURCE and view["title_es"] == "La feria de reciclaje"
    assert view["deliverable"]["requirements_es"][0] == "El texto completo, ya corregido"
    assert view["submission"]["status_es"] == "Pendiente de revisión del tutor"


class TruncatingLlm(FakeLlm):
    """The first `cut` generation calls stop at the output limit (finish_reason "length")."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cut = 2  # both free models of the first request
        self.max_tokens: list[int] = []

    def __call__(self, request):
        body = json.loads(request.content) if not request.url.path.endswith("/models") else {}
        if body and body["messages"][0]["content"] == editing.SYSTEM:
            self.max_tokens.append(body["max_tokens"])
            if self.cut:
                self.cut -= 1
                return httpx.Response(200, json={
                    "id": "gen-cut", "model": body["model"], "provider": "Fake",
                    "choices": [{"message": {"content": "{\"title_es\": \"La fer"}, "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 900, "completion_tokens": body["max_tokens"], "cost": 0.0}})
        return super().__call__(request)


def test_truncated_generation_uses_one_bounded_request_and_the_editing_limit(catalog, store):
    fake = TruncatingLlm([SPELLING])
    outcome = generate(catalog, store, fake)
    assert outcome.status == "accepted" and len(outcome.attempts) == 2
    assert outcome.attempts[0].reasons[0].startswith("generation exhausted")
    assert set(fake.max_tokens) == {editing.EDIT_MAX_TOKENS}
    assert [r["status"] for r in store.generation_attempts()] == ["rejected", "accepted"]


# ---------------------------------------------------------------- T024: quality checks and editorial revisions

from app.writing import revisions  # noqa: E402


def quality(record_changes=None, reference_changes=None):
    exercise = {"instructions_es": list(SPELLING["instructions_es"]), "source_text_es": SOURCE,
                **(record_changes or {})}
    reference = {"corrected_text_es": REFERENCE, "corrections": CORRECTIONS, "ambiguities_es": [],
                 **(reference_changes or {})}
    return {c["id"]: c["status"] for c in editing.quality_checks(exercise, reference)}


def test_quality_checks_detect_tu_repetition_and_undocumented_questions():
    assert quality() == {"W13": "pass", "W14": "pass", "W15": "pass"}
    assert quality({"instructions_es": ["Lee el texto.", "Corregí los errores."]})["W13"] == "fail"
    assert quality({"instructions_es": ["Leé el texto.", "No cambies las ideas."]})["W13"] == "fail"
    assert quality({"instructions_es": ["Leé el texto.", "No cambiés las ideas."]})["W13"] == "pass"
    assert quality(reference_changes={"corrected_text_es": REFERENCE + " Cada árbol es un árbol sano."})["W14"] == "fail"
    assert quality({"instructions_es": ["Corregí los errores de tildes del texto.",
                                        "Corregí los errores de tildes del texto completo."]})["W14"] == "fail"
    question = {"error": "preguntan cuál", "correction": "preguntan ¿cuál", "criterion": "EE17"}
    text = SOURCE + " Los niños preguntan cuál es el mejor material?"
    assert quality({"source_text_es": text}, {"corrections": [question]})["W15"] == "fail"
    assert quality({"source_text_es": text}, {"corrections": [question], "ambiguities_es": ["También «.»"]})["W15"] == \
        "pass"
    colon = {"error": "preguntan: cuál", "correction": "preguntan: ¿Cuál", "criterion": "EE17"}
    assert quality({"source_text_es": SOURCE + " Los niños preguntan: cuál es el mejor?"},
                   {"corrections": [colon]})["W15"] == "pass"


def test_generation_rejects_tu_instructions(catalog, store):
    tu = {**SPELLING, "instructions_es": SPELLING["instructions_es"][:3] + ["No cambies las ideas del texto."]}
    outcome = generate(catalog, store, FakeLlm([tu, SPELLING]))
    assert outcome.status == "accepted" and outcome.attempts[0].reasons[0].startswith("W13")


SPEC = {"exercise_id": None, "reason": "T024 test revision",
        "instructions": [["No cambiés las ideas del texto.", "No cambiés las ideas ni el orden del texto."]],
        "text": [["Al final, todos aprenden", "Al terminar, todos aprenden"]],
        "ambiguities_es": ["«hacer el esfuerzo» también admite «hacer un esfuerzo» (no es un error)."]}


def test_revision_is_validated_versioned_and_served_without_reference(catalog, store, synthetic_client):
    eid = generate(catalog, store, FakeLlm([SPELLING])).exercise["exercise_id"]
    url, schema = synthetic_client.app.state.catalog_target
    api = TestClient(create_app(url, schema, "TEST-v1"))
    original = api.get(f"/api/writing/exercises/{eid}").json()
    assert original["revision"] == 1 and original["editable_source"] is True
    [result] = revisions.apply_revisions(store, catalog, [{**SPEC, "exercise_id": eid}])
    assert result["status"] == "revised" and result["revision"] == 2 and "W15:pass" in result["checks"]
    assert revisions.apply_revisions(store, catalog, [{**SPEC, "exercise_id": eid}])[0]["status"] == "present"
    view = api.get(f"/api/writing/exercises/{eid}").json()
    assert view["revision"] == 2 and view["source_text_es"].count("Al terminar") == 1
    assert "No cambiés las ideas ni el orden del texto." in view["instructions_es"]
    # history: the original record and reference are unchanged; revision 2 has its own reference
    assert store.record(eid, 1)["source_text_es"] == SOURCE
    assert store.reference_correction(eid, 1)["corrected_text_es"] == REFERENCE
    latest = store.reference_correction(eid)
    assert latest["revision"] == 2 and "Al terminar" in latest["corrected_text_es"] and latest["ambiguities_es"]
    [row] = store.revisions(eid)
    assert (row["reason"], row["author"]) == ("T024 test revision", "human_editor") and row["checks"]
    for path in (f"/api/writing/exercises/{eid}", "/api/writing/levels/writing_conventions/exercises"):
        body = api.get(path).text
        assert latest["corrected_text_es"] not in body and REFERENCE not in body and "botellas" not in body


def test_invalid_revision_is_refused(catalog, store):
    eid = generate(catalog, store, FakeLlm([SPELLING])).exercise["exercise_id"]
    bad = {**SPEC, "exercise_id": eid, "reason": "bad", "instructions": [["No cambiés las ideas del texto.",
                                                                          "No cambies las ideas del texto."]]}
    with pytest.raises(Exception, match="W13"):
        revisions.apply_revisions(store, catalog, [bad])
    assert store.revisions(eid) == []


def test_submission_keeps_the_revision_it_answered(catalog, store, synthetic_client):
    eid = generate(catalog, store, FakeLlm([SPELLING])).exercise["exercise_id"]
    url, schema = synthetic_client.app.state.catalog_target
    api = TestClient(create_app(url, schema, "TEST-v1"))
    api.post(f"/api/writing/exercises/{eid}/submit", json={"text": SOURCE, "client_request_id": str(uuid.uuid4())})
    revisions.apply_revisions(store, catalog, [{**SPEC, "exercise_id": eid}])
    view = api.get(f"/api/writing/exercises/{eid}").json()
    assert view["revision"] == 1 and view["source_text_es"] == SOURCE and view["draft"]["text"] == SOURCE
    assert store.submission(eid)["exercise_revision"] == 1 and store.submission(eid)["text_es"] == SOURCE
