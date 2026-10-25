"""RCA-004 / T029: the W08 review of a writing exercise must come from a model other than its generator."""

from __future__ import annotations

import httpx

from app.llm.client import Attempt
from app.llm.router import RouteResult
from app.llm.usage import MemoryUsageStore
from app.writing import editing, generation
from test_writing_editing import FakeLlm as EditFake, SPELLING, client_for as edit_client
from test_writing_generation import GOOD, FakeLlm, catalog, client_for, run, store  # noqa: F401  (fixtures)
from test_writing_revalidation import Down


def test_reviewer_outage_never_falls_back_to_the_generator(catalog, store):
    down = Down(FakeLlm([GOOD]))
    usage = MemoryUsageStore()
    outcome = generation.generate_exercise(client_for(down), usage, catalog, store, "L2", "medium", ["EE03", "EE04"])
    assert outcome.status == "unavailable" and outcome.exercise is None
    reviews = [r for r in usage.records if r["purpose"] == "review"]
    assert reviews and {r["model_requested"] for r in reviews} == {"rev/b:free"}  # the generator is never asked
    assert all(r["status"] == "error" for r in reviews)  # failed reviewer attempts are preserved
    assert store.exercises() == [] and [a["status"] for a in store.generation_attempts()] == ["unavailable"]


def test_exhausted_budget_before_the_review_stores_nothing(catalog, store):
    outcome, usage = run(catalog, store, FakeLlm([GOOD]), max_requests_per_day=1)
    assert outcome.status == "unavailable" and outcome.stop_reason == "daily_budget"
    assert [r["status"] for r in usage.records if r["purpose"] == "review"] == ["budget_blocked"]
    assert store.exercises() == []


def test_l1_reviews_exclude_the_generator_too(catalog, store):
    down = Down(EditFake([SPELLING]))
    outcome = editing.generate_editing_exercise(edit_client(down), MemoryUsageStore(), catalog, store, "spelling")
    assert outcome.status == "unavailable" and down.models.count("gen/a:free") == 1  # generation only


def test_same_model_review_helper():
    final = Attempt("gen/a:free", 1, "ok", 10, model_used="gen/a:free")
    same = RouteResult(status="ok", content="{}", final=final, records=[], message="")
    assert generation.same_model_review("gen/a:free", same)
    assert generation.same_model_review("gen/a:beta", same)  # T031: a variant id is the same model
    assert generation.same_model_review("other/x:free", same) is None
    assert generation.same_model_review(None, same) is None
