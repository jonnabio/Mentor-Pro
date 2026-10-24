"""One-question generation pipeline and dev endpoint with a mocked OpenRouter."""

from __future__ import annotations

import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from app.generation import prompts
from app.generation.grounding import GroundingError, build_grounding
from app.generation.parsing import OutputError, extract_json, parse_rubric, parse_solve
from app.generation.pipeline import generate_one, student_view
from app.generation.store import MemoryGenerationStore
from app.llm.client import OpenRouterClient
from app.llm.settings import LlmSettings
from app.llm.usage import MemoryUsageStore
from app.main import create_app
from conftest import SYNTHETIC

KEY = "sk-or-v1-test-key-not-real"
MODELS = {"data": [
    {"id": "gen/a:free", "context_length": 100000, "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "solve/b:free", "context_length": 50000, "pricing": {"prompt": "0", "completion": "0"}},
]}

MATH_ITEM = {
    "stimulus": {"type": "none"},
    "stem": "Una escuela reúne 144 cuadernos y los reparte por igual en 6 aulas. ¿Cuántos cuadernos recibe cada aula?",
    "options": [{"label": "A", "text": "18"}, {"label": "B", "text": "24"},
                {"label": "C", "text": "26"}, {"label": "D", "text": "138"}],
    "answer_key": "B",
    "explanation": "Se divide 144 entre 6 y se obtienen 24 cuadernos por aula.",
    "distractor_rationales": {"A": "Error al dividir.", "C": "Estima en lugar de dividir.", "D": "Resta en vez de dividir."},
    "cognitive_verb": "Lee",
    "subject_checks": {"math": {"expression": "144 / 6"}},
}
PASSAGE = ("Las tortugas baula llegan cada año a las playas de Guanacaste para desovar. Durante la noche, cada "
           "hembra cava un nido en la arena y deposita sus huevos. Por eso, proteger estas playas es necesario "
           "para que la especie sobreviva. Los guardaparques vigilan la zona y evitan que se usen luces fuertes "
           "cerca de los nidos.")
READING_ITEM = {
    "stimulus": {"type": "text", "text": PASSAGE},
    "stem": "¿Cuál es la idea fundamental del texto?",
    "options": [{"label": "A", "text": "Los guardaparques usan luces fuertes en la playa."},
                {"label": "B", "text": "Proteger las playas permite que las tortugas baula sobrevivan."},
                {"label": "C", "text": "Las tortugas cavan sus nidos durante el día."},
                {"label": "D", "text": "Guanacaste es una provincia grande y muy seca."}],
    "answer_key": "B",
    "explanation": "El texto concluye que proteger las playas es necesario para que la especie sobreviva.",
    "distractor_rationales": {"A": "Contradice el texto.", "C": "Contradice el texto.", "D": "No aparece en el texto."},
    "cognitive_verb": "Explica",
    "subject_checks": {"reading": {"key_support_span": "proteger estas playas es necesario para que la especie sobreviva"}},
}
RUBRIC_OK = {"alignment": 2, "clarity": 2, "distractor_quality": 2, "language": 2, "difficulty_match": 2, "notes": ""}


class FakeLlm:
    """Answers by purpose: generation scripts (list), solve letter, rubric JSON."""

    def __init__(self, generations, solve="B", rubric=None, cost=0.0):
        self.generations = list(generations)
        self.solve, self.rubric, self.cost = solve, rubric or RUBRIC_OK, cost
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()  # practice-set workers call concurrently
        self.max_tokens: dict[str, list[int]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            return self._respond(request)

    def _respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        if system == prompts.SYSTEM:
            purpose = "generation"
            content = self.generations.pop(0) if len(self.generations) > 1 else self.generations[0]
            content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        elif system.startswith("Usted resuelve"):
            purpose, content = "solve", self.solve
        else:
            purpose, content = "rubric", json.dumps(self.rubric)
        self.calls.append((purpose, body["model"]))
        self.max_tokens.setdefault(purpose, []).append(body["max_tokens"])
        return httpx.Response(200, json={
            "id": f"gen-{len(self.calls)}", "model": body["model"], "provider": "Fake",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 300, "cost": self.cost}})


def client_for(fake):
    return OpenRouterClient(LlmSettings(api_key=KEY), transport=httpx.MockTransport(fake), sleep=lambda s: None)


@pytest.fixture()
def catalog_conn(synthetic_client):
    from app.main import open_catalog
    import workbook_fixtures  # noqa: F401  (path set by conftest)

    url, schema = synthetic_client.app.state.catalog_target
    conn = open_catalog(url, schema)
    yield conn
    conn.close()


def bundle(conn, subject="matematicas", code="M01", ordinal=None):
    return build_grounding(conn, SYNTHETIC, subject, code, ordinal)


# ---------------------------------------------------------------- grounding

def test_grounding_uses_catalog_text(catalog_conn):
    b = bundle(catalog_conn)
    assert b.objective["text_es"] == "Resuelve problemas con números naturales."
    assert b.evidence["ordinal"] == 1 and b.evidence["id"].endswith("-E1")
    assert b.concept_lines == ["Valor posicional.", "Lectura y escritura."]
    assert [r["record_type"] for r in b.records()] == ["bloque", "afirmacion", "evidencia"]
    assert bundle(catalog_conn, ordinal=2).evidence["ordinal"] == 2


@pytest.mark.parametrize(("subject", "code", "ordinal"), [
    ("matematicas", "M99", None), ("espanol", "M01", None), ("espanol", "EE01", None), ("matematicas", "M01", 9)])
def test_grounding_abstains(catalog_conn, subject, code, ordinal):
    with pytest.raises(GroundingError):
        bundle(catalog_conn, subject, code, ordinal)


def test_prompt_contains_curriculum_and_no_student_data(catalog_conn):
    messages = prompts.generation_messages(bundle(catalog_conn), "medium")
    user = messages[1]["content"]
    assert "Lee números  mayores que 100 000." in user and "<curriculo>" in user
    assert "Intermedia" in user and "expression" in user


# ---------------------------------------------------------------- parsing

def test_parsing_helpers():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Aquí está: {"a": {"b": 2}} fin') == {"a": {"b": 2}}
    with pytest.raises(OutputError):
        extract_json("sin json")
    assert parse_solve("La respuesta es B.") == "B"
    assert parse_solve("AMBIGUA") is None and parse_solve("A o B") is None
    with pytest.raises(OutputError):
        parse_rubric('{"alignment": 3}')


# ---------------------------------------------------------------- pipeline

def test_math_item_accepted_with_proof_and_no_solve(catalog_conn):
    fake = FakeLlm([MATH_ITEM])
    usage = MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "easy")
    assert outcome.status == "accepted", outcome.reasons
    assert outcome.validation["math_proven"] is True
    assert [p for p, _ in fake.calls] == ["generation", "rubric"]
    item = outcome.item
    assert item["grounding_basis"] == "approved_baseline"
    assert item["source_refs"][0]["excerpt"] == "Lee números  mayores que 100 000."
    assert item["item_id"].startswith(f"Q-{outcome.evidence_id}-")
    summary = outcome.summary()
    assert (summary["calls"], summary["tokens_in"], summary["tokens_out"], summary["cost_usd"]) == (2, 1800, 600, 0.0)
    assert {r["purpose"] for r in usage.records} == {"generation", "review"}


