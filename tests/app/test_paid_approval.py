"""T055: free-first generation, adult-approved paid generation, credit checks and cost tracking (mocked HTTP)."""

from __future__ import annotations

import copy
import json
import threading
from datetime import datetime, timezone

import httpx
import jsonschema
import pytest

from app.generation.pipeline import generate_one
from app.llm import costs, paid
from app.llm.client import OpenRouterClient, failure_category
from app.llm.router import route
from app.llm.settings import LlmSettings
from app.llm.usage import MemoryUsageStore
from test_generation import MATH_ITEM, bundle, catalog_conn  # noqa: F401  (fixture)
from test_openrouter import KEY, MODELS, MSG, USAGE_SCHEMA, FakeOpenRouter, completion, failing_free
from test_question_generation_fallback import FALLBACK, PRIMARY, SOLVER, Provider

PAID = "acme/pro"                     # listed at 0.000003 / 0.000015 USD per token in MODELS
MGMT = "sk-or-v1-management-not-real"
PAID_SETTINGS = {"paid_model": PAID, "allow_paid": True, "max_usd_per_day": 2.0, "paid_max_usd_per_operation": 1.0,
                 "max_retries": 0}


class Billing(FakeOpenRouter):
    """FakeOpenRouter plus GET /key and GET /credits (management key only)."""

    def __init__(self, scripts=None, key=(200, {"data": {"limit": None, "limit_remaining": None, "usage": 1.0}}),
                 credits=(200, {"data": {"total_credits": 10.0, "total_usage": 4.0}}), models=MODELS, **kw):
        super().__init__(scripts, **kw)
        self.key, self.credits, self.models = key, credits, models
        self.credit_auth: list[str] = []

    def __call__(self, request):
        path = request.url.path
        if path.endswith("/credits"):
            self.credit_auth.append(request.headers["Authorization"])
            return httpx.Response(self.credits[0], json=self.credits[1])
        if path.endswith("/key"):
            return httpx.Response(self.key[0], json=self.key[1])
        if path.endswith("/models"):
            self.requests.append(request)
            return httpx.Response(200, json=self.models)
        return super().__call__(request)


def make(fake, **overrides):
    settings = LlmSettings(api_key=KEY, **{**PAID_SETTINGS, **overrides})
    return OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def history(store=None, tokens=(1000, 400)):
    """Observed token history for the three workflow purposes (estimates are based on it)."""
    store = store or MemoryUsageStore()
    for purpose in paid.WORKFLOW:
        store.add({"call_id": f"h-{purpose}", "purpose": purpose, "status": "ok", "tier": "free", "cost_usd": 0.0,
                   "tokens_in": tokens[0], "tokens_out": tokens[1], "started_at": "2026-11-05T00:00:00Z",
                   "model_requested": "x:free"})
    return store


def approved(client, usage, store=None, ceiling=0.5, objective="M09"):
    store = store or paid.MemoryAuthorizationStore()
    out = paid.request_estimate(store, client, usage, "matematicas", objective, 1, 1)
    paid.approve(store, client.settings, out["authorization_id"], ceiling, "parent")
    return store, out


def grant_for(client, usage, ceiling=0.5, store=None):
    store, out = approved(client, usage, store, ceiling)
    return paid.open_grant(store, client, usage, out["authorization_id"], "matematicas", "M09"), store


# ---------------------------------------------------------------- 1, 13: free path unchanged

def test_1_free_success_offers_nothing_and_charges_nothing():
    fake = Billing()
    usage = MemoryUsageStore()
    result = route(make(fake), usage, MSG, "generation")
    assert result.status == "ok" and result.tier == "free" and result.paid_available is False
    assert PAID not in fake.chat_models() and all(r["tier"] == "free" for r in usage.records)


def test_1_free_success_with_a_grant_spends_nothing():
    fake = Billing()
    usage = history()
    client = make(fake)
    grant, store = grant_for(client, usage)
    assert route(client, usage, MSG, "generation", paid=grant).tier == "free"
    assert grant.finish()["spent_usd"] == 0 and PAID not in fake.chat_models()


