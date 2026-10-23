"""Practice set generation (T007, ADR-011) with a mocked OpenRouter."""

from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.allocation import allocate
from app.generation import prompts
from app.generation.practice_set import SetLimits, coverage, generate_set
from app.generation.store import MemoryGenerationStore
from app.llm.client import OpenRouterClient
from app.llm.settings import LlmSettings
from app.llm.usage import MemoryUsageStore
from app.main import create_app
from conftest import SYNTHETIC
from curriculum.catalog import select_objectives
from test_generation import KEY, MATH_ITEM, FakeLlm, catalog_conn, client_for  # noqa: F401  (fixture)

import httpx

CONTEXTS = [  # (stem, total, groups): distinct situations so no two items are near duplicates
    ("Una escuela reúne {t} cuadernos y los reparte por igual en {g} aulas. ¿Cuántos cuadernos recibe cada aula?", 144, 6),
    ("En la feria se venden {t} empanadas en bolsas de {g} unidades. ¿Cuántas bolsas se llenan?", 96, 4),
    ("Un grupo reparte {t} calcomanías en {g} sobres iguales. ¿Cuántas calcomanías lleva cada sobre?", 250, 5),
    ("La biblioteca ordena {t} libros en {g} estantes con la misma cantidad. ¿Cuántos libros van por estante?", 168, 7),
    ("Para el acto cívico se acomodan {t} sillas en {g} filas iguales. ¿Cuántas sillas tiene cada fila?", 216, 9),
]


def math_item(index: int) -> dict:
    stem, total, groups = CONTEXTS[index]
    answer = total // groups
    item = copy.deepcopy(MATH_ITEM)
    item["stem"] = stem.format(t=total, g=groups)
    item["options"] = [{"label": "A", "text": str(answer - 3)}, {"label": "B", "text": str(answer)},
                       {"label": "C", "text": str(answer + 2)}, {"label": "D", "text": str(total - groups)}]
    item["explanation"] = f"Se divide {total} entre {groups} y se obtiene {answer}."
    item["subject_checks"] = {"math": {"expression": f"{total} / {groups}"}}
    return item


def plan(conn, codes=("M01", "M02"), count=5):
    selection = select_objectives(conn, SYNTHETIC, "selected_objectives", "matematicas", list(codes))
    return allocate(selection.objectives, count, "medium")["allocation"]


def run_set(conn, fake, limits=SetLimits(), usage=None, settings=None):
    client = (OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)
              if settings else client_for(fake))
    usage = usage or MemoryUsageStore()
    store = MemoryGenerationStore()
    allocation = plan(conn)
    result = generate_set(conn, client, usage, store, SYNTHETIC, "matematicas", allocation, limits)
    return result, allocation, usage, store


def test_complete_set_follows_allocation(catalog_conn):
    result, allocation, usage, store = run_set(catalog_conn, FakeLlm([math_item(i) for i in range(5)]))
    assert result.status == "complete" and result.stop_reason is None
    assert [s.objective_code for s in result.slots] == ["M01", "M01", "M01", "M02", "M02"]
    assert [s.evidence_id for s in result.slots] == [s["evidence_id"] for row in allocation for s in row["slots"]]
    assert all(s.status == "accepted" and s.item["curriculum_ref"]["evidencia_id"] == s.evidence_id
               for s in result.slots)
    assert all(row["planned"] == row["accepted"] for row in coverage(allocation, result))
    assert len({s.item["item_id"] for s in result.slots}) == 5
    summary = result.summary()
    assert summary["accepted"] == 5 and summary["rejected_attempts"] == 0
    assert summary["calls"] == len(usage.records) == 10  # generation + rubric per math item (proof, no solve)
    assert all(r["practice_set_id"] == result.practice_set_id for r in usage.records)
    assert [(r["practice_set_id"], r["slot"]) for r in store.rows] == [(result.practice_set_id, n) for n in range(1, 6)]