def test_wrong_math_key_is_rejected_after_retry(catalog_conn):
    bad = {**MATH_ITEM, "answer_key": "A",
           "distractor_rationales": {"B": "x x x", "C": "x x x", "D": "x x x"}}
    fake = FakeLlm([bad])
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "easy")
    assert outcome.status == "rejected"
    assert [p for p, _ in fake.calls] == ["generation", "generation"]
    assert any("M03" in r for r in outcome.reasons)


def test_reading_item_needs_agreeing_blind_solve(catalog_conn):
    fake = FakeLlm([READING_ITEM], solve="B")
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn, "espanol", "EL01"), "medium")
    assert outcome.status == "accepted", outcome.reasons
    assert outcome.validation["independent_solve"]["agrees_with_key"] is True
    gen_model = fake.calls[0][1]
    solve_model = next(m for p, m in fake.calls if p == "solve")
    assert solve_model != gen_model  # blind solve uses a different model


def test_solve_disagreement_rejects(catalog_conn):
    fake = FakeLlm([READING_ITEM], solve="C")
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn, "espanol", "EL01"), "medium")
    assert outcome.status == "rejected"
    assert any("independent solve chose C" in r for r in outcome.reasons)


def test_every_attempt_reason_is_recorded(catalog_conn):
    fake = FakeLlm([READING_ITEM], solve="C")
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn, "espanol", "EL01"), "medium")
    attempts = outcome.validation["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert all(a["verdict"] == "regenerate" and a["reasons"] for a in attempts)


def test_rubric_zero_rejects_and_rubric_one_revises(catalog_conn):
    fake = FakeLlm([MATH_ITEM], rubric={**RUBRIC_OK, "clarity": 0})
    assert generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "easy").status == "rejected"
    fake = FakeLlm([MATH_ITEM], rubric={**RUBRIC_OK, "language": 1})
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "easy")
    assert outcome.status == "rejected" and outcome.validation["verdict"] == "revise"