def test_13_free_records_keep_the_schema_with_new_optional_fields():
    usage = MemoryUsageStore()
    route(make(Billing(), allow_paid=False), usage, MSG, "generation", subject="matematicas", objective_code="M09")
    validator = jsonschema.Draft202012Validator(USAGE_SCHEMA, format_checker=jsonschema.FormatChecker())
    for record in usage.records:
        assert list(validator.iter_errors(record)) == []
        assert record["subject"] == "matematicas" and record["authorization_id"] is None


# ---------------------------------------------------------------- 2, 3, 4: offer, decline, approve

def test_2_free_failure_offers_paid_generation_with_an_estimate():
    fake = Billing(failing_free())
    client, usage = make(fake), history()
    result = route(client, usage, MSG, "generation")
    assert result.status == "exhausted" and result.paid_available and PAID not in fake.chat_models()
    out = paid.request_estimate(paid.MemoryAuthorizationStore(), client, usage, "matematicas", "M09", 1, 1)
    est = out["estimate"]
    assert out["status"] == "pending" and est["status"] == "ok" and est["currency"] == "USD"
    assert est["pricing"]["usd_per_input_token"] == 0.000003 and est["pricing"]["fetched_at"]
    # Expected: one pass of 3 calls at 1000 in / 400 out tokens.
    assert est["expected_usd"] == pytest.approx(3 * (1000 * 3e-6 + 400 * 15e-6))
    gen = est["per_call"]["generation"]
    assert gen["input_tokens_max"] == 1250 and gen["output_tokens_max"] == client.settings.generation_max_tokens
    assert est["max_usd"] > est["expected_usd"] and "Maximum" in est["uncertainty"]
    assert est["balance"]["status"] == "balance_unknown" and est["balance"]["credits_check"] == "no_management_key"


def test_paid_generation_disabled_by_default_cannot_be_estimated():
    with pytest.raises(paid.PaidRefused, match="disabled"):
        paid.request_estimate(paid.MemoryAuthorizationStore(), make(Billing(), allow_paid=False), history(),
                              "matematicas", "M09", 1, 1)


def test_3_decline_means_no_paid_call():
    fake = Billing(failing_free())
    client, usage = make(fake), history()
    store = paid.MemoryAuthorizationStore()
    out = paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)
    assert paid.decline(store, out["authorization_id"], "parent")["status"] == "declined"
    with pytest.raises(paid.PaidRefused, match="not approved"):
        paid.open_grant(store, client, usage, out["authorization_id"], "matematicas", "M09")
    with pytest.raises(paid.PaidRefused):
        paid.approve(store, client.settings, out["authorization_id"], 0.5, "parent")  # decided once
    assert route(client, usage, MSG, "generation").status == "exhausted"
    assert PAID not in fake.chat_models()


def test_4_approval_allows_paid_calls_within_scope_and_is_consumed():
    fake = Billing({**failing_free(), PAID: [(200, completion(PAID, cost=0.0123), {})]})
    client, usage = make(fake), history()
    grant, store = grant_for(client, usage)
    result = route(client, usage, MSG, "generation", paid=grant, subject="matematicas", objective_code="M09")
    assert result.status == "ok" and result.tier == "paid"
    record = usage.records[-1]
    assert record["tier"] == "paid" and record["authorization_id"] == grant.authorization_id
    assert record["cost_usd"] == 0.0123 and record["objective_code"] == "M09"
    done = grant.finish()
    assert done["status"] == "consumed" and done["spent_usd"] == pytest.approx(0.0123)
    with pytest.raises(paid.PaidRefused, match="not approved"):  # never reusable
        paid.open_grant(store, client, usage, grant.authorization_id, "matematicas", "M09")


def test_approval_is_operation_specific_and_adult_only():
    client, usage = make(Billing()), history()
    store, out = approved(client, usage)
    with pytest.raises(paid.PaidRefused, match="not this run"):
        paid.open_grant(store, client, usage, out["authorization_id"], "matematicas", "M05")
    with pytest.raises(paid.PaidRefused, match="never the student"):
        paid.approve(store, client.settings, "PA-x", 0.5, "student")