def test_duplicate_within_set_is_rejected_and_regenerated(catalog_conn):
    generations = [math_item(0), math_item(0), math_item(1), math_item(2), math_item(3), math_item(4)]
    result, *_ = run_set(catalog_conn, FakeLlm(generations))
    assert result.status == "complete"
    stems = [s.item["stem"] for s in result.slots]
    assert len(set(stems)) == 5
    reasons = [r for row in result.rejection_reasons() for r in row["reasons"]]
    assert any(r.startswith("D01: exact duplicate") for r in reasons)


def test_invalid_questions_never_fill_the_set(catalog_conn):
    wrong = {**math_item(0), "answer_key": "A"}
    result, allocation, *_ = run_set(catalog_conn, FakeLlm([wrong]), SetLimits(max_requests_per_slot=1))
    assert result.status == "partial" and result.stop_reason == "slot_retries_exhausted"
    assert all(s.status == "failed" and s.item is None for s in result.slots)
    assert all(len(s.requests) == 1 for s in result.slots)
    summary = result.summary()
    assert summary["accepted"] == 0 and summary["rejected_attempts"] == summary["generation_attempts"] == 10
    assert all(row["accepted"] == 0 for row in coverage(allocation, result))


def test_set_call_limit_is_never_exceeded(catalog_conn):
    result, _, usage, _ = run_set(catalog_conn, FakeLlm([math_item(i) for i in range(5)]),
                                  SetLimits(max_calls_per_set=3))
    sent = [r for r in usage.records if r["status"] != "budget_blocked"]
    assert len(sent) == 3
    assert result.status == "partial" and result.stop_reason == "set_call_limit"
    assert [s.status for s in result.slots] == ["accepted", "failed", "not_attempted", "not_attempted",
                                                "not_attempted"]


def test_daily_budget_stops_the_set(catalog_conn):
    settings = LlmSettings(api_key=KEY, max_requests_per_day=4)
    result, _, usage, _ = run_set(catalog_conn, FakeLlm([math_item(i) for i in range(5)]), settings=settings)
    assert len([r for r in usage.records if r["status"] != "budget_blocked"]) == 4
    assert result.status == "partial" and result.stop_reason == "daily_budget"
    assert result.summary()["accepted"] == 2


def test_more_questions_than_the_limit_is_refused(catalog_conn):
    with pytest.raises(ValueError):
        generate_set(catalog_conn, None, MemoryUsageStore(), MemoryGenerationStore(), SYNTHETIC, "matematicas",
                     plan(catalog_conn, count=10), SetLimits())


def test_limits_from_env():
    assert SetLimits.from_env({}) == SetLimits()
    assert SetLimits.from_env({"MENTOR_PRO_SET_MAX_CALLS": "12"}).max_calls_per_set == 12
    with pytest.raises(ValueError):
        SetLimits.from_env({"MENTOR_PRO_SET_MAX_REQUESTS_PER_SLOT": "0"})


# ---------------------------------------------------------------- dev endpoint

def dev_client(synthetic_client, fake):
    url, schema = synthetic_client.app.state.catalog_target
    store = MemoryGenerationStore()
    app = create_app(url, schema, SYNTHETIC, dev_endpoints=True,
                     llm_factory=lambda: (client_for(fake), MemoryUsageStore(), store))
    return TestClient(app), store


SET_REQUEST = {"subject": "matematicas", "scope": "selected_objectives", "objective_codes": ["M02", "M01"],
               "difficulty": "medium", "question_count": 5}


def test_dev_practice_set_endpoint(synthetic_client):
    client, store = dev_client(synthetic_client, FakeLlm([math_item(i) for i in range(5)]))
    data = client.post("/api/dev/practice-sets/generate", json=SET_REQUEST).json()
    assert data["status"] == "complete" and data["summary"]["accepted"] == 5
    assert [row["planned"] for row in data["coverage"]] == [2, 1, 2]
    for slot in data["slots"]:
        assert "answer_key" not in slot["student_view"] and "explanation" not in slot["student_view"]
    assert len(store.sets) == 1 and store.sets[0]["result"].practice_set_id == data["practice_set_id"]


