"""Free-first model routing with budget enforcement (openrouter-model-routing skill, ADR-009).

Order: configured free models (if available), else discovered free models;
the paid model only when OPENROUTER_ALLOW_PAID=true and the daily USD budget
allows. Every attempt — including budget-blocked ones — is recorded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.client import Attempt, AuthenticationError, OpenRouterClient, PaymentRequiredError, TransientError
from app.llm.usage import UsageContext, blocked_record, to_record

AUTO_FREE_LIMIT = 3  # discovered free models tried when none are configured


class Store(Protocol):
    def add(self, record: dict[str, Any]) -> None: ...
    def today(self) -> dict[str, Any]: ...


@dataclass
class RouteResult:
    status: str                       # ok | exhausted | budget_blocked | auth_error | discovery_error
    content: str | None = None
    final: Attempt | None = None
    tier: str | None = None
    candidates: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""


def free_candidates(client: OpenRouterClient) -> list[str]:
    """Configured free models that are currently listed and free, else top discovered free models."""
    models = {m.id: m for m in client.list_models()}
    configured = [m for m in client.settings.free_models if m in models and models[m].is_free]
    if configured:
        return configured
    if client.settings.free_models:
        return []  # configured but none available: do not silently switch to arbitrary models
    discovered = sorted((m for m in models.values() if m.is_free),
                        key=lambda m: (-(m.context_length or 0), m.id))
    return [m.id for m in discovered[:AUTO_FREE_LIMIT]]


def route(client: OpenRouterClient, store: Store, messages: list[dict[str, str]], purpose: str,
          max_tokens: int | None = None, request_id: str | None = None,
          avoid: frozenset[str] = frozenset()) -> RouteResult:
    """Route one request. Models in `avoid` are tried last (e.g. the generator, for a blind solve)."""
    ctx = UsageContext(request_id=request_id or f"req-{uuid.uuid4().hex[:16]}", purpose=purpose)
    result = RouteResult(status="exhausted")
    settings = client.settings

    try:
        free = free_candidates(client)
    except AuthenticationError as exc:
        return RouteResult(status="auth_error", message=str(exc))
    except TransientError as exc:
        return RouteResult(status="discovery_error", message=str(exc))
    free = [m for m in free if m not in avoid] + [m for m in free if m in avoid]
    plan = [(m, "free") for m in free]
    if settings.allow_paid and settings.paid_model:
        plan.append((settings.paid_model, "paid"))
    result.candidates = [m for m, _ in plan]
    if not plan:
        result.message = "no qualified free model available and paid fallback disabled"
        return result

    for index, (model, tier) in enumerate(plan):
        is_fallback = index > 0
        usage = store.today()
        if usage["requests"] >= settings.max_requests_per_day:
            record = blocked_record(model, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
            return RouteResult(status="budget_blocked", candidates=result.candidates, records=result.records,
                               message="daily request budget reached")
        if tier == "paid" and (usage["paid_unknown"] > 0 or usage["paid_usd"] >= settings.max_usd_per_day):
            record = blocked_record(model, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
            result.status, result.message = "budget_blocked", "paid fallback blocked by the daily USD budget"
            return result

        try:
            attempts = client.chat(model, messages, max_tokens=max_tokens)
        except AuthenticationError as exc:
            return RouteResult(status="auth_error", candidates=result.candidates, records=result.records,
                               message=str(exc))
        except PaymentRequiredError:
            record = blocked_record(model, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
            continue

        for attempt in attempts:
            record = to_record(attempt, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
        final = attempts[-1]
        if final.status == "ok" and final.content:
            result.status, result.content, result.final, result.tier = "ok", final.content, final, tier
            return result
    result.message = result.message or "all candidate models failed"
    return result
