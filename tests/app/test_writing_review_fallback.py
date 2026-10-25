"""T031 (ADR-029): writing reviews try the primary reviewer, then the qualified fallback; never the generator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from app.llm.client import OpenRouterClient
from app.llm.router import route, same_model
from app.llm.settings import LlmConfigurationError, LlmSettings
from app.llm.usage import MemoryUsageStore
from app.writing import generation, revalidation
from test_writing_generation import GOOD, KEY, REVIEW_OK, catalog, store  # noqa: F401  (fixtures)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "dev"))
import benchmark_writing_reviewers as bench  # noqa: E402

GEN, PRIMARY, FALLBACK = "gen/a:free", "rev/b:free", "rev/c:free"
REVIEWERS = (PRIMARY, FALLBACK)


def listing(*ids: str) -> dict:
    return {"data": [{"id": m, "context_length": 100000, "pricing": {"prompt": "0", "completion": "0"}} for m in ids]}


class Llm:
    """Generation by GEN; each reviewer answers per `behavior`: ok | 502 | truncated | <model_used to report>."""

    def __init__(self, behavior: dict[str, str] | None = None, listed=(GEN, PRIMARY, FALLBACK)):
        self.behavior, self.listed, self.calls = behavior or {}, listed, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=listing(*self.listed))
        body = json.loads(request.content)
        model = body["model"]
        review = body["messages"][0]["content"] == generation.REVIEW_SYSTEM
        self.calls.append(("review" if review else "generation", model))
        how = self.behavior.get(model, "ok") if review else "ok"
        if how == "502":
            return httpx.Response(502, json={"error": {"message": "upstream down"}})
        choice = {"message": {"content": json.dumps(REVIEW_OK if review else GOOD, ensure_ascii=False)}}
        if how == "truncated":
            choice["finish_reason"] = "length"
        used = how if how not in ("ok", "truncated") else model
        return httpx.Response(200, json={"id": f"g-{len(self.calls)}", "model": used, "choices": [choice],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0}})

    def reviews(self) -> list[str]:
        return [m for p, m in self.calls if p == "review"]


def client_for(fake: Llm, reviewers=REVIEWERS, **overrides) -> OpenRouterClient:
    settings = LlmSettings(api_key=KEY, free_models=(GEN,), writing_review_models=tuple(reviewers), **overrides)
    return OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def generate(catalog, store, fake: Llm, **kwargs):
    usage = MemoryUsageStore()
    outcome = generation.generate_exercise(client_for(fake, **kwargs), usage, catalog, store, "L2", "medium",
                                           ["EE03", "EE04"])
    return outcome, usage


def accepted_review(store) -> dict:
    return next(a for a in store.generation_attempts() if a["status"] == "accepted")["review"]


def test_primary_reviewer_succeeds(catalog, store):
    fake = Llm()
    outcome, _ = generate(catalog, store, fake)
    assert outcome.status == "accepted" and fake.reviews() == [PRIMARY]
    assert accepted_review(store)["reviewer_model"] == PRIMARY


@pytest.mark.parametrize("failure", ["502", "truncated"])
def test_failed_primary_falls_back_to_the_qualified_reviewer(catalog, store, failure):
    fake = Llm({PRIMARY: failure})
    outcome, usage = generate(catalog, store, fake)
    assert outcome.status == "accepted" and accepted_review(store)["reviewer_model"] == FALLBACK
    primary = [r for r in usage.records if r["purpose"] == "review" and r["model_requested"] == PRIMARY]
    # 502 is retried (bounded by OPENROUTER_MAX_RETRIES=2); a truncated reply is not retried on the same model.
    assert [r["error_kind"] for r in primary] == (["http_502"] * 3 if failure == "502" else ["truncated"])
    assert fake.reviews()[-1] == FALLBACK and GEN not in fake.reviews()
    fallback = [r for r in usage.records if r["purpose"] == "review" and r["model_requested"] == FALLBACK]
    assert [(r["status"], r["is_fallback"]) for r in fallback] == [("ok", True)]


def test_unlisted_primary_is_skipped_without_a_substitute(catalog, store):
    fake = Llm(listed=(GEN, FALLBACK, "other/z:free"))
    outcome, _ = generate(catalog, store, fake)
    assert outcome.status == "accepted" and fake.reviews() == [FALLBACK]  # other/z is never chosen


def test_all_reviewers_failing_stores_nothing_and_never_asks_the_generator(catalog, store):
    fake = Llm({PRIMARY: "502", FALLBACK: "truncated"})
    outcome, _ = generate(catalog, store, fake)
    assert outcome.status == "unavailable" and outcome.stop_reason == "llm_unavailable"
    assert set(fake.reviews()) == {PRIMARY, FALLBACK} and store.exercises() == []


def test_generator_in_the_reviewer_list_is_excluded(catalog, store):
    fake = Llm()
    outcome, _ = generate(catalog, store, fake, reviewers=(GEN, FALLBACK))
    assert outcome.status == "accepted" and fake.reviews() == [FALLBACK]


def test_a_variant_of_the_generator_is_excluded_too(catalog, store):
    fake = Llm(listed=(GEN, "gen/a:beta"))
    outcome, _ = generate(catalog, store, fake, reviewers=("gen/a:beta",))
    assert outcome.status == "unavailable" and fake.reviews() == [] and store.exercises() == []


def test_reviewer_resolving_to_the_generator_is_refused(catalog, store):
    fake = Llm({PRIMARY: GEN})  # OpenRouter reports the generator as the model that answered
    outcome, _ = generate(catalog, store, fake, reviewers=(PRIMARY,))
    assert outcome.status == "rejected" and store.exercises() == []
    assert any("W08: review not independent" in r for a in outcome.attempts for r in a.reasons)


def test_budget_exhausted_during_fallback_stops_without_storing(catalog, store):
    fake = Llm({PRIMARY: "502"})
    # 1 generation + 3 primary attempts use the day's budget; the fallback is refused before it is sent.
    outcome, usage = generate(catalog, store, fake, max_requests_per_day=4)
    assert outcome.status == "unavailable" and outcome.stop_reason == "daily_budget"
    fallback = [r["status"] for r in usage.records if r["model_requested"] == FALLBACK]
    assert fallback == ["budget_blocked"] and FALLBACK not in fake.reviews() and store.exercises() == []


def test_revalidation_reinstates_through_the_fallback(catalog, store):
    seeded = generation.generate_exercise(client_for(Llm()), MemoryUsageStore(), catalog, store, "L2", "medium",
                                          ["EE03", "EE04"])
    eid = seeded.exercise["exercise_id"]
    store.set_eligibility(eid, "quarantined", "test: review not independent", "RCA-004")
    fake = Llm({PRIMARY: "502"})
    result = revalidation.revalidate(client_for(fake), MemoryUsageStore(), catalog, store, eid, GEN)
    assert result["status"] == "passed" and result["reviewer_model"] == FALLBACK
    assert result["calls"] == 4 and store.eligibility(eid) == "eligible"  # 3 primary attempts within MAX_CALLS


def test_multiple_choice_routing_ignores_the_writing_reviewers():
    fake = Llm()
    client = client_for(fake)
    result = route(client, MemoryUsageStore(), [{"role": "user", "content": "x"}], purpose="review")
    assert result.status == "ok" and result.candidates == [GEN]


def test_same_model_and_settings():
    assert same_model("a/b:free", "a/b") and same_model("A/B:free", "a/b:beta")
    assert not same_model("a/b:free", "a/bc:free") and not same_model(None, "a/b")
    with pytest.raises(LlmConfigurationError):
        LlmSettings(api_key=KEY, writing_review_models=(PRIMARY, PRIMARY)).validate()


def test_candidate_discovery_follows_the_listing_not_a_fixed_list():
    def model(mid, ctx=200000, params=("response_format", "structured_outputs"), price="0"):
        return {"id": mid, "context_length": ctx, "supported_parameters": list(params),
                "pricing": {"prompt": price, "completion": price}}
    data = {"data": [model(GEN), model("gen/other:free"), model(PRIMARY), model("openrouter/free"),
                     model("x/code-model:free"), model("y/plain:free", params=("max_tokens",)),
                     model("z/short:free", ctx=8000), model("p/paid", price="0.001"),
                     model("v/big:free", ctx=500000), model("v/small:free", ctx=100000), model("w/mid:free", ctx=300000),
                     model("u/a:free"), model("t/b:free")]}
    fake = lambda request: httpx.Response(200, json=data)  # noqa: E731
    client = OpenRouterClient(LlmSettings(api_key=KEY, free_models=(GEN,), writing_review_models=(PRIMARY,)),
                              transport=httpx.MockTransport(fake))
    picked = bench.select_candidates(client, client.settings)
    # Other vendors first, longest context, one per vendor; the generator's vendor ("gen") ranks last.
    assert picked["candidates"] == ["v/big:free", "w/mid:free", "t/b:free"]
    reasons = {r["id"]: r["excluded"] for r in picked["listed"]}
    assert reasons[GEN] == "generator" and reasons[PRIMARY] == "primary reviewer"
    assert reasons["openrouter/free"] == "router, not a model" and reasons["x/code-model:free"] == "specialist model"
    assert reasons["y/plain:free"] == "no structured output" and reasons["z/short:free"] == "context too short"
    assert "p/paid" not in reasons  # only free models are considered