def test_invalid_output_then_valid_output(catalog_conn):
    fake = FakeLlm(["no es json", MATH_ITEM])
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "easy")
    assert outcome.status == "accepted"


def test_model_cannot_override_metadata(catalog_conn):
    sneaky = {**MATH_ITEM, "item_id": "Q-FAKE", "grounding_basis": "official",
              "source_refs": [{"record_id": "X", "excerpt": "inventado"}]}
    outcome = generate_one(client_for(FakeLlm([sneaky])), MemoryUsageStore(), bundle(catalog_conn), "easy")
    assert outcome.item["grounding_basis"] == "approved_baseline"
    assert outcome.item["source_refs"][0]["record_id"] == outcome.evidence_id


def test_student_view_hides_answer():
    view = student_view({"item_id": "Q-1", **MATH_ITEM})
    assert set(view) == {"item_id", "stimulus", "stem", "options"}


# ---------------------------------------------------------------- dev endpoint

def dev_app(synthetic_client, fake, generation_store=None):
    url, schema = synthetic_client.app.state.catalog_target
    store = generation_store or MemoryGenerationStore()
    app = create_app(url, schema, SYNTHETIC, dev_endpoints=True,
                     llm_factory=lambda: (client_for(fake), MemoryUsageStore(), store))
    return TestClient(app), store


def test_dev_endpoint_disabled_by_default(synthetic_client):
    response = synthetic_client.post("/api/dev/questions/generate",
                                     json={"subject": "matematicas", "objective_code": "M01", "difficulty": "easy"})
    assert response.status_code == 404


def test_dev_endpoint_accepted(synthetic_client):
    client, store = dev_app(synthetic_client, FakeLlm([MATH_ITEM]))
    data = client.post("/api/dev/questions/generate",
                       json={"subject": "matematicas", "objective_code": "M01", "difficulty": "easy"}).json()
    assert data["status"] == "accepted" and data["item"]["answer_key"] == "B"
    assert "answer_key" not in data["student_view"] and "explanation" not in data["student_view"]
    assert data["usage"]["models_used"] == ["gen/a:free", "solve/b:free"]  # rubric runs on another model
    assert len(store.rows) == 1


def test_dev_endpoint_rejected_is_labelled(synthetic_client):
    bad = {**MATH_ITEM, "answer_key": "A", "distractor_rationales": {"B": "x x x", "C": "x x x", "D": "x x x"}}
    client, _ = dev_app(synthetic_client, FakeLlm([bad]))
    data = client.post("/api/dev/questions/generate",
                       json={"subject": "matematicas", "objective_code": "M01", "difficulty": "easy"}).json()
    assert data["status"] == "rejected" and "item" not in data and "student_view" not in data
    assert data["rejected_draft"]["answer_key"] == "A"


@pytest.mark.parametrize("payload", [
    {"subject": "espanol", "objective_code": "EE01", "difficulty": "easy"},
    {"subject": "matematicas", "objective_code": "M01", "difficulty": "mixed"},
    {"subject": "espanol", "objective_code": "M01", "difficulty": "easy"},
])
def test_dev_endpoint_rejects_invalid_requests(synthetic_client, payload):
    client, _ = dev_app(synthetic_client, FakeLlm([MATH_ITEM]))
    assert client.post("/api/dev/questions/generate", json=payload).status_code == 422


def test_dev_endpoint_without_key_returns_503(synthetic_client, monkeypatch):
    from app.llm.settings import LlmConfigurationError

    def unconfigured():
        raise LlmConfigurationError("OPENROUTER_API_KEY is not set")
    url, schema = synthetic_client.app.state.catalog_target
    client = TestClient(create_app(url, schema, SYNTHETIC, dev_endpoints=True, llm_factory=unconfigured))
    response = client.post("/api/dev/questions/generate",
                           json={"subject": "matematicas", "objective_code": "M01", "difficulty": "easy"})
    assert response.status_code == 503 and response.json()["error"] == "llm_not_configured"