def test_pending_requests_are_bounded():
    client, usage, store = make(Billing()), history(), paid.MemoryAuthorizationStore()
    for _ in range(paid.PENDING_LIMIT):
        paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)
    with pytest.raises(paid.PaidRefused, match="already pending"):
        paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)


def test_approvals_expire():
    now = [datetime(2026, 11, 5, tzinfo=timezone.utc)]
    store = paid.MemoryAuthorizationStore(clock=lambda: now[0])
    client, usage = make(Billing()), history()
    _, out = approved(client, usage, store)
    now[0] = now[0] + paid.APPROVAL_TTL
    assert store.get(out["authorization_id"])["status"] == "expired"
    assert store.claim(out["authorization_id"]) is False


# ---------------------------------------------------------------- 5, 6: balances

def test_5_insufficient_verified_credit_blocks_approval_and_execution():
    fake = Billing(credits=(200, {"data": {"total_credits": 10.0, "total_usage": 9.9}}))
    client, usage = make(fake, management_key=MGMT), history()
    store = paid.MemoryAuthorizationStore()
    out = paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)
    assert out["estimate"]["balance"]["status"] == "verified"
    assert out["estimate"]["balance"]["balance_usd"] == pytest.approx(0.1)
    assert fake.credit_auth == [f"Bearer {MGMT}"]                       # management key only on /credits
    with pytest.raises(paid.PaidRefused, match="insufficient verified credit"):
        paid.approve(store, client.settings, out["authorization_id"], 0.5, "parent")


def test_5_balance_dropping_after_approval_stops_before_any_paid_call():
    fake = Billing()
    client, usage = make(fake, management_key=MGMT), history()
    store, out = approved(client, usage)
    fake.credits = (200, {"data": {"total_credits": 10.0, "total_usage": 9.99}})
    with pytest.raises(paid.PaidRefused, match="insufficient verified credit"):
        paid.open_grant(store, client, usage, out["authorization_id"], "matematicas", "M09")
    assert store.get(out["authorization_id"])["status"] == "stopped" and PAID not in fake.chat_models()


def test_key_limit_is_reported_separately_and_also_limits_spending():
    fake = Billing(key=(200, {"data": {"limit": 5.0, "limit_remaining": 0.2}}))
    client, usage = make(fake, management_key=MGMT), history()
    store = paid.MemoryAuthorizationStore()
    est = paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)["estimate"]
    assert est["balance"]["balance_usd"] == 6.0 and est["balance"]["key_limit_remaining_usd"] == 0.2
    with pytest.raises(paid.PaidRefused, match="insufficient verified credit"):
        paid.approve(store, client.settings, est and store.all()[0]["authorization_id"], 0.5, "parent")


@pytest.mark.parametrize("credits, category", [((403, {"error": {"code": 403}}), "forbidden"),
                                               ((401, {}), "auth_invalid"), ((429, {}), "rate_limited"),
                                               ((503, {}), "provider_failure")])
def test_6_unknown_balance_is_reported_with_its_reason(credits, category):
    balance = paid.check_balance(make(Billing(credits=credits), management_key=MGMT))
    assert balance["status"] == "balance_unknown" and balance["balance_usd"] is None
    assert balance["credits_check"] == category and balance["key_check"] == "verified"


def test_management_key_is_never_in_repr_and_must_differ_from_the_app_key():
    settings = LlmSettings(api_key=KEY, management_key=MGMT)
    assert MGMT not in repr(settings) and KEY not in repr(settings)
    with pytest.raises(Exception, match="separate key"):
        LlmSettings(api_key=KEY, management_key=KEY).validate()


# ---------------------------------------------------------------- 7: error categories

@pytest.mark.parametrize("status, body, category", [
    (402, {"error": {"code": 402, "message": "Insufficient credits"}}, "insufficient_credits"),
    (402, {}, "payment_required"),
    (429, {"error": {"message": "insufficient credits"}}, "rate_limited"),   # never billing, whatever the text
    (401, {}, "auth_invalid"), (403, {}, "forbidden"), (500, {}, "provider_failure"), (503, {}, "provider_failure"),
    (400, {}, "request_rejected")])
