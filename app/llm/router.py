"""Free-first model routing with budget enforcement (openrouter-model-routing skill, ADR-009).

Order: configured free models (if available), else discovered free models;
the paid model only when OPENROUTER_ALLOW_PAID=true and the daily USD budget
allows. Every HTTP attempt reserves budget through a `BudgetGate` before it is
sent (ADR-012). Every attempt — including budget-blocked ones — is recorded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.budget import BudgetGate
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
    usable = {k: m for k, m in models.items() if m.is_free and m.is_text_chat}
    configured = [m for m in client.settings.free_models if m in usable]
    if configured:
        return configured
    if client.settings.free_models:
        return []  # configured but none available: do not silently switch to arbitrary models
    discovered = sorted(usable.values(),
                        key=lambda m: (-(m.context_length or 0), m.id))
    return [m.id for m in discovered[:AUTO_FREE_LIMIT]]


def same_model(a: str | None, b: str | None) -> bool:
    """One model under two ids: OpenRouter variants (`:free`, `:beta`) share the model (T031, RCA-004)."""
    return bool(a and b) and a.split(":", 1)[0].lower() == b.split(":", 1)[0].lower()


def listed_free(client: OpenRouterClient, models: tuple[str, ...]) -> list[str]:
    """The given models, in order, that are currently listed as free text models (never a substitute)."""
    usable = {m.id for m in client.list_models() if m.is_free and m.is_text_chat}
    return [m for m in models if m in usable]


def supports(client: OpenRouterClient, model: str, parameter: str) -> bool:
    info = next((m for m in client.list_models() if m.id == model), None)
    return info is not None and parameter in info.supported_parameters


def reasoning_body(client: OpenRouterClient, model: str, purpose: str) -> dict[str, Any] | None:
    """Reduced reasoning for question generation only, and only for models that list `reasoning`."""
    effort = client.settings.generation_reasoning_effort
    if purpose != "generation" or not effort or not supports(client, model, "reasoning"):
        return None
    return {"reasoning": {"effort": effort}}


def route(client: OpenRouterClient, store: Store, messages: list[dict[str, str]], purpose: str,
          max_tokens: int | None = None, request_id: str | None = None,
          avoid: frozenset[str] = frozenset(), practice_set_id: str | None = None,
          gate: BudgetGate | None = None, exclude: frozenset[str] = frozenset(),
          models: tuple[str, ...] | None = None) -> RouteResult:
    """Route one request. Models in `avoid` are tried last (e.g. the generator, for a blind solve); models in
    `exclude`, or a variant of them, are never called (T029: an independent review must not fall back to the
    generator). `models` replaces the free list with an explicit ordered one (T031: writing reviewers).

    Pass one shared `gate` to every concurrent caller; without it a private gate is used.
    """
    ctx = UsageContext(request_id=request_id or f"req-{uuid.uuid4().hex[:16]}", purpose=purpose,
                       practice_set_id=practice_set_id)
    result = RouteResult(status="exhausted")
    settings = client.settings

    try:
        free = listed_free(client, models) if models else free_candidates(client)
    except AuthenticationError as exc:
        return RouteResult(status="auth_error", message=str(exc))
    except TransientError as exc:
        return RouteResult(status="discovery_error", message=str(exc))
    if purpose == "generation":
        # T012: some models are kept for blind solve and review but never generate questions.
        free = [m for m in free if m not in settings.generation_excluded_models]
    free = [m for m in free if not any(same_model(m, x) for x in exclude)]
    free = [m for m in free if m not in avoid] + [m for m in free if m in avoid]
    plan = [(m, "free") for m in free]
    if settings.allow_paid and settings.paid_model and not any(same_model(settings.paid_model, x) for x in exclude):
        plan.append((settings.paid_model, "paid"))
    result.candidates = [m for m, _ in plan]
    if not plan:
        result.message = "no qualified free model available and paid fallback disabled"
        return result

    gate = gate or BudgetGate(store, settings)
    for index, (model, tier) in enumerate(plan):
        is_fallback = index > 0
        reserved = [0]

        def reserve(tier: str = tier) -> bool:
            if gate.acquire(tier):
                reserved[0] += 1
                return True
            return False

        try:
            attempts = client.chat(model, messages, max_tokens=max_tokens, before_attempt=reserve,
                                   extra_body=reasoning_body(client, model, purpose))
        except AuthenticationError as exc:
            gate.settle(reserved[0], reserved[0] if tier == "paid" else 0)
            return RouteResult(status="auth_error", candidates=result.candidates, records=result.records,
                               message=str(exc))
        except PaymentRequiredError:
            record = blocked_record(model, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
            gate.settle(reserved[0], reserved[0] if tier == "paid" else 0)
            continue

        for attempt in attempts:
            record = to_record(attempt, ctx, tier, is_fallback)
            store.add(record)
            result.records.append(record)
        gate.settle(reserved[0], reserved[0] if tier == "paid" else 0)
        final = attempts[-1]
        if final.status == "budget_blocked":
            return RouteResult(status="budget_blocked", candidates=result.candidates, records=result.records,
                               message=gate.refusal or "budget reached")
        if final.status == "ok" and final.content:
            result.status, result.content, result.final, result.tier = "ok", final.content, final, tier
            return result
    result.message = result.message or "all candidate models failed"
    return result