def test_parsers_tolerate_leaked_reasoning():
    reasoning = ('The user wants me to evaluate {an item}. Let me check B and C.\n'
                 '{"alignment": 2, "clarity": 2, "distractor_quality": 1, "language": 2, "difficulty_match": 2, "notes": "ok"}')
    assert parse_rubric(reasoning)["distractor_quality"] == 1
    assert parse_solve("Compare A with C... the largest is option C.\nC") == "C"
    assert parse_solve("Options A and B look wrong.\nAMBIGUA") is None


def test_subject_checks_keep_only_known_keys():
    from app.generation.parsing import model_fields

    raw = {**READING_ITEM, "subject_checks": {"reading": {"key_support_span": "x", "difficulty": "medium"},
                                              "difficulty": "medium", "math": "nope"}}
    assert model_fields(raw)["subject_checks"] == {"reading": {"key_support_span": "x"}}


@pytest.mark.parametrize(("subject", "code", "block"), [
    ("matematicas", "M01", '"math"'), ("espanol", "EL01", '"reading"')])
def test_prompt_shows_exact_subject_checks_shape(catalog_conn, subject, code, block):
    user = prompts.generation_messages(bundle(catalog_conn, subject, code), "easy")[1]["content"]
    assert "EJEMPLO DE subject_checks" in user and block in user.split("EJEMPLO DE subject_checks")[-1]


# ---------------------------------------------------------------- unproven property questions (checker 1.6.0, T009)

PROPERTY_ITEM = {
    **MATH_ITEM,
    "stimulus": {"type": "text", "text": "En la escuela hay 72 alumnos inscritos en un torneo de fútbol."},
    "stem": "¿Cuál es la mayor cantidad de equipos iguales que se pueden formar de modo que el número de equipos "
            "sea múltiplo de 3 y par?",
    "options": [{"label": "A", "text": "6"}, {"label": "B", "text": "12"},
                {"label": "C", "text": "18"}, {"label": "D", "text": "24"}],
    "answer_key": "D",
    "explanation": "24 divide a 72, es par y es múltiplo de 3; es la mayor de las opciones que cumple.",
    "distractor_rationales": {"A": "No es la mayor.", "B": "No es la mayor.", "C": "No es la mayor."},
    "subject_checks": {"math": {"select": "max"}},
}


def test_property_question_needs_agreeing_blind_solve(catalog_conn):
    fake = FakeLlm([PROPERTY_ITEM], solve="D")
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "medium")
    assert outcome.status == "accepted"
    assert outcome.validation["math_proven"] is False
    assert outcome.validation["independent_solve"]["agrees_with_key"] is True
    assert "solve" in [p for p, _ in fake.calls]


def test_property_question_rejected_when_blind_solve_disagrees(catalog_conn):
    fake = FakeLlm([PROPERTY_ITEM], solve="C")
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "medium")
    assert outcome.status == "rejected"
    assert any("independent solve chose C" in r for r in outcome.reasons)


def test_property_question_rejected_when_blind_solve_unavailable(catalog_conn):
    class NoSolve(FakeLlm):
        def _respond(self, request):
            if request.content and json.loads(request.content)["messages"][0]["content"].startswith("Usted resuelve"):
                return httpx.Response(404, json={"error": {"message": "unavailable"}})
            return super()._respond(request)

    outcome = generate_one(client_for(NoSolve([PROPERTY_ITEM])), MemoryUsageStore(), bundle(catalog_conn), "medium")
    assert outcome.status == "rejected" and outcome.validation["verdict"] == "pending"
    assert "independent solve unavailable" in outcome.reasons


# ---------------------------------------------------------------- per-purpose output limits (T011)

def test_only_generation_uses_the_configurable_limit(catalog_conn):
    fake = FakeLlm([READING_ITEM])
    client = OpenRouterClient(LlmSettings(api_key=KEY, generation_max_tokens=7000),
                              transport=httpx.MockTransport(fake), sleep=lambda s: None)
    assert generate_one(client, MemoryUsageStore(), bundle(catalog_conn, "espanol", "EL01"), "medium").status         == "accepted"
    assert fake.max_tokens == {"generation": [7000], "solve": [2000], "rubric": [3000]}


def test_default_generation_limit_is_4000(catalog_conn):
    fake = FakeLlm([MATH_ITEM])
    generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "easy")
    assert fake.max_tokens["generation"] == [4000] and fake.max_tokens["rubric"] == [3000]