def test_7_http_failures_are_categorized(status, body, category):
    assert failure_category(status, body=body) == category


def test_7_timeouts_are_provider_failures_not_billing():
    fake = FakeOpenRouter({"acme/big:free": [("timeout", None, {})], "acme/small:free": [("timeout", None, {})]})
    usage = MemoryUsageStore()
    route(make(fake), usage, MSG, "generation")
    assert {r["failure_category"] for r in usage.records} == {"provider_failure"}


def test_7_confirmed_insufficient_credits_stop_paid_execution():
    fake = Billing({**failing_free(), PAID: [(402, {"error": {"code": 402}}, {})]})
    client, usage = make(fake), history()
    grant, store = grant_for(client, usage)
    result = route(client, usage, MSG, "generation", paid=grant)
    assert result.status == "payment_required" and "nothing purchased" in result.message
    assert grant.stopped == "insufficient_credits" and usage.records[-1]["failure_category"] == "insufficient_credits"
    assert route(client, usage, MSG, "generation", paid=grant).status == "exhausted"   # no further paid call
    assert fake.chat_models().count(PAID) == 1
    done = grant.finish()
    assert done["status"] == "stopped" and done["spent_usd"] == 0


def test_7_rate_limited_paid_model_is_not_treated_as_out_of_funds():
    fake = Billing({**failing_free(), PAID: [(429, {}, {})]})
    client, usage = make(fake), history()
    grant, _ = grant_for(client, usage)
    assert route(client, usage, MSG, "generation", paid=grant).status == "exhausted"
    assert grant.stopped is None and usage.records[-1]["failure_category"] == "rate_limited"


# ---------------------------------------------------------------- 8: no invented estimate

@pytest.mark.parametrize("pricing", [None, {"prompt": "-1", "completion": "-1"}, {"prompt": "abc", "completion": "1"}])
def test_8_unavailable_prices_give_no_estimate_and_no_authorization(pricing):
    models = copy.deepcopy(MODELS)
    models["data"] = [m for m in models["data"] if m["id"] != PAID]
    if pricing:
        models["data"].append({"id": PAID, "pricing": pricing})
    store = paid.MemoryAuthorizationStore()
    out = paid.request_estimate(store, make(Billing(models=models)), history(), "matematicas", "M09", 1, 1)
    assert out["authorization_id"] is None and out["estimate"]["status"] == "estimate_unavailable"
    assert "expected_usd" not in out["estimate"] and store.all() == []


def test_8_no_token_history_gives_no_estimate():
    out = paid.request_estimate(paid.MemoryAuthorizationStore(), make(Billing()), MemoryUsageStore(),
                                "matematicas", "M09", 1, 1)
    assert out["estimate"]["status"] == "estimate_unavailable" and "token history" in out["estimate"]["reason"]


def test_prices_rising_after_approval_stop_the_run():
    fake = Billing()
    client, usage = make(fake), history()
    store, out = approved(client, usage)
    fake.models = copy.deepcopy(MODELS)
    next(m for m in fake.models["data"] if m["id"] == PAID)["pricing"]["completion"] = "0.00003"
    with pytest.raises(paid.PaidRefused, match="prices rose"):
        paid.open_grant(store, client, usage, out["authorization_id"], "matematicas", "M09")


# ---------------------------------------------------------------- 9, 10, 11: ceilings and concurrency

def test_9_ceiling_above_operation_cap_or_below_expected_is_refused():
    client, usage = make(Billing()), history()
    store = paid.MemoryAuthorizationStore()
    out = paid.request_estimate(store, client, usage, "matematicas", "M09", 1, 1)
    with pytest.raises(paid.PaidRefused, match="PAID_MAX_USD_PER_OPERATION"):
        paid.approve(store, client.settings, out["authorization_id"], 1.5, "parent")
    with pytest.raises(paid.PaidRefused, match="below the expected cost"):
        paid.approve(store, client.settings, out["authorization_id"], 0.001, "parent")


