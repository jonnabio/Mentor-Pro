"""Free-generation reliability (T064): rate limits, cooldown, truncation recovery and bounded retries.

Mocked OpenRouter only; no network, no paid model.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.generation import prompts
from app.generation.practice_set import SetLimits
from app.llm.client import MAX_BACKOFF_S, OpenRouterClient, retry_after_seconds
from app.llm.cooldown import MAX_COOLDOWN_S, ModelCooldown
from app.llm.router import route
from app.llm.settings import GENERATION_MAX_TOKENS_MAX, LlmConfigurationError, LlmSettings
from app.llm.usage import MemoryUsageStore
from test_generation import FakeLlm, catalog_conn  # noqa: F401  (fixture)
from test_openrouter import KEY, MSG, FakeOpenRouter, completion, make, reply
from test_practice_set import math_item, run_set

LIMITED = (429, {"error": {"message": "rate limited"}}, {})


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ---------------------------------------------------------------- client back-off


def test_backoff_is_bounded_exponential_with_jitter():
    client, sleeps = make(FakeOpenRouter({"acme/big:free": [LIMITED]}), max_retries=3)
    attempts = client.chat("acme/big:free", MSG)
    assert [a.status for a in attempts] == ["rate_limited"] * 4
    assert len(sleeps) == 3 and all(0 < s <= MAX_BACKOFF_S for s in sleeps)
    assert [int(s) for s in sleeps] == [1, 2, 4]              # 2^(n-1) plus jitter below 0.5 s
    assert all(s - int(s) < 0.5 for s in sleeps)


def test_short_retry_after_is_honoured():
    fake = FakeOpenRouter({"acme/big:free": [(429, {}, {"Retry-After": "7"}), (200, completion("acme/big:free"), {})]})
    client, sleeps = make(fake)
    attempts = client.chat("acme/big:free", MSG)
    assert [a.status for a in attempts] == ["rate_limited", "ok"] and sleeps == [7.0]
    assert attempts[0].retry_after_s == 7.0


def test_long_retry_after_is_not_slept_through():
    client, sleeps = make(FakeOpenRouter({"acme/big:free": [(429, {}, {"Retry-After": "900"})]}), max_retries=3)
    attempts = client.chat("acme/big:free", MSG)
    assert len(attempts) == 1 and sleeps == []                # one request, no 15-minute sleep
    assert attempts[0].retry_after_s == 900.0


@pytest.mark.parametrize("value,expected", [("12", 12.0), ("0", 0.0), ("-3", 0.0), (None, None),
                                            ("Wed, 21 Oct 2026 07:28:00 GMT", None)])
def test_retry_after_parsing(value, expected):
    assert retry_after_seconds(value) == expected


# ---------------------------------------------------------------- cooldown


def test_cooldown_bounds_and_expiry():
    clock = Clock()
    cooldown = ModelCooldown(clock)
    cooldown.start("m", 10)
    cooldown.start("m", 5)                                    # a shorter cooldown never shortens it
    assert cooldown.remaining("m") == 10
    cooldown.start("x", 10 * MAX_COOLDOWN_S)
    assert cooldown.remaining("x") == MAX_COOLDOWN_S
    clock.now += 11
    assert cooldown.remaining("m") == 0


def test_rate_limited_model_is_cooled_and_skipped_on_the_next_request():
    fake = FakeOpenRouter({"acme/big:free": [LIMITED]})
    client, _ = make(fake, max_retries=1)
    cooldown = ModelCooldown(Clock())
    first = route(client, MemoryUsageStore(), MSG, "generation", cooldown=cooldown)
    assert first.status == "ok" and first.final.model_requested == "acme/small:free"
    assert fake.chat_models() == ["acme/big:free", "acme/big:free", "acme/small:free"]
    assert cooldown.remaining("acme/big:free") == client.settings.rate_limit_cooldown_s

    second = route(client, MemoryUsageStore(), MSG, "generation", cooldown=cooldown)
    assert second.status == "ok"
    assert fake.chat_models()[3:] == ["acme/small:free"]      # no request to the cooling model
    assert "rate limited, skipped" not in second.message


def test_cooldown_follows_a_longer_retry_after():
    fake = FakeOpenRouter({"acme/big:free": [(429, {}, {"Retry-After": "1200"})]})
    client, _ = make(fake)
    cooldown = ModelCooldown(Clock())
    route(client, MemoryUsageStore(), MSG, "generation", cooldown=cooldown)
    assert cooldown.remaining("acme/big:free") == 1200


def test_every_model_cooling_sends_nothing_and_says_so():
    fake = FakeOpenRouter()
    client, _ = make(fake)
    cooldown = ModelCooldown(Clock())
    for model in ("acme/big:free", "acme/small:free"):
        cooldown.start(model, 60)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "generation", cooldown=cooldown)
    assert result.status == "rate_limited" and "cooling down" in result.message
    assert fake.chat_models() == [] and store.records == []


def test_cooldown_expires_and_the_model_is_tried_again():
    clock = Clock()
    fake = FakeOpenRouter()
    client, _ = make(fake)
    cooldown = ModelCooldown(clock)
    cooldown.start("acme/big:free", 60)
    route(client, MemoryUsageStore(), MSG, "generation", cooldown=cooldown)
    clock.now += 61
    route(client, MemoryUsageStore(), MSG, "generation", cooldown=cooldown)
    assert fake.chat_models() == ["acme/small:free", "acme/big:free"]


def test_paid_model_is_never_added_by_rate_limits():
    fake = FakeOpenRouter({"acme/big:free": [LIMITED], "acme/small:free": [LIMITED]})
    client, _ = make(fake, max_retries=0, paid_model="acme/pro", allow_paid=True, max_usd_per_day=1.0)
    result = route(client, MemoryUsageStore(), MSG, "generation", cooldown=ModelCooldown(Clock()))
    assert result.status == "exhausted" and "acme/pro" not in fake.chat_models()
    assert result.paid_available is True                      # an offer only, never an automatic switch


def test_cooldown_setting_is_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("OPENROUTER_RATE_LIMIT_COOLDOWN_S", "120")
    assert LlmSettings.load(tmp_path / ".env").rate_limit_cooldown_s == 120
    monkeypatch.setenv("OPENROUTER_RATE_LIMIT_COOLDOWN_S", "99999")
    with pytest.raises(LlmConfigurationError):
        LlmSettings.load(tmp_path / ".env")


# ---------------------------------------------------------------- truncation


def test_truncation_retry_is_single_and_bounded():
    fake = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=9000), {})],
                           "acme/small:free": [(200, reply(finish="length", tokens_out=9000), {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "generation", max_tokens=9000, truncation_retry=True)
    sent = [(json.loads(r.content)["model"], json.loads(r.content)["max_tokens"]) for r in fake.requests
            if r.url.path.endswith("/chat/completions")]
    assert sent == [("acme/big:free", 9000), ("acme/big:free", GENERATION_MAX_TOKENS_MAX), ("acme/small:free", 9000)]
    assert result.status == "exhausted" and result.content is None    # nothing truncated is ever returned
    assert all(r["error_kind"] == "truncated" for r in store.records)


def test_truncation_recovered_by_the_larger_limit():
    fake = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=4000), {}),
                                             (200, completion("acme/big:free", content="{}"), {})]})
    client, _ = make(fake)
    result = route(client, MemoryUsageStore(), MSG, "generation", max_tokens=4000, truncation_retry=True)
    assert result.status == "ok" and result.final.model_requested == "acme/big:free"


def test_truncation_retry_only_when_opted_in_and_below_the_ceiling():
    fake = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=500), {})]})
    client, _ = make(fake)
    route(client, MemoryUsageStore(), MSG, "generation", max_tokens=500)  # not opted in (writing)
    assert fake.chat_models() == ["acme/big:free", "acme/small:free"]
    fake2 = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=16000), {})]})
    client2, _ = make(fake2)
    route(client2, MemoryUsageStore(), MSG, "generation", max_tokens=GENERATION_MAX_TOKENS_MAX,
          truncation_retry=True)
    assert fake2.chat_models() == ["acme/big:free", "acme/small:free"]


def test_truncation_retry_respects_the_daily_budget():
    fake = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=4000), {})]})
    client, _ = make(fake, max_requests_per_day=1)
    result = route(client, MemoryUsageStore(), MSG, "generation", max_tokens=4000, truncation_retry=True)
    assert result.status == "budget_blocked" and fake.chat_models() == ["acme/big:free"]


# ---------------------------------------------------------------- whole-session generation


class RateLimitedLlm(FakeLlm):
    """Every generation call is rate limited by every model."""

    def _respond(self, request):
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            if body["messages"][0]["content"] == prompts.SYSTEM:
                self.calls.append(("generation", body["model"]))
                return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return super()._respond(request)


def test_rate_limited_set_stops_early_without_partial_items(catalog_conn):
    fake = RateLimitedLlm([math_item(i) for i in range(5)])
    settings = LlmSettings(api_key=KEY, max_retries=1, max_requests_per_day=10_000)
    result, _, usage, store = run_set(catalog_conn, fake, SetLimits(max_requests_per_slot=3, max_calls_per_set=80,
                                                                    concurrency=1), settings=settings)
    assert result.status == "partial" and result.stop_reason == "provider_rate_limited"
    assert all(s.item is None for s in result.slots)
    # The first slot reaches both models (with one retry each); everything after is skipped while they cool.
    assert len(fake.calls) == 4
    # The slot's second request finds every model cooling and stops the set; later slots never call anything.
    assert [len(s.requests) for s in result.slots] == [2, 0, 0, 0, 0]


def test_malformed_output_never_enters_a_set(catalog_conn):
    fake = FakeLlm(['{"stem": "incompleto"', "no json at all"])
    result, *_ = run_set(catalog_conn, fake, SetLimits(max_requests_per_slot=1, max_calls_per_set=40),
                         settings=LlmSettings(api_key=KEY, max_requests_per_day=10_000))
    assert all(s.status == "failed" and s.item is None for s in result.slots)
    assert result.status == "partial"