@pytest.mark.parametrize("change", [{"question_count": 10}, {"objective_codes": ["M01", "EL01"]},
                                    {"scope": "single_objective"}])
def test_dev_practice_set_rejects_invalid_requests(synthetic_client, change):
    client, store = dev_client(synthetic_client, FakeLlm([math_item(0)]))
    response = client.post("/api/dev/practice-sets/generate", json={**SET_REQUEST, **change})
    assert response.status_code == 422 and not store.sets


def test_postgres_store_persists_set_items_and_attempts(synthetic_client, catalog_conn):
    import psycopg

    from app.generation.store import GenerationStore

    url, _ = synthetic_client.app.state.catalog_target
    store = GenerationStore(url)
    allocation = plan(catalog_conn)
    result = generate_set(catalog_conn, client_for(FakeLlm([math_item(i) for i in range(5)])), MemoryUsageStore(),
                          store, SYNTHETIC, "matematicas", allocation, SetLimits())
    store.add_set(result, SYNTHETIC, SET_REQUEST, allocation, {"max_questions": 5})
    set_id = result.practice_set_id
    try:
        with psycopg.connect(url) as conn:
            row = conn.execute("SELECT status, accepted, calls FROM generation.practice_set "
                               "WHERE practice_set_id = %s", (set_id,)).fetchone()
            items = conn.execute("SELECT slot, objective_code, evidence_id FROM generation.practice_set_item "
                                 "WHERE practice_set_id = %s ORDER BY slot", (set_id,)).fetchall()
            attempts = conn.execute("SELECT COUNT(*) FROM generation.question_attempt WHERE practice_set_id = %s",
                                    (set_id,)).fetchone()[0]
        assert row == ("complete", 5, 10)
        assert [(i[0], i[1]) for i in items] == [(1, "M01"), (2, "M01"), (3, "M01"), (4, "M02"), (5, "M02")]
        assert attempts == 5
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DELETE FROM generation.practice_set_item WHERE practice_set_id = %s", (set_id,))
            conn.execute("DELETE FROM generation.practice_set WHERE practice_set_id = %s", (set_id,))
            conn.execute("DELETE FROM generation.question_attempt WHERE practice_set_id = %s", (set_id,))



class FlakyLlm(FakeLlm):
    """Fails the first `failures` generation calls with HTTP 502 on every model."""

    def __init__(self, generations, failures):
        super().__init__(generations)
        self.failures = failures

    def __call__(self, request):
        import json

        if not request.url.path.endswith("/models") and self.failures:
            if json.loads(request.content)["messages"][0]["content"] == prompts.SYSTEM:
                self.failures -= 1
                return httpx.Response(502, json={"error": {"message": "upstream"}})
        return super().__call__(request)


def test_model_failure_is_retried_not_fatal(catalog_conn):
    fake = FlakyLlm([math_item(i) for i in range(5)], failures=100)
    result, *_ = run_set(catalog_conn, fake, SetLimits(max_requests_per_slot=2, max_calls_per_set=1000),
                         settings=LlmSettings(api_key=KEY, max_requests_per_day=10_000))
    assert all(r["status"] == "unavailable" for s in result.slots for r in s.requests)
    assert all(len(s.requests) == 2 for s in result.slots)  # every slot retried, the set was not aborted
    assert result.status == "partial" and result.stop_reason == "llm_unavailable"


def test_transient_failure_then_success_completes(catalog_conn):
    fake = FlakyLlm([math_item(i) for i in range(5)], failures=6)
    result, *_ = run_set(catalog_conn, fake)
    assert result.status == "complete"
    assert result.slots[0].requests[0]["status"] == "unavailable"
