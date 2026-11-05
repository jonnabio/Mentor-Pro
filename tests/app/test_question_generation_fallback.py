"""T053: question generation tries the configured primary, then the fallback on provider failure only."""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from app.generation import prompts
from app.generation.pipeline import generate_one
from app.llm.client import OpenRouterClient
from app.llm.settings import LlmConfigurationError, LlmSettings
from app.llm.usage import MemoryUsageStore
from test_generation import KEY, MATH_ITEM, PROPERTY_ITEM, FakeLlm, bundle, catalog_conn  # noqa: F401  (fixture)

PRIMARY, FALLBACK, SOLVER = "primary/a:free", "fallback/b:free", "solver/c:free"


def listing(*ids: str) -> dict:
    # Context lengths order discovery for solve and review: PRIMARY, FALLBACK, SOLVER.
    sizes = {PRIMARY: 300000, FALLBACK: 200000, SOLVER: 100000}
    return {"data": [{"id": m, "context_length": sizes.get(m, 50000), "pricing": {"prompt": "0", "completion": "0"}}
                     for m in ids]}


class Provider(FakeLlm):
    """FakeLlm whose generation calls fail per model: `timeout`, `502` or `429`; other purposes answer normally."""

    def __init__(self, generations, failures=None, listed=(PRIMARY, FALLBACK, SOLVER), **kwargs):
        super().__init__(generations, **kwargs)
        self.failures, self.listed, self.http = failures or {}, listed, []

    def _respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=listing(*self.listed))
        body = json.loads(request.content)
        self.http.append(body["model"])
        how = self.failures.get(body["model"]) if body["messages"][0]["content"] == prompts.SYSTEM else None
        if how == "timeout":
            self.calls.append(("generation", body["model"]))
            raise httpx.ReadTimeout("no response", request=request)
        if how in ("502", "429"):
            self.calls.append(("generation", body["model"]))
            return httpx.Response(int(how), json={"error": {"message": "provider unavailable"}})
        return super()._respond(request)

    def generations_by(self) -> list[str]:
        return [m for p, m in self.calls if p == "generation"]


def client_for(fake: Provider, models=(PRIMARY, FALLBACK), **overrides) -> OpenRouterClient:
    settings = LlmSettings(api_key=KEY, question_generation_models=tuple(models), **overrides)
    return OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def generation_records(usage: MemoryUsageStore) -> list[tuple[str, str, bool]]:
    return [(r["model_requested"], r["status"], r["is_fallback"]) for r in usage.records if r["purpose"] == "generation"]


def test_primary_succeeds_and_the_fallback_is_never_called(catalog_conn):
    fake, usage = Provider([MATH_ITEM]), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "accepted", outcome.reasons
    assert fake.generations_by() == [PRIMARY]                             # never generates; may still review
    assert generation_records(usage) == [(PRIMARY, "ok", False)]
    assert outcome.item["generation"]["model_requested"] == PRIMARY


@pytest.mark.parametrize("failure, kind", [("timeout", "timeout"), ("502", "http_502"), ("429", "http_429")])
def test_primary_provider_failure_falls_back_after_its_bounded_retries(catalog_conn, failure, kind):
    fake, usage = Provider([MATH_ITEM], {PRIMARY: failure}), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "accepted", outcome.reasons
    # OPENROUTER_MAX_RETRIES=2: three primary attempts, then one fallback call; no third model.
    assert fake.generations_by() == [PRIMARY] * 3 + [FALLBACK]
    records = [r for r in usage.records if r["purpose"] == "generation"]
    assert [(r["model_requested"], r["is_fallback"]) for r in records] == [(PRIMARY, False)] * 3 + [(FALLBACK, True)]
    assert {r["error_kind"] for r in records[:3]} == {kind} and records[3]["status"] == "ok"
    assert outcome.item["generation"]["model_requested"] == FALLBACK     # provenance names the fallback
    assert all(r["latency_ms"] is not None for r in records)


