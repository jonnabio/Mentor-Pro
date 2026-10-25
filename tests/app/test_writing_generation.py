"""Writing exercise generation with OpenRouter (T021, ADR-020); scripted models, test database only."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import httpx
import psycopg
import pytest

from app.llm.client import OpenRouterClient
from app.llm.settings import LlmSettings
from app.llm.usage import MemoryUsageStore
from app.writing import contracts, generation
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
GOOD = {
    "topic_es": "Los huertos escolares",
    "communicative_situation_es": ("Tu escuela prepara una feria de huertos escolares para las familias. Escribí el "
                                   "párrafo de introducción de un texto expositivo que explique por qué un huerto "
                                   "ayuda a aprender y a comer mejor."),
    "suggested_ideas_es": ["Qué es un huerto escolar.", "Qué se aprende al cuidar las plantas.",
                           "Cómo ayuda a comer frutas y verduras."],
    "instructions_es": ["Escribí un solo párrafo de introducción para un texto expositivo.",
                        "Empezá con una idea principal que presente el tema.",
                        "Agregá al menos dos ideas complementarias relacionadas con la feria.",
                        "Uní las ideas con conectores como «además» o «por esta razón».",
                        "No contés una historia: informá y explicá."],
    "deliverable_description_es": "Un párrafo de introducción con una idea principal y dos ideas complementarias.",
}
REVIEW_OK = {k: 2 for k in generation.COMPOSE_REVIEW_KEYS} | {"notes": ""}


class FakeLlm:
    def __init__(self, generations, reviews=None, cost=0.0):
        self.generations, self.reviews = list(generations), list(reviews or [REVIEW_OK])
        self.calls: list[tuple[str, str]] = []
        self.prompts: list[str] = []
        self.cost = cost

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        self.prompts.append(body["messages"][1]["content"])
        if system == generation.SYSTEM:
            purpose, source = "generation", self.generations
        else:
            purpose, source = "review", self.reviews
        content = source.pop(0) if len(source) > 1 else source[0]
        content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        self.calls.append((purpose, body["model"]))
        return httpx.Response(200, json={
            "id": f"gen-{len(self.calls)}", "model": body["model"], "provider": "Fake",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1500, "completion_tokens": 400, "cost": self.cost}})


def client_for(fake, **overrides):
    return OpenRouterClient(LlmSettings(api_key=KEY, **overrides), transport=httpx.MockTransport(fake),
                            sleep=lambda s: None)


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


def run(catalog, store, fake, level="L2", difficulty="medium", criteria=("EE03", "EE04"), **settings):
    usage = MemoryUsageStore()
    outcome = generation.generate_exercise(client_for(fake, **settings), usage, catalog, store, level, difficulty,
                                           list(criteria))
    return outcome, usage


# ---------------------------------------------------------------- request and grounding

@pytest.mark.parametrize("level,criteria,difficulty,message", [
    ("L2", ["EE03"], "medium", "do not fit"),               # EE04 is core for L2
    ("L2", ["EE03", "EE04", "EE05"], "medium", "do not fit"),
    ("L3", ["EE03", "EE05", "EE06"], "medium", "not both"),
    ("L9", ["EE03"], "medium", "unknown writing level"),
    ("L2", ["EE03", "EE04"], "mixed", "difficulty"),
])
def test_invalid_requests_are_refused_before_any_call(catalog, level, criteria, difficulty, message):
    with pytest.raises(generation.WritingRequestError, match=message):
        generation.build_grounding(catalog, "PNE2026-SUM-v1.0", level, difficulty, criteria)


def test_grounding_joins_catalog_records_and_official_descriptors(catalog):
    g = generation.build_grounding(catalog, "PNE2026-SUM-v1.0", "L2", "medium", ["ee04", "EE03"])
    assert (g.level["code"], g.exercise_type, g.codes) == ("idea_development", "introduction_paragraph",
                                                           ["EE03", "EE04"])
    assert [c["assertion_id"] for c in g.criteria] == ["PNE2026-PRI-ESP-PE-B2-A3", "PNE2026-PRI-ESP-PE-B3-A4"]
    assert g.criteria[1]["descriptors_es"] == contracts.criteria()["EE04"]["descriptors_es"]
    assert g.deliverable == {"unit": "paragraphs", "min": 1, "max": 1, "evidence_mode": "typed"}
    full = generation.build_grounding(catalog, "PNE2026-SUM-v1.0", "L5", "hard", [f"EE{n:02d}" for n in range(1, 21)])
    assert full.deliverable["evidence_mode"] == "handwritten" and full.deliverable["time_limit_min"] == 90


def test_prompt_carries_official_goal_model_task_and_no_student_data(catalog):
    g = generation.build_grounding(catalog, "PNE2026-SUM-v1.0", "L2", "medium", ["EE03", "EE04"])
    user = generation.generation_messages(g, ["Un tema guardado"])[1]["content"]
    assert contracts.criteria()["EE04"]["descriptors_es"][4] in user
    assert "Situación comunicativa" in user and "La importancia de la higiene en la vida diaria" in user
    assert "Un tema guardado" in user and "un solo párrafo de introducción" in user
    assert "student" not in user.lower() and "@" not in user  # prompts carry no student data


# ---------------------------------------------------------------- generation outcomes

def test_valid_exercise_is_accepted_and_stored_with_metadata(catalog, store):
    fake = FakeLlm([GOOD], cost=0.0)
    outcome, usage = run(catalog, store, fake)
    assert outcome.status == "accepted" and len(outcome.attempts) == 1
    exercise = outcome.exercise
    assert contracts.validate_exercise(exercise) == []
    assert exercise["exercise_id"].startswith("PE-L2-huertos-escolares-")
    assert exercise["target_criteria"] == ["EE03", "EE04"]
    assert [p["rubric_ref"] for p in exercise["evaluation"]["parameters"]] == ["MEP-RUBRICA-PE-2026#EE03",
                                                                              "MEP-RUBRICA-PE-2026#EE04"]
    assert exercise["provenance"]["authored_by"] == "llm_draft_human_reviewed"
    assert [p for p, _ in fake.calls] == ["generation", "review"]
    assert fake.calls[1][1] == "rev/b:free"  # the reviewer is not the generator
    assert store.exercise(exercise["exercise_id"]) == exercise
    [row] = store.generation_attempts()
    assert (row["status"], row["exercise_id"], row["calls"], row["tokens_in"], row["tokens_out"]) == (
        "accepted", exercise["exercise_id"], 2, 3000, 800)
    assert float(row["cost_usd"]) == 0.0 and row["cost_complete"] and row["prompt_version"] == "writing-1.3"
    assert [c["id"] for c in row["checks"]] == ["W01", "W02", "W03", "W04", "W05", "W06", "W07",
                                               "W13", "W14", "W16", "W17", "W18", "W08"]
    assert {r["purpose"] for r in usage.records} == {"generation", "review"}
    with psycopg.connect(TEST_DATABASE_URL) as conn:
        assert conn.execute("SELECT generation_request_id FROM writing.exercise").fetchone()[0] == row["request_id"]


def test_model_cannot_set_criteria_rubric_or_metadata(catalog, store):
    sneaky = {**GOOD, "target_criteria": ["EE01", "EE99"], "level": "full_composition",
              "evaluation": {"parameters": [{"criterion": "EE99"}]}, "exercise_id": "PE-L5-x-000"}
    outcome, _ = run(catalog, store, FakeLlm([sneaky]))
    assert outcome.status == "accepted"
    assert outcome.exercise["target_criteria"] == ["EE03", "EE04"] and outcome.exercise["level"] == "idea_development"
    assert "descriptors_es" not in json.dumps(outcome.exercise)  # rubric referenced, never copied


@pytest.mark.parametrize("bad,check", [
    ({"instructions_es": GOOD["instructions_es"] + ["Se evaluará con el criterio EE04."]}, "W03"),
    ({"instructions_es": ["Escribí un texto sobre los huertos.", "Usá buena letra.", "Revisá la ortografía."],
      "deliverable_description_es": "Un texto breve."}, "W04"),
    ({"instructions_es": GOOD["instructions_es"][:2]}, "W05"),
    ({"topic_es": "La importancia del agua para la salud"}, "W06"),
    ({"instructions_es": ["Write one introduction paragraph.", "Add two ideas complementarias.",
                          "Escribí la idea principal del párrafo de introducción."]}, "W07"),
])
def test_invalid_exercise_is_rejected_then_retried(catalog, store, bad, check):
    outcome, _ = run(catalog, store, FakeLlm([{**GOOD, **bad}, GOOD]))
    assert outcome.status == "accepted" and len(outcome.attempts) == 2
    first = outcome.attempts[0]
    assert first.status == "rejected" and any(r.startswith(check) for r in first.reasons), first.reasons
    rows = store.generation_attempts()
    assert [r["status"] for r in rows] == ["rejected", "accepted"] and rows[0]["exercise_id"] is None


def test_unparseable_output_and_low_review_exhaust_the_bounded_retries(catalog, store):
    low = {**REVIEW_OK, "clarity": 1, "notes": "La instrucción 3 es ambigua."}
    fake = FakeLlm(["no es JSON", GOOD, GOOD], reviews=[low])
    outcome, _ = run(catalog, store, fake)
    assert outcome.status == "rejected" and outcome.stop_reason == "max_requests"
    assert len(outcome.attempts) == generation.MAX_REQUESTS == 3
    assert outcome.attempts[0].reasons[0].startswith("W01")
    assert all(r.startswith("W08") for a in outcome.attempts[1:] for r in a.reasons)
    assert store.topics() == [] and [r["status"] for r in store.generation_attempts()] == ["rejected"] * 3


def test_budget_exhaustion_stops_without_storing_an_exercise(catalog, store):
    outcome, usage = run(catalog, store, FakeLlm([GOOD]), max_requests_per_day=1)
    assert outcome.status == "unavailable" and outcome.stop_reason == "daily_budget"
    assert store.topics() == [] and store.generation_attempts()[0]["status"] == "unavailable"


def test_stored_topics_are_not_repeated(catalog, store):
    run(catalog, store, FakeLlm([GOOD]))
    pets = {**GOOD, "topic_es": "Las mascotas en la escuela",
            "communicative_situation_es": ("Tu grado prepara una charla sobre el cuidado responsable de perros y "
                                           "gatos. Escribí la introducción de un texto expositivo para el mural.")}
    outcome, _ = run(catalog, store, FakeLlm([GOOD, pets]))
    assert outcome.status == "accepted" and outcome.exercise["topic_es"] == "Las mascotas en la escuela"
    assert outcome.attempts[0].reasons[0].startswith("W06")


def test_paid_fallback_stays_disabled(catalog, store):
    fake = FakeLlm([GOOD])
    run(catalog, store, fake, paid_model="paid/x")
    assert all(model.endswith(":free") for _, model in fake.calls)


def test_typed_guided_composition_marks_handwriting_not_evaluable(catalog):
    g = generation.build_grounding(catalog, "PNE2026-SUM-v1.0", "L4", "medium",
                                   [f"EE{n:02d}" for n in range(1, 7)] + ["EE19"])
    exercise = generation.assemble(g, generation.model_fields(json.dumps(GOOD, ensure_ascii=False)))
    param = next(p for p in exercise["evaluation"]["parameters"] if p["criterion"] == "EE19")
    assert param["applicability"] == "not_evaluable"
    assert contracts.validate_exercise(copy.deepcopy(exercise)) == []


# ---------------------------------------------------------------- T025: composed-paragraph checks

@pytest.mark.parametrize("bad,check", [
    ({"instructions_es": GOOD["instructions_es"][:4] + ["No cuentes una historia: informá y explicá."]}, "W13"),
    ({"instructions_es": GOOD["instructions_es"] + ["Escribí un solo párrafo de introducción para el texto."]}, "W14"),
    ({"suggested_ideas_es": GOOD["suggested_ideas_es"] + ["Consecuencias de no tener huerto."]}, "W16"),
    ({"suggested_ideas_es": ["Un huerto escolar es un espacio donde los estudiantes siembran, riegan y cosechan "
                             "verduras, y así aprenden ciencias, trabajo en equipo y alimentación sana."]}, "W17"),
])
def test_compose_quality_rejects_then_retries(catalog, store, bad, check):
    outcome, _ = run(catalog, store, FakeLlm([{**GOOD, **bad}, GOOD]))
    assert outcome.status == "accepted" and len(outcome.attempts) == 2
    assert any(r.startswith(check) for r in outcome.attempts[0].reasons), outcome.attempts[0].reasons


def test_near_duplicate_situation_is_rejected(catalog, store):
    run(catalog, store, FakeLlm([GOOD]))
    outcome, _ = run(catalog, store, FakeLlm([{**GOOD, "topic_es": "La huerta de la escuela"}]))
    assert outcome.status == "rejected" and all(any(r.startswith("W18") for r in a.reasons) for a in outcome.attempts)


def test_review_scope_and_model_text_reject(catalog, store):
    low = REVIEW_OK | {"paragraph_scope": 1, "notes": "La idea 3 corresponde a la conclusión."}
    outcome, _ = run(catalog, store, FakeLlm([GOOD], reviews=[low]))
    assert outcome.status == "rejected" and "paragraph_scope" in outcome.attempts[0].reasons[0]


def test_conclusion_exercise(catalog, store):
    conclusion = {**GOOD, "topic_es": "El ahorro de electricidad en casa",
                  "communicative_situation_es": ("Tu escuela publica un boletín sobre el uso de la electricidad. "
                                                 "Escribí el párrafo de conclusión de un texto expositivo."),
                  "suggested_ideas_es": ["Apagar luces que no se usan.", "Desconectar cargadores."],
                  "instructions_es": ["Escribí un solo párrafo de conclusión para un texto expositivo.",
                                      "Proponé una idea principal con una acción o solución.",
                                      "Agregá al menos dos ideas complementarias sobre cómo ahorrar.",
                                      "Usá conectores de cierre como «en conclusión»."],
                  "deliverable_description_es": "Un párrafo de conclusión con acciones o soluciones."}
    outcome, _ = run(catalog, store, FakeLlm([conclusion]), level="L3", criteria=("EE03", "EE06"))
    assert outcome.status == "accepted" and outcome.exercise["exercise_type"] == "conclusion_paragraph"
    assert outcome.exercise["target_criteria"] == ["EE03", "EE06"]


def test_compose_seeding_generates_only_missing_and_is_idempotent(catalog, store, monkeypatch):
    from app.writing import seeding

    monkeypatch.setattr(seeding, "COMPOSE_PLAN", (("L2", "introduction_paragraph", ["EE03", "EE04"], 2),))
    run(catalog, store, FakeLlm([GOOD]))  # one already approved
    pets = {**GOOD, "topic_es": "Las mascotas en la escuela",
            "communicative_situation_es": ("Tu grado prepara una charla sobre el cuidado responsable de perros y "
                                           "gatos. Escribí la introducción de un texto expositivo para el mural.")}
    report = seeding.seed_compose(client_for(FakeLlm([pets])), MemoryUsageStore(), catalog, store)
    assert report["gap"] == {} and report["totals"]["accepted"] == 1 and len(report["results"]) == 1
    again = seeding.seed_compose(client_for(FakeLlm([pets])), MemoryUsageStore(), catalog, store)
    assert again["results"] == [] and len(seeding.compose_inventory(store)["introduction_paragraph"]) == 2


def test_compose_revision_is_validated_and_versioned(catalog, store):
    from app.writing import revisions

    eid = run(catalog, store, FakeLlm([GOOD]))[0].exercise["exercise_id"]
    spec = {"exercise_id": eid, "reason": "T025 test", "ideas_remove": ["Qué es un huerto escolar."],
            "set_instructions": GOOD["instructions_es"][:4]}
    [result] = revisions.apply_revisions(store, catalog, [spec])
    assert result["status"] == "revised" and result["revision"] == 2 and "W16:pass" in result["checks"]
    assert store.record(eid)["suggested_ideas_es"] == GOOD["suggested_ideas_es"][1:]
    assert store.record(eid, 1)["suggested_ideas_es"] == GOOD["suggested_ideas_es"]
    bad = {"exercise_id": eid, "reason": "bad",
           "set_instructions": GOOD["instructions_es"][:3] + ["No cuentes una historia."]}
    with pytest.raises(Exception, match="W13"):
        revisions.apply_revisions(store, catalog, [bad])
