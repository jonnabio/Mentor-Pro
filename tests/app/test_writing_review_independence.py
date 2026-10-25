"""RCA-004: the W08 review of a writing exercise must come from a model other than its generator."""

from __future__ import annotations

import httpx

from app.llm.router import RouteResult
from app.writing import generation
from test_writing_generation import GOOD, FakeLlm, catalog, run, store  # noqa: F401  (fixtures)


class ReviewerDown(FakeLlm):
    """The only other free model answers 502, so route() falls back to the generator for the review."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/models") and b'"rev/b:free"' in request.content:
            return httpx.Response(502, json={"error": {"message": "upstream down"}})
        return super().__call__(request)


def test_a_review_by_the_generator_is_refused(catalog, store):
    fake = ReviewerDown([GOOD])
    outcome, _ = run(catalog, store, fake)
    # Each attempt is refused; the retries then use up the exercise's call budget (unavailable), never accepted.
    assert outcome.status in ("rejected", "unavailable") and outcome.exercise is None
    w08 = [r for a in outcome.attempts for r in a.reasons if r.startswith("W08")]
    assert w08 and all("review not independent: gen/a:free" in r for r in w08)
    assert any(p == "review" and m == "gen/a:free" for p, m in fake.calls)  # the fallback did happen
    assert store.exercises() == [] and "accepted" not in {a["status"] for a in store.generation_attempts()}


def test_same_model_review_helper():
    class Final:
        model_used = "gen/a:free"

    same = RouteResult(status="ok", content="{}", final=Final(), records=[], message="")
    assert generation.same_model_review("gen/a:free", same)
    assert generation.same_model_review("other/x:free", same) is None
    assert generation.same_model_review(None, same) is None
