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
    assert sorted((r["practice_set_id"], r["slot"]) for r in store.rows) == [(result.practice_set_id, n) for n in range(1, 6)]


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
                                  SetLimits(max_calls_per_set=3, concurrency=1))
    sent = [r for r in usage.records if r["status"] != "budget_blocked"]
    assert len(sent) == 3
    assert result.status == "partial" and result.stop_reason == "set_call_limit"
    assert [s.status for s in result.slots] == ["accepted", "failed", "not_attempted", "not_attempted",
                                                "not_attempted"]


def test_daily_budget_stops_the_set(catalog_conn):
    settings = LlmSettings(api_key=KEY, max_requests_per_day=4)
    result, _, usage, _ = run_set(catalog_conn, FakeLlm([math_item(i) for i in range(5)]), SetLimits(concurrency=1),
                                  settings=settings)
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
    assert SetLimits.from_env({}).concurrency == 2
    assert SetLimits.from_env({"QUESTION_GENERATION_CONCURRENCY": "4"}).concurrency == 4
    for bad in ("0", "9"):
        with pytest.raises(ValueError):
            SetLimits.from_env({"QUESTION_GENERATION_CONCURRENCY": bad})
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

    def _respond(self, request):  # called with the FakeLlm lock held
        import json

        if not request.url.path.endswith("/models") and self.failures:
            if json.loads(request.content)["messages"][0]["content"] == prompts.SYSTEM:
                self.failures -= 1
                return httpx.Response(502, json={"error": {"message": "upstream"}})
        return super()._respond(request)


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


# ---------------------------------------------------------------- concurrency (T008, ADR-012)

import threading  # noqa: E402
import time  # noqa: E402

from app.llm.budget import BudgetGate  # noqa: E402


class SlowLlm(FakeLlm):
    """Adds latency outside the lock so calls from different workers overlap."""

    def __init__(self, generations, delay=0.02, delay_for=None):
        super().__init__(generations)
        self.delay, self.delay_for = delay, delay_for or {}

    def __call__(self, request):
        body = request.content.decode("utf-8") if request.content else ""
        extra = next((d for text, d in self.delay_for.items() if text in body), 0.0)
        time.sleep(self.delay + extra)
        return super().__call__(request)


def test_budget_gate_is_atomic_under_threads():
    gate = BudgetGate(MemoryUsageStore(), LlmSettings(api_key=KEY, max_requests_per_day=10))
    start = threading.Barrier(40)
    granted = []

    def worker():
        start.wait()
        granted.append(gate.acquire("free"))

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert granted.count(True) == 10 and gate.refusal == "daily request budget reached"


@pytest.mark.parametrize("daily,set_cap", [(7, 1000), (10_000, 7)])
def test_concurrent_set_never_exceeds_budgets(catalog_conn, daily, set_cap):
    settings = LlmSettings(api_key=KEY, max_requests_per_day=daily, max_retries=0)
    result, _, usage, _ = run_set(catalog_conn, SlowLlm([math_item(i) for i in range(5)]),
                                  SetLimits(max_calls_per_set=set_cap, concurrency=5), settings=settings)
    assert len([r for r in usage.records if r["status"] != "budget_blocked"]) == 7
    assert result.status == "partial"
    assert result.stop_reason == ("daily_budget" if daily == 7 else "set_call_limit")


class BarrierLlm(FakeLlm):
    """Every generation waits until all workers have generated, so no slot sees another's item in its bank."""

    def __init__(self, generations, parties):
        super().__init__(generations)
        self.barrier = threading.Barrier(parties, timeout=5)

    def __call__(self, request):
        body = request.content.decode("utf-8") if request.content else ""
        response = super().__call__(request)
        if "Formato de salida" in body:  # generation requests only
            try:
                self.barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return response


def test_simultaneous_duplicates_are_rejected_at_commit(catalog_conn):
    same = math_item(0)
    result, *_ = run_set(catalog_conn, BarrierLlm([same], parties=5), SetLimits(concurrency=5,
                                                                                  max_requests_per_slot=1))
    accepted = [s for s in result.slots if s.status == "accepted"]
    assert len(accepted) == 1
    commit_rejections = [r for r in result.rejection_reasons() if r.get("stage") == "set_commit"]
    assert len(commit_rejections) == 4
    assert all(r["reasons"][0].startswith("D01: exact duplicate") for r in commit_rejections)


def test_retries_are_isolated_per_slot(catalog_conn):
    class FailM02(FakeLlm):
        def _respond(self, request):
            body = request.content.decode("utf-8") if request.content else ""
            if "Usa los símbolos" in body and "Formato de salida" in body:
                return httpx.Response(502, json={"error": {"message": "upstream"}})
            return super()._respond(request)

    settings = LlmSettings(api_key=KEY, max_requests_per_day=10_000, max_retries=0)
    result, _, usage, _ = run_set(catalog_conn, FailM02([math_item(i) for i in range(5)]),
                                  SetLimits(concurrency=3), settings=settings)
    by_code = {code: [s for s in result.slots if s.objective_code == code] for code in ("M01", "M02")}
    assert all(s.status == "accepted" and len(s.requests) == 1 for s in by_code["M01"])
    assert all(s.status == "failed" and len(s.requests) == 3 for s in by_code["M02"])
    ids = [r["request_id"] for s in result.slots for r in s.requests]
    assert len(ids) == len(set(ids))  # no request is shared between slots
    for slot in result.slots:
        own = {r["request_id"] for r in slot.requests}
        assert all(rec["request_id"] in own for rec in usage.records
                   if rec["request_id"] in own)  # each usage record belongs to exactly one slot
    assert {rec["request_id"] for rec in usage.records} == set(ids)


def test_output_keeps_allocation_order_when_completion_order_differs(catalog_conn):
    # Slot 1 (first M01 evidencia) is slowest, so later slots finish first.
    fake = SlowLlm([math_item(i) for i in range(5)], delay=0.0, delay_for={"Lee números": 0.3})
    result, allocation, _, store = run_set(catalog_conn, fake, SetLimits(concurrency=5))
    planned = [(row["workbook_code"], s["evidence_id"]) for row in allocation for s in row["slots"]]
    assert [(s.objective_code, s.evidence_id) for s in result.slots] == planned
    assert [s.slot for s in result.slots] == [1, 2, 3, 4, 5]
    assert [o.evidence_id for o in result.outcomes] == [e for _, e in planned]
    completion = [r["slot"] for r in store.rows]
    assert completion != sorted(completion)  # completion order really differed
    assert all(s.item["curriculum_ref"]["evidencia_id"] == s.evidence_id for s in result.slots)
