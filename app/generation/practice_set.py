"""Validated practice set generation (T007, ADR-011).

Each allocation slot (objective, evidencia, difficulty from `app.allocation`)
is generated with `generate_one` and the same validation as a single question.
A slot gets at most `max_requests_per_slot` requests; a slot that never yields
an accepted item stays failed. The set is never padded and validation is
never bypassed. The set's accepted items form the duplicate bank, so in-set
near duplicates are rejected (D01).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from app.generation import prompts
from app.generation.grounding import build_grounding
from app.generation.pipeline import GenerationOutcome, generate_one
from app.llm.client import OpenRouterClient
from app.llm.router import Store


@dataclass(frozen=True)
class SetLimits:
    max_questions: int = 5
    max_requests_per_slot: int = 3
    max_calls_per_set: int = 80

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> SetLimits:
        limits = cls(
            max_questions=int(env.get("MENTOR_PRO_SET_MAX_QUESTIONS", cls.max_questions)),
            max_requests_per_slot=int(env.get("MENTOR_PRO_SET_MAX_REQUESTS_PER_SLOT", cls.max_requests_per_slot)),
            max_calls_per_set=int(env.get("MENTOR_PRO_SET_MAX_CALLS", cls.max_calls_per_set)),
        )
        if min(limits.max_questions, limits.max_requests_per_slot, limits.max_calls_per_set) < 1:
            raise ValueError("practice set limits must be positive")
        return limits


class SetBudgetStore:
    """Usage store wrapper that makes the router budget-block once the set's call limit is reached.

    The router already refuses to send a call when `today()["requests"]` reaches the daily budget,
    so reporting an exhausted budget here enforces the per-set limit before any call is sent.
    """

    def __init__(self, inner: Store, max_calls: int):
        self.inner, self.max_calls = inner, max_calls
        self.sent = 0
        self.limit_hit = False

    def add(self, record: dict[str, Any]) -> None:
        self.inner.add(record)
        if record["status"] != "budget_blocked":
            self.sent += 1

    def today(self) -> dict[str, Any]:
        usage = self.inner.today()
        if self.sent >= self.max_calls:
            self.limit_hit = True
            return {**usage, "requests": float("inf")}
        return usage


@dataclass
class SlotResult:
    slot: int
    objective_code: str
    evidence_id: str
    evidence_ordinal: int
    difficulty: str
    status: str = "not_attempted"            # accepted | failed | not_attempted
    item: dict[str, Any] | None = None
    request_id: str | None = None             # request that produced the accepted item
    requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PracticeSetResult:
    practice_set_id: str
    subject: str
    status: str                               # complete | partial
    stop_reason: str | None
    slots: list[SlotResult]
    outcomes: list[GenerationOutcome]
    duration_ms: int

    def summary(self) -> dict[str, Any]:
        per_request = [o.summary() for o in self.outcomes]
        generation_attempts = sum(len((o.validation or {}).get("attempts", [])) or (1 if o.summary()["calls"] else 0)
                                  for o in self.outcomes)
        accepted = sum(1 for s in self.slots if s.status == "accepted")
        return {
            "requested": len(self.slots),
            "accepted": accepted,
            "requests": len(self.outcomes),
            "generation_attempts": generation_attempts,
            "rejected_attempts": generation_attempts - accepted,
            "calls": sum(u["calls"] for u in per_request),
            "tokens_in": sum(u["tokens_in"] for u in per_request),
            "tokens_out": sum(u["tokens_out"] for u in per_request),
            "cost_usd": round(sum(u["cost_usd"] for u in per_request), 8),
            "cost_complete": all(u["cost_complete"] for u in per_request),
            "models_used": sorted({m for u in per_request for m in u["models_used"]}),
            "duration_ms": self.duration_ms,
        }

    def rejection_reasons(self) -> list[dict[str, Any]]:
        rows = []
        for slot in self.slots:
            for request in slot.requests:
                for attempt in request["attempts"]:
                    if attempt["verdict"] != "accept":
                        rows.append({"slot": slot.slot, "objective_code": slot.objective_code,
                                     "request_id": request["request_id"], **attempt})
        return rows


def _request_entry(outcome: GenerationOutcome) -> dict[str, Any]:
    attempts = (outcome.validation or {}).get("attempts") or [
        {"attempt": 1, "verdict": outcome.status, "reasons": outcome.reasons}]
    return {"request_id": outcome.request_id, "status": outcome.status, "attempts": attempts,
            "usage": outcome.summary()}


def generate_set(conn: psycopg.Connection, client: OpenRouterClient, usage_store: Store, generation_store: Any,
                 baseline: str, subject: str, allocation: list[dict[str, Any]], limits: SetLimits,
                 practice_set_id: str | None = None,
                 clock: Callable[[], float] = time.monotonic) -> PracticeSetResult:
    """Generate every slot of `allocation` (the `allocation` list returned by `allocate`)."""
    set_id = practice_set_id or f"set-{uuid.uuid4().hex[:16]}"
    slots = [SlotResult(s["slot"], row["workbook_code"], s["evidence_id"], s["evidence_ordinal"], s["difficulty"])
             for row in allocation for s in row["slots"]]
    if len(slots) > limits.max_questions:
        raise ValueError(f"{len(slots)} questions requested; the limit is {limits.max_questions}")

    budget = SetBudgetStore(usage_store, limits.max_calls_per_set)
    started = clock()
    outcomes: list[GenerationOutcome] = []
    accepted_items: list[dict[str, Any]] = []
    stop_reason: str | None = None

    for slot in slots:
        if stop_reason in ("set_call_limit", "daily_budget"):
            break
        bundle = build_grounding(conn, baseline, subject, slot.objective_code, slot.evidence_ordinal)
        for _ in range(limits.max_requests_per_slot):
            bank = accepted_items + generation_store.recent_stems(slot.evidence_id)
            outcome = generate_one(client, budget, bundle, slot.difficulty, bank=bank, practice_set_id=set_id)
            generation_store.add(outcome, baseline, slot.difficulty, prompts.GENERATION_PROMPT_VERSION,
                                 practice_set_id=set_id, slot=slot.slot)
            outcomes.append(outcome)
            slot.requests.append(_request_entry(outcome))
            if outcome.status == "accepted":
                slot.status, slot.item, slot.request_id = "accepted", outcome.item, outcome.request_id
                accepted_items.append(outcome.item)
                break
            if outcome.status == "unavailable" and any("budget_blocked" in r for r in outcome.reasons):
                stop_reason = "set_call_limit" if budget.limit_hit else "daily_budget"
                break
            # Other unavailable outcomes (model errors, truncation) count as a failed request and are retried.
        if slot.status != "accepted":
            slot.status = "failed"
            if stop_reason is None:
                unavailable = all(r["status"] == "unavailable" for r in slot.requests)
                stop_reason = "llm_unavailable" if unavailable else "slot_retries_exhausted"

    complete = all(s.status == "accepted" for s in slots)
    return PracticeSetResult(set_id, subject, "complete" if complete else "partial",
                             None if complete else stop_reason, slots, outcomes, int((clock() - started) * 1000))


def coverage(allocation: list[dict[str, Any]], result: PracticeSetResult) -> list[dict[str, Any]]:
    """Planned versus accepted questions per objective and evidencia."""
    rows = []
    for row in allocation:
        for evidence_id in dict.fromkeys(s["evidence_id"] for s in row["slots"]):
            planned = [s for s in result.slots if s.objective_code == row["workbook_code"]
                       and s.evidence_id == evidence_id]
            rows.append({"objective_code": row["workbook_code"], "evidence_id": evidence_id,
                         "planned": len(planned), "accepted": sum(1 for s in planned if s.status == "accepted")})
    return rows