def test_both_models_failing_is_a_bounded_unavailable_outcome(catalog_conn):
    fake, usage = Provider([MATH_ITEM], {PRIMARY: "timeout", FALLBACK: "502"}), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "unavailable"
    assert outcome.reasons == ["generation exhausted: all candidate models failed"]
    assert fake.generations_by() == [PRIMARY] * 3 + [FALLBACK] * 3        # 2 models x 3 attempts, then stop
    assert len(fake.http) == 6 and SOLVER not in fake.http                # never a third, unconfigured model


def test_fallback_output_rejected_by_validation_does_not_switch_models(catalog_conn):
    wrong = copy.deepcopy(MATH_ITEM)
    wrong["answer_key"] = "A"                                             # the proof gives B: deterministic reject
    fake, usage = Provider([wrong], {PRIMARY: "timeout"}), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "rejected"
    # Each revision round routes primary then fallback again; validation never moves on to another model.
    assert set(fake.generations_by()) == {PRIMARY, FALLBACK}
    assert all(m in (PRIMARY, FALLBACK) for m in fake.http if m != SOLVER)
    assert [p for p, _ in fake.calls if p != "generation"] == []          # rejected before solve and review


def test_every_provider_request_is_recorded_and_counted_against_the_daily_budget(catalog_conn):
    fake, usage = Provider([MATH_ITEM], {PRIMARY: "timeout"}), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    sent = [r for r in usage.records if r["status"] != "budget_blocked"]
    assert outcome.status == "accepted" and len(sent) == len(fake.http) == usage.today()["requests"]

    fake, usage = Provider([MATH_ITEM], {PRIMARY: "timeout"}), MemoryUsageStore()
    outcome = generate_one(client_for(fake, max_requests_per_day=2), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "unavailable" and len(fake.http) == 2       # the budget stops the fallback too
    assert [r["status"] for r in usage.records] == ["timeout", "timeout", "budget_blocked"]


def test_independent_solve_still_avoids_the_model_that_generated(catalog_conn):
    fake, usage = Provider([PROPERTY_ITEM], {PRIMARY: "timeout"}, solve="D"), MemoryUsageStore()
    outcome = generate_one(client_for(fake), usage, bundle(catalog_conn), "medium")
    assert outcome.status == "accepted", outcome.reasons
    assert outcome.validation["independent_solve"]["agrees_with_key"] is True
    solved_by = next(m for p, m in fake.calls if p == "solve")
    reviewed_by = next(m for p, m in fake.calls if p == "rubric")
    assert FALLBACK not in (solved_by, reviewed_by)                       # the fallback generated this item


def test_without_the_setting_generation_uses_the_free_list_as_before(catalog_conn):
    fake, usage = Provider([MATH_ITEM], {PRIMARY: "timeout"}), MemoryUsageStore()
    settings = LlmSettings(api_key=KEY, free_models=(PRIMARY,))
    client = OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)
    outcome = generate_one(client, usage, bundle(catalog_conn), "medium")
    assert outcome.status == "unavailable" and fake.generations_by() == [PRIMARY] * 3  # unchanged: no fallback


def test_an_unlisted_fallback_is_named_not_substituted(catalog_conn):
    fake = Provider([MATH_ITEM], {PRIMARY: "timeout"}, listed=(PRIMARY, SOLVER))
    outcome = generate_one(client_for(fake), MemoryUsageStore(), bundle(catalog_conn), "medium")
    assert outcome.status == "unavailable" and fake.generations_by() == [PRIMARY] * 3
    assert outcome.reasons == [f"generation exhausted: all candidate models failed (not listed as free: {FALLBACK})"]


def test_settings_load_and_refuse_invalid_lists(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("OPENROUTER_QUESTION_GENERATION_MODELS", f" {PRIMARY} , {FALLBACK} ")
    assert LlmSettings.load(tmp_path / "none.env").question_generation_models == (PRIMARY, FALLBACK)
    monkeypatch.delenv("OPENROUTER_QUESTION_GENERATION_MODELS")
    assert LlmSettings.load(tmp_path / "none.env").question_generation_models == ()
    with pytest.raises(LlmConfigurationError):
        LlmSettings(api_key=KEY, question_generation_models=(PRIMARY, PRIMARY)).validate()
    with pytest.raises(LlmConfigurationError):
        LlmSettings(api_key=KEY, question_generation_models=(PRIMARY, "nvidia/nemotron-3.5-super-vl:free")).validate()