def test_9_paid_call_whose_worst_case_exceeds_the_ceiling_is_never_sent():
    fake = Billing({**failing_free()})
    client, usage = make(fake), history()
    # Expected cost of the operation is 0.027 USD; one generation call's worst case is 0.06375 USD.
    grant, _ = grant_for(client, usage, ceiling=0.03)
    result = route(client, usage, MSG, "generation", paid=grant, max_tokens=4000)
    assert result.status == "budget_blocked" and PAID not in fake.chat_models()
    assert usage.records[-1]["status"] == "budget_blocked" and usage.records[-1]["tier"] == "paid"


def test_10_retry_that_would_pass_the_ceiling_is_blocked():
    fake = Billing({**failing_free(), PAID: [(503, {}, {}), (200, completion(PAID, cost=0.01), {})]})
    client, usage = make(fake, max_retries=2), history()
    grant, _ = grant_for(client, usage, ceiling=0.1)    # room for one worst-case generation call only
    first = route(client, usage, MSG, "generation", paid=grant, max_tokens=4000)
    # The 503 attempt holds 0.06375; its retry would need another 0.06375 > 0.1, so it is never sent.
    assert first.status == "budget_blocked" and fake.chat_models().count(PAID) == 1
    assert grant.stopped == "authorization_ceiling"
    assert route(client, usage, MSG, "generation", paid=grant).status == "exhausted"   # no further paid call
    assert fake.chat_models().count(PAID) == 1
    # The failed 503 attempt has no reported cost: counted at its full reservation, never as zero.
    done = grant.finish()
    assert done["unknown_cost_calls"] == 1 and done["spent_usd"] == pytest.approx(0.06375)


