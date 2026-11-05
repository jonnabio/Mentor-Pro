"""Free-first model routing with budget enforcement (openrouter-model-routing skill, ADR-009).

Order: configured free models (if available), else discovered free models.
T055: the paid model is never added automatically. It is tried last only when the
caller passes a `PaidGrant` (an adult's operation-specific approval, app.llm.paid)
and OPENROUTER_ALLOW_PAID=true; each paid attempt then reserves its worst-case cost
against the approval ceiling and the daily USD budget. Without a grant an exhausted
result says whether paid generation could be requested (`paid_available`).
Every HTTP attempt reserves budget through a `BudgetGate` before it is sent
(ADR-012). Every attempt — including budget-blocked ones — is recorded.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.budget import BudgetGate
from app.llm.client import Attempt, AuthenticationError, OpenRouterClient, PaymentRequiredError, TransientError
from app.llm.usage import UsageContext, to_record

AUTO_FREE_LIMIT = 3  # discovered free models tried when none are configured


class Store(Protocol):
    def add(self, record: dict[str, Any]) -> None: ...
    def today(self) -> dict[str, Any]: ...


@dataclass
class RouteResult:
    status: str  # ok | exhausted | budget_blocked | auth_error | discovery_error | payment_required
    content: str | None = None
    final: Attempt | None = None
    tier: str | None = None
    candidates: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    paid_available: bool = False      # T055: free failed; a paid model could be requested with adult approval


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
          models: tuple[str, ...] | None = None, paid: Any = None, subject: str | None = None,
          objective_code: str | None = None) -> RouteResult:
    """Route one request. Models in `avoid` are tried last (e.g. the generator, for a blind solve); models in
    `exclude`, or a variant of them, are never called (T029: an independent review must not fall back to the
    generator). `models` replaces the free list with an explicit ordered one (T031: writing reviewers).

    Pass one shared `gate` to every concurrent caller; without it a private gate is used.
    `paid` is a claimed `app.llm.paid.PaidGrant`; without it no paid call is ever made (T055).
    """
    ctx = UsageContext(request_id=request_id or f"req-{uuid.uuid4().hex[:16]}", purpose=purpose,
                       practice_set_id=practice_set_id, subject=subject, objective_code=objective_code,
                       authorization_id=getattr(paid, "authorization_id", None))
    result = RouteResult(status="exhausted")
    settings = client.settings

    try:
        free = listed_free(client, models) if models else free_candidates(client)
    except AuthenticationError as exc:
        return RouteResult(status="auth_error", message=str(exc))
    except TransientError as exc:
        return RouteResult(status="discovery_error", message=str(exc))
    # T053: an explicitly listed model that is not currently listed as free is skipped, never substituted, and
    # named in the failure message (a delisted fallback must not disappear silently).
    unlisted = [m for m in models or () if m not in free]
    if purpose == "generation":
        # T012: some models are kept for blind solve and review but never generate questions.
        free = [m for m in free if m not in settings.generation_excluded_models]
    free = [m for m in free if not any(same_model(m, x) for x in exclude)]
    free = [m for m in free if m not in avoid] + [m for m in free if m in avoid]
    plan = [(m, "free") for m in free]
    paid_possible = bool(settings.allow_paid and settings.paid_model
                         and not any(same_model(settings.paid_model, x) for x in exclude))
    if paid is not None and paid_possible and paid.model == settings.paid_model and not paid.stopped:
        plan.append((settings.paid_model, "paid"))
    result.candidates = [m for m, _ in plan]
    if not plan:
        result.paid_available = paid_possible and paid is None
        result.message = "no qualified free model available" + (
            "; paid generation available with adult approval" if result.paid_available
            else "; no paid generation without an approved authorization")
        if unlisted:
            result.message += f" (not listed as free: {', '.join(unlisted)})"
        return result

    gate = gate or BudgetGate(store, settings)
    call_max_tokens = max_tokens or settings.max_tokens
    for index, (model, tier) in enumerate(plan):
        is_fallback = index > 0
        reserved = [0]
        holds: list[float] = []  # paid only: worst-case USD reserved for each sent attempt, in order

        def reserve(tier: str = tier) -> bool:
            if tier == "paid":
                amount = paid.reserve(purpose, call_max_tokens)
                if amount is None:
                    gate.refusal = "paid authorization ceiling or daily USD budget reached"
                    return False
                if not gate.acquire(tier):
                    paid.settle(amount, 0.0)  # never sent
                    return False
                holds.append(amount)
            elif not gate.acquire(tier):
                return False
            reserved[0] += 1
            return True

        try:
            attempts = client.chat(model, messages, max_tokens=max_tokens, before_attempt=reserve,
                                   extra_body=reasoning_body(client, model, purpose))
        except (AuthenticationError, PaymentRequiredError) as exc:
            sent = list(exc.attempts)   # every request of this call was sent: record each one
            for number, attempt in enumerate(sent):
                record = to_record(attempt, ctx, tier, is_fallback)
                if tier == "paid" and number < len(holds):
                    # A 401/402 response is not a charged completion; earlier retries keep their liability.
                    record["liability_usd"] = 0.0 if attempt is exc.attempt else holds[number]
                store.add(record)
                result.records.append(record)
            if tier == "paid" and holds:
                for amount in holds[:-1]:   # earlier retries of this call: cost unknown, counted in full
                    paid.settle(amount, None)
                paid.settle(holds[-1], 0.0)
            gate.settle(reserved[0], reserved[0] if tier == "paid" else 0)
            if isinstance(exc, AuthenticationError):
                return RouteResult(status="auth_error", candidates=result.candidates, records=result.records,
                                   message=str(exc))
            if tier == "paid":
                # Stop paid execution and tell the operator; credits are never purchased automatically.
                paid.stop(exc.attempt.failure_category if exc.attempt else "payment_required")
                return RouteResult(status="payment_required", candidates=result.candidates, records=result.records,
                                   message=f"{exc}; paid generation stopped, nothing purchased")
            continue

        sent_index = 0
        for attempt in attempts:
            record = to_record(attempt, ctx, tier, is_fallback)
            if tier == "paid" and attempt.status != "budget_blocked":
                # The worst-case reservation stays on the record as the daily-budget liability until the
                # actual cost is known (paid_exposure); it is never added to a known cost.
                record["liability_usd"] = holds[sent_index]
                sent_index += 1
            store.add(record)
            result.records.append(record)
        if tier == "paid":
            sent = [a for a in attempts if a.status != "budget_blocked"]
            for amount, attempt in zip(holds, sent):
                paid.settle(amount, attempt.cost_usd)  # None (unknown) is counted at the full reservation
        gate.settle(reserved[0], reserved[0] if tier == "paid" else 0)
        final = attempts[-1]
        if final.status == "budget_blocked":
            return RouteResult(status="budget_blocked", candidates=result.candidates, records=result.records,
                               message=gate.refusal or "budget reached")
        if final.status == "ok" and final.content:
            result.status, result.content, result.final, result.tier = "ok", final.content, final, tier
            return result
    result.message = result.message or "all candidate models failed"
    if paid is None and paid_possible:
        result.paid_available = True
        result.message += "; paid generation available with adult approval"
    if unlisted:
        result.message += f" (not listed as free: {', '.join(unlisted)})"
    return result
