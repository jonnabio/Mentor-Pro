"""OpenRouter integration with a mocked HTTP transport (no network)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import jsonschema
import pytest

from app.llm import connectivity
from app.llm.client import AuthenticationError, OpenRouterClient
from app.llm.router import free_candidates, route
from app.llm.settings import LlmConfigurationError, LlmSettings
from app.llm.usage import MemoryUsageStore, UsageStore

REPO = Path(__file__).resolve().parents[2]
USAGE_SCHEMA = json.loads((REPO / ".ace/schemas/question-engine/llm-usage-record.schema.json").read_text(encoding="utf-8"))
KEY = "sk-or-v1-test-key-not-real"

MODELS = {"data": [
    {"id": "acme/small:free", "name": "Small", "context_length": 8000,
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["max_tokens"]},
    {"id": "acme/big:free", "name": "Big", "context_length": 128000,
     "pricing": {"prompt": "0", "completion": "0"}},
    {"id": "acme/song", "name": "Song", "context_length": 1000000, "pricing": {"prompt": "0", "completion": "0"},
     "architecture": {"input_modalities": ["text"], "output_modalities": ["text", "audio"]}},
    {"id": "acme/pro", "name": "Pro", "context_length": 200000,
     "pricing": {"prompt": "0.000003", "completion": "0.000015"}},
]}


def completion(model, cost=0.0, tokens=(12, 3), content="listo", gen_id="gen-1"):
    usage = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1], "total_tokens": sum(tokens)}
    if cost is not None:
        usage["cost"] = cost
    return {"id": gen_id, "model": model, "provider": "AcmeHost",
            "choices": [{"message": {"role": "assistant", "content": content}}], "usage": usage}


class FakeOpenRouter:
    """Scripted responses per model: list of (status, body or None, headers)."""

    def __init__(self, scripts=None, generation=None):
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.generation = generation
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        if request.url.path.endswith("/generation"):
            if self.generation is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"data": self.generation})
        body = json.loads(request.content)
        assert body["usage"] == {"include": True}
        script = self.scripts.get(body["model"]) or [(200, completion(body["model"]), {})]
        status, payload, headers = script.pop(0) if len(script) > 1 else script[0]
        if status == "timeout":
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(status, json=payload, headers=headers)

    def chat_models(self):
        return [json.loads(r.content)["model"] for r in self.requests if r.url.path.endswith("/chat/completions")]


def make(fake, **overrides):
    settings = LlmSettings(api_key=KEY, **overrides)
    sleeps: list[float] = []
    client = OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=sleeps.append)
    return client, sleeps


MSG = [{"role": "user", "content": "hola"}]


# ---------------------------------------------------------------- settings

def test_settings_from_env_file(tmp_path, monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("OPENROUTER_"):
            monkeypatch.delenv(name)
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\nOPENROUTER_FREE_MODELS=acme/big:free, acme/small:free\n", encoding="utf-8")
    settings = LlmSettings.load(env)
    assert settings.base_url == "https://openrouter.ai/api/v1"
    assert settings.free_models == ("acme/big:free", "acme/small:free")
    assert settings.allow_paid is False and settings.max_usd_per_day == 0
    assert KEY not in repr(settings)


def test_missing_key_and_invalid_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(LlmConfigurationError, match="OPENROUTER_API_KEY"):
        LlmSettings.load(tmp_path / ".env")
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setenv("OPENROUTER_ALLOW_PAID", "true")
    with pytest.raises(LlmConfigurationError, match="PAID_MODEL"):
        LlmSettings.load(tmp_path / ".env")
    monkeypatch.setenv("OPENROUTER_ALLOW_PAID", "false")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://openrouter.ai/api/v1")
    with pytest.raises(LlmConfigurationError, match="https"):
        LlmSettings.load(tmp_path / ".env")


# ---------------------------------------------------------------- discovery

def test_discovery_identifies_free_models_and_caches():
    fake = FakeOpenRouter()
    client, _ = make(fake)
    models = {m.id: m for m in client.list_models()}
    assert models["acme/big:free"].is_free and not models["acme/pro"].is_free
    client.list_models()
    assert sum(r.url.path.endswith("/models") for r in fake.requests) == 1


def test_configured_free_model_takes_priority():
    client, _ = make(FakeOpenRouter(), free_models=("acme/small:free",))
    assert free_candidates(client) == ["acme/small:free"]


def test_auto_selection_prefers_larger_context():
    client, _ = make(FakeOpenRouter())
    assert free_candidates(client) == ["acme/big:free", "acme/small:free"]


def test_configured_paid_or_missing_model_is_not_treated_as_free():
    client, _ = make(FakeOpenRouter(), free_models=("acme/pro", "acme/gone:free"))
    assert free_candidates(client) == []


# ---------------------------------------------------------------- calls and usage

def test_successful_call_captures_usage():
    fake = FakeOpenRouter({"acme/big:free": [(200, completion("acme/big:free", cost=0.0, tokens=(20, 2)), {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "ok" and result.content == "listo" and result.tier == "free"
    rec = store.records[0]
    assert (rec["model_used"], rec["tokens_in"], rec["tokens_out"], rec["cost_usd"], rec["cost_source"]) == (
        "acme/big:free", 20, 2, 0.0, "provider_reported")
    assert rec["provider"] == "AcmeHost" and rec["latency_ms"] >= 0


def test_model_used_comes_from_response():
    fake = FakeOpenRouter({"acme/big:free": [(200, completion("acme/big-v2:free"), {})]})
    client, _ = make(fake)
    result = route(client, MemoryUsageStore(), MSG, "connectivity_test")
    assert result.final.model_requested == "acme/big:free" and result.final.model_used == "acme/big-v2:free"


def test_cost_falls_back_to_generation_endpoint():
    fake = FakeOpenRouter({"acme/big:free": [(200, completion("acme/big:free", cost=None), {})]},
                          generation={"total_cost": 0.000123, "tokens_prompt": 12, "tokens_completion": 3})
    client, _ = make(fake)
    final = route(client, MemoryUsageStore(), MSG, "connectivity_test").final
    assert (final.cost_usd, final.cost_source) == (0.000123, "generation_endpoint")


def test_missing_cost_is_null_not_zero():
    fake = FakeOpenRouter({"acme/big:free": [(200, completion("acme/big:free", cost=None), {})]})
    client, _ = make(fake)
    final = route(client, MemoryUsageStore(), MSG, "connectivity_test").final
    assert (final.cost_usd, final.cost_source) == (None, "missing")


def test_usage_records_match_schema():
    fake = FakeOpenRouter({"acme/big:free": [(429, {}, {"Retry-After": "2"}), (200, completion("acme/big:free"), {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    route(client, store, MSG, "connectivity_test")
    validator = jsonschema.Draft202012Validator(USAGE_SCHEMA, format_checker=jsonschema.FormatChecker())
    for record in store.records:
        assert not list(validator.iter_errors(record)), record
    assert KEY not in json.dumps(store.records)


# ---------------------------------------------------------------- retries and errors

def test_retries_429_with_retry_after_then_succeeds():
    fake = FakeOpenRouter({"acme/big:free": [(429, {}, {"Retry-After": "3"}), (200, completion("acme/big:free"), {})]})
    client, sleeps = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "ok"
    assert sleeps == [3.0]
    assert [r["status"] for r in store.records] == ["rate_limited", "ok"]


def test_retry_limit_then_next_free_model():
    fake = FakeOpenRouter({"acme/big:free": [(503, {}, {})]})
    client, sleeps = make(fake, max_retries=2)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert fake.chat_models() == ["acme/big:free"] * 3 + ["acme/small:free"]
    assert len(sleeps) == 2 and all(0 < s <= 30 for s in sleeps)
    assert result.status == "ok" and result.final.model_requested == "acme/small:free"
    assert store.records[-1]["is_fallback"] is True


def test_timeouts_are_retried_and_recorded():
    fake = FakeOpenRouter({"acme/big:free": [("timeout", None, {})], "acme/small:free": [("timeout", None, {})]})
    client, _ = make(fake, max_retries=1)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "exhausted"
    assert [r["status"] for r in store.records] == ["timeout"] * 4


def test_non_retryable_error_moves_to_next_model_without_retry():
    fake = FakeOpenRouter({"acme/big:free": [(400, {"error": {"message": "bad"}}, {})]})
    client, sleeps = make(fake)
    result = route(client, MemoryUsageStore(), MSG, "connectivity_test")
    assert fake.chat_models() == ["acme/big:free", "acme/small:free"] and sleeps == []
    assert result.status == "ok"


def test_invalid_response_body_is_an_error():
    fake = FakeOpenRouter({"acme/big:free": [(200, {"unexpected": True}, {})]})
    client, _ = make(fake, free_models=("acme/big:free",))
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "exhausted" and store.records[0]["error_kind"] == "invalid_response"


def test_auth_error_stops_immediately():
    fake = FakeOpenRouter({"acme/big:free": [(401, {"error": {"message": "no"}}, {})]})
    client, _ = make(fake)
    result = route(client, MemoryUsageStore(), MSG, "connectivity_test")
    assert result.status == "auth_error" and fake.chat_models() == ["acme/big:free"]
    assert KEY not in result.message


def test_auth_error_on_discovery():
    def reject(request):
        return httpx.Response(401, json={})
    client = OpenRouterClient(LlmSettings(api_key=KEY), transport=httpx.MockTransport(reject), sleep=lambda s: None)
    with pytest.raises(AuthenticationError):
        client.list_models()
    assert route(client, MemoryUsageStore(), MSG, "connectivity_test").status == "auth_error"


# ---------------------------------------------------------------- paid fallback and budgets

def failing_free():
    return {"acme/big:free": [(503, {}, {})], "acme/small:free": [(503, {}, {})]}


def test_paid_model_never_used_when_disabled():
    fake = FakeOpenRouter(failing_free())
    client, _ = make(fake, max_retries=0, paid_model="acme/pro", allow_paid=False)
    result = route(client, MemoryUsageStore(), MSG, "connectivity_test")
    assert result.status == "exhausted" and "acme/pro" not in fake.chat_models()


def test_paid_fallback_when_enabled_and_budgeted():
    fake = FakeOpenRouter({**failing_free(), "acme/pro": [(200, completion("acme/pro", cost=0.0021), {})]})
    client, _ = make(fake, max_retries=0, paid_model="acme/pro", allow_paid=True, max_usd_per_day=1.0)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "ok" and result.tier == "paid" and result.final.cost_usd == 0.0021
    assert store.records[-1]["tier"] == "paid" and store.records[-1]["is_fallback"] is True


def test_paid_fallback_blocked_by_zero_budget():
    fake = FakeOpenRouter(failing_free())
    client, _ = make(fake, max_retries=0, paid_model="acme/pro", allow_paid=True, max_usd_per_day=0.0)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "budget_blocked" and "acme/pro" not in fake.chat_models()
    assert store.records[-1]["status"] == "budget_blocked"


def test_paid_fallback_blocked_when_paid_cost_unknown():
    store = MemoryUsageStore()
    store.add({"status": "ok", "tier": "paid", "cost_usd": None})
    fake = FakeOpenRouter(failing_free())
    client, _ = make(fake, max_retries=0, paid_model="acme/pro", allow_paid=True, max_usd_per_day=5.0)
    assert route(client, store, MSG, "connectivity_test").status == "budget_blocked"


def test_daily_request_budget_blocks_calls():
    fake = FakeOpenRouter()
    client, _ = make(fake, max_requests_per_day=1)
    store = MemoryUsageStore()
    assert route(client, store, MSG, "connectivity_test").status == "ok"
    assert route(client, store, MSG, "connectivity_test").status == "budget_blocked"
    assert len(fake.chat_models()) == 1


def test_402_skips_model():
    fake = FakeOpenRouter({"acme/big:free": [(402, {}, {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert result.status == "ok" and store.records[0]["status"] == "budget_blocked"


# ---------------------------------------------------------------- connectivity check and storage

def test_connectivity_report_has_requested_fields():
    fake = FakeOpenRouter({"acme/big:free": [(200, completion("acme/big:free", cost=0.0, tokens=(15, 1)), {})]})
    client, _ = make(fake)
    report = connectivity.run(client.settings, MemoryUsageStore(), client=client)
    assert report["status"] == "ok"
    assert {k: report[k] for k in ("model_used", "tokens_in", "tokens_out", "cost_usd", "tier")} == {
        "model_used": "acme/big:free", "tokens_in": 15, "tokens_out": 1, "cost_usd": 0.0, "tier": "free"}
    assert report["models_listed"] == 4 and report["free_models_listed"] == 3


def test_connectivity_cli_without_key(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    empty_env = tmp_path / ".env"  # no key in the file either
    monkeypatch.setattr(connectivity, "LlmSettings",
                        type("S", (), {"load": staticmethod(lambda: LlmSettings.load(empty_env))}))
    assert connectivity.main(["--no-store"]) == 2
    assert "not_configured" in capsys.readouterr().out


def test_usage_store_in_postgres():
    sys.path.insert(0, str(REPO / "tests" / "curriculum"))
    from workbook_fixtures import TEST_DATABASE_URL

    import psycopg
    try:
        store = UsageStore(TEST_DATABASE_URL)
    except psycopg.OperationalError as exc:
        pytest.fail(f"PostgreSQL test database unreachable ({type(exc).__name__})")
    fake = FakeOpenRouter({"acme/big:free": [(429, {}, {}), (200, completion("acme/big:free", cost=0.0004), {})]})
    client, _ = make(fake)
    try:
        before = store.today()["requests"]
        result = route(client, store, MSG, "connectivity_test")
        assert result.status == "ok"
        assert store.today()["requests"] == before + 2
        with psycopg.connect(TEST_DATABASE_URL) as conn:
            rows = conn.execute("SELECT status, cost_usd, model_used FROM llm.usage_record WHERE request_id = %s "
                                "ORDER BY attempt", (result.records[0]["request_id"],)).fetchall()
        assert [r[0] for r in rows] == ["rate_limited", "ok"]
        assert float(rows[1][1]) == 0.0004 and rows[1][2] == "acme/big:free"
    finally:
        with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS llm CASCADE")


def test_api_key_never_reaches_frontend(synthetic_client):
    for path in ("/", "/static/app.js", "/api/subjects", "/api/openapi.json"):
        body = synthetic_client.get(path).text
        assert "OPENROUTER" not in body and "sk-or-" not in body


def test_non_text_output_models_are_never_candidates():
    client, _ = make(FakeOpenRouter())
    assert "acme/song" not in free_candidates(client)  # free but outputs audio
    client, _ = make(FakeOpenRouter(), free_models=("acme/song",))
    assert free_candidates(client) == []


# ---------------------------------------------------------------- live findings (T006)

def test_403_on_one_model_skips_it_instead_of_stopping():
    fake = FakeOpenRouter({"acme/big:free": [(403, {"error": {"message": "only available to ..."}}, {})]})
    client, _ = make(fake)
    result = route(client, MemoryUsageStore(), MSG, "connectivity_test")
    assert result.status == "ok" and result.final.model_requested == "acme/small:free"


def test_truncated_reply_is_invalid_output_and_moves_on():
    truncated = completion("acme/big:free", content="El usuario quiere...")
    truncated["choices"][0]["finish_reason"] = "length"
    fake = FakeOpenRouter({"acme/big:free": [(200, truncated, {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "connectivity_test")
    assert store.records[0]["status"] == "invalid_output" and store.records[0]["error_kind"] == "truncated"
    assert result.status == "ok" and result.final.model_requested == "acme/small:free"


# ---------------------------------------------------------------- generation output limit and truncation (T011)

def clean_env(monkeypatch):
    for name in list(__import__("os").environ):
        if name.startswith("OPENROUTER_"):
            monkeypatch.delenv(name)


def test_generation_limit_defaults_to_4000_and_is_configurable(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")
    settings = LlmSettings.load(env)
    assert settings.generation_max_tokens == 4000 and settings.max_tokens == 1024  # restored in T012
    monkeypatch.setenv("OPENROUTER_GENERATION_MAX_TOKENS", "8000")
    assert LlmSettings.load(env).generation_max_tokens == 8000


@pytest.mark.parametrize("value,ok", [("999", False), ("1000", True), ("16000", True), ("16001", False),
                                      ("abc", False)])
def test_generation_limit_boundaries(tmp_path, monkeypatch, value, ok):
    clean_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\nOPENROUTER_GENERATION_MAX_TOKENS={value}\n", encoding="utf-8")
    if ok:
        assert LlmSettings.load(env).generation_max_tokens == int(value)
    else:
        with pytest.raises(LlmConfigurationError):
            LlmSettings.load(env)


def reply(finish=None, native=None, tokens_out=3, content="listo"):
    body = completion("acme/big:free", tokens=(12, tokens_out), content=content)
    if finish is not None:
        body["choices"][0]["finish_reason"] = finish
    if native is not None:
        body["choices"][0]["native_finish_reason"] = native
    return body


@pytest.mark.parametrize("body,status,kind", [
    (reply(finish="length", tokens_out=500), "invalid_output", "truncated"),
    (reply(finish="stop", native="MAX_TOKENS", tokens_out=500), "invalid_output", "truncated"),
    (reply(native="max_output_tokens", tokens_out=500), "invalid_output", "truncated"),
    (reply(tokens_out=1000), "invalid_output", "truncated"),          # no reason, output at the limit
    (reply(tokens_out=999), "ok", None),                               # no reason, below the limit
    (reply(finish="stop", tokens_out=1000), "ok", None),               # explicit stop at exactly the limit
    (reply(finish="stop", content="   "), "invalid_output", "empty"),
])
def test_truncation_and_empty_replies_are_detected(body, status, kind):
    client, _ = make(FakeOpenRouter({"acme/big:free": [(200, body, {})]}))
    attempt = client.chat("acme/big:free", MSG, max_tokens=1000)[-1]
    assert (attempt.status, attempt.error_kind) == (status, kind)


def test_truncated_generation_falls_back_and_is_recorded():
    fake = FakeOpenRouter({"acme/big:free": [(200, reply(finish="length", tokens_out=6000), {})]})
    client, _ = make(fake)
    store = MemoryUsageStore()
    result = route(client, store, MSG, "generation", max_tokens=6000)
    assert result.status == "ok" and result.final.model_requested == "acme/small:free"
    first = store.records[0]
    assert (first["status"], first["error_kind"], first["tokens_out"]) == ("invalid_output", "truncated", 6000)
    assert [json.loads(r.content)["max_tokens"] for r in fake.requests
            if r.url.path.endswith("/chat/completions")] == [6000, 6000]


# ---------------------------------------------------------------- routing by purpose and reasoning control (T012)

REASONING_MODELS = {"data": [
    {"id": "acme/think:free", "name": "Think", "context_length": 200000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["max_tokens", "reasoning", "include_reasoning"]},
    {"id": "acme/vision:free", "name": "Vision", "context_length": 100000,
     "pricing": {"prompt": "0", "completion": "0"}, "supported_parameters": ["max_tokens", "reasoning"]},
    {"id": "acme/plain:free", "name": "Plain", "context_length": 50000, "pricing": {"prompt": "0", "completion": "0"},
     "supported_parameters": ["max_tokens"]},
]}


def sent(fake):
    return [(json.loads(r.content)["model"], json.loads(r.content).get("reasoning"))
            for r in fake.requests if r.url.path.endswith("/chat/completions")]


def test_settings_defaults_for_generation_routing(tmp_path, monkeypatch):
    clean_env(monkeypatch)
    env = tmp_path / ".env"
    env.write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")
    settings = LlmSettings.load(env)
    assert settings.generation_excluded_models == ("nvidia/nemotron-3.5-super-vl:free",)
    assert settings.generation_reasoning_effort == ""
    monkeypatch.setenv("OPENROUTER_GENERATION_REASONING_EFFORT", "LOW")
    assert LlmSettings.load(env).generation_reasoning_effort == "low"
    monkeypatch.setenv("OPENROUTER_GENERATION_REASONING_EFFORT", "none")
    with pytest.raises(LlmConfigurationError):
        LlmSettings.load(env)


def test_excluded_model_never_generates_but_still_solves_and_reviews(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "MODELS", REASONING_MODELS)
    fake = FakeOpenRouter({"acme/think:free": [(502, {}, {})]})
    client, _ = make(fake, free_models=("acme/think:free", "acme/vision:free", "acme/plain:free"),
                     generation_excluded_models=("acme/vision:free",), max_retries=0)
    gen = route(client, MemoryUsageStore(), MSG, "generation")
    assert gen.candidates == ["acme/think:free", "acme/plain:free"]
    assert gen.final.model_requested == "acme/plain:free"   # fallback skips the excluded model
    for purpose in ("independent_solve", "review"):
        assert "acme/vision:free" in route(client, MemoryUsageStore(), MSG, purpose).candidates


def test_reasoning_sent_only_for_generation_and_only_when_supported(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "MODELS", REASONING_MODELS)
    fake = FakeOpenRouter({"acme/think:free": [(502, {}, {})]})
    client, _ = make(fake, free_models=("acme/think:free", "acme/plain:free"), max_retries=0,
                     generation_reasoning_effort="low")
    route(client, MemoryUsageStore(), MSG, "generation")
    assert sent(fake) == [("acme/think:free", {"effort": "low"}), ("acme/plain:free", None)]
    fake.requests.clear()
    route(client, MemoryUsageStore(), MSG, "independent_solve")
    route(client, MemoryUsageStore(), MSG, "review")
    assert sent(fake) and all(reasoning is None for _, reasoning in sent(fake))


def test_no_reasoning_field_when_setting_is_empty(monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "MODELS", REASONING_MODELS)
    fake = FakeOpenRouter()
    client, _ = make(fake, free_models=("acme/think:free",))
    route(client, MemoryUsageStore(), MSG, "generation")
    body = json.loads(next(r for r in fake.requests if r.url.path.endswith("/chat/completions")).content)
    assert "reasoning" not in body and body["usage"] == {"include": True}