def test_11_concurrent_reservations_never_exceed_the_ceiling():
    client, usage = make(Billing()), history()
    grant, store = grant_for(client, usage, ceiling=0.5)
    per_call = paid.call_ceiling(grant.pricing, grant.input_max["generation"], 4000)
    won: list[float] = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        amount = grant.reserve("generation", 4000) if not grant.stopped else None
        if amount:
            won.append(amount)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(won) == int(0.5 // per_call) and sum(won) <= 0.5


def test_11_only_one_paid_operation_runs_at_a_time():
    client, usage = make(Billing()), history()
    store = paid.MemoryAuthorizationStore()
    _, first = approved(client, usage, store)
    _, second = approved(client, usage, store)
    paid.open_grant(store, client, usage, first["authorization_id"], "matematicas", "M09")
    with pytest.raises(paid.PaidRefused, match="another paid operation"):
        paid.open_grant(store, client, usage, second["authorization_id"], "matematicas", "M09")


def test_11_daily_usd_budget_caps_paid_spending():
    client, usage = make(Billing(), max_usd_per_day=2.0), history()
    grant, _ = grant_for(client, usage, ceiling=0.5)
    grant.today_paid = lambda: 1.99                       # spent earlier today by another operation
    assert grant.reserve("generation", 4000) is None and grant.stopped == "authorization_ceiling"



# ---------------------------------------------------------------- 12: cost tracking and reconciliation

def test_12_report_separates_actual_unknown_and_never_sent():
    usage = MemoryUsageStore()
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    base = {"purpose": "generation", "status": "ok", "tier": "free", "model_requested": "m", "model_used": "m",
            "tokens_in": 10, "tokens_out": 5, "started_at": "2026-11-05T10:00:00Z", "subject": "matematicas",
            "practice_set_id": "seed-bb-matematicas-cd792836-ab12cd"}
    usage.add({**base, "call_id": "1", "cost_usd": 0.0})
    usage.add({**base, "call_id": "2", "cost_usd": 0.02, "tier": "paid", "purpose": "review"})
    usage.add({**base, "call_id": "3", "cost_usd": None, "tier": "paid"})
    usage.add({**base, "call_id": "4", "cost_usd": None, "status": "budget_blocked"})
    usage.add({**base, "call_id": "5", "cost_usd": 0.5, "started_at": "2026-10-31T10:00:00Z"})
    out = costs.report(usage, LlmSettings(api_key=KEY, max_usd_per_day=1.0), now=now)
    assert out["today"]["actual_usd"] == 0.02 and out["today"]["unknown_cost_paid_calls"] == 1
    assert out["today"]["calls_never_sent"] == 1 and out["today"]["calls_sent"] == 3
    assert out["month"]["calls_sent"] == 3                         # 31 Oct is another month
    assert set(out["month_by_purpose"]) == {"generation", "review"}
    assert list(out["month_by_batch"]) == ["bb-matematicas-cd792836"]
    assert out["budget"]["paid_usd_remaining"] == 0.98 and out["openrouter_credits"] == {"status": "not_checked"}


def test_12_reconcile_fills_unknown_costs_and_reports_mismatches():
    usage = MemoryUsageStore()
    base = {"purpose": "generation", "status": "ok", "tier": "paid", "model_requested": PAID,
            "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "cost_source": "missing"}
    usage.add({**base, "call_id": "a", "generation_id": "gen-a", "cost_usd": None})
    usage.add({**base, "call_id": "b", "generation_id": "gen-b", "cost_usd": 0.01, "cost_source": "provider_reported"})
    fake = FakeOpenRouter(generation={"total_cost": 0.02})
    out = costs.reconcile(usage, make(fake))
    assert out["filled_missing"] == 1 and len(out["mismatched"]) == 1
    assert usage.records[0]["cost_usd"] == 0.02 and usage.records[0]["cost_source"] == "generation_endpoint"
    assert usage.records[1]["cost_usd"] == 0.01                    # recorded costs are never overwritten


def test_12_reasoning_tokens_are_recorded():
    body = completion(PAID, cost=0.01)
    body["usage"]["completion_tokens_details"] = {"reasoning_tokens": 7}
    usage = MemoryUsageStore()
    route(make(Billing({"acme/big:free": [(200, body, {})]})), usage, MSG, "generation")
    assert usage.records[0]["reasoning_tokens"] == 7


# ---------------------------------------------------------------- 14: educational gates unchanged

def _paid_pipeline(catalog_conn, item):
    fake = Provider([item], {PRIMARY: "502", FALLBACK: "502"}, listed=(PRIMARY, FALLBACK, SOLVER, PAID))
    fake_models = {"data": [{"id": m, "pricing": {"prompt": "0", "completion": "0"}} for m in (PRIMARY, FALLBACK,
                                                                                              SOLVER)]
                   + [{"id": PAID, "pricing": {"prompt": "0.000003", "completion": "0.000015"}}]}
    original = fake._respond

    def respond(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json=fake_models)
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit": None, "limit_remaining": None}})
        return original(request)

    fake._respond = respond
    settings = LlmSettings(api_key=KEY, question_generation_models=(PRIMARY, FALLBACK), **PAID_SETTINGS)
    client = OpenRouterClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)
    usage = history()
    grant, _ = grant_for(client, usage, ceiling=1.0)
    return fake, usage, generate_one(client, usage, bundle(catalog_conn), "medium", paid=grant)


def test_14_paid_output_passes_the_same_validation_and_review(catalog_conn):
    fake, usage, outcome = _paid_pipeline(catalog_conn, MATH_ITEM)
    assert outcome.status == "accepted", outcome.reasons
    assert outcome.item["generation"]["model_requested"] == PAID
    assert "rubric" in outcome.validation                          # review still ran
    review = [r for r in usage.records if r["purpose"] == "review"]
    assert review and review[-1]["model_requested"] != PAID        # the reviewer is a free model, not the generator


def test_14_paid_output_with_a_wrong_key_is_still_rejected(catalog_conn):
    wrong = copy.deepcopy(MATH_ITEM)
    wrong["answer_key"] = "A"
    fake, usage, outcome = _paid_pipeline(catalog_conn, wrong)
    assert outcome.status == "rejected"


def test_unknown_reported_cost_never_counts_as_zero():
    fake = Billing({**failing_free(), PAID: [(200, completion(PAID, cost=None, gen_id=None), {})]})
    client, usage = make(fake), history()
    grant, _ = grant_for(client, usage)
    route(client, usage, MSG, "generation", paid=grant, max_tokens=4000)
    done = grant.finish()
    assert done["unknown_cost_calls"] == 1 and done["spent_usd"] > 0
    assert json.dumps(done)  # serialisable for the operator
