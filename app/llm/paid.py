"""Paid question generation: estimate, adult approval, per-operation ceiling (T055, ADR-009 amendment).

Free-first routing never switches to the paid model by itself. A paid call is possible only inside one
operation that an authorized adult (parent or administrator) approved, through this operator CLI, after
seeing an estimate:

1. `estimate`: current OpenRouter prices for the configured paid model, observed token history, the whole
   workflow (generation and revision, independent solve, review, bounded retries), and the key limit and
   account balance where they can be verified. Stored as a `pending` authorization (bounded, expiring).
2. `approve` / `decline`: an operation-specific decision with a USD ceiling. Approval is refused when the
   estimate is unavailable, the ceiling is below the expected cost or above
   OPENROUTER_PAID_MAX_USD_PER_OPERATION, or a verified balance or key allowance is below the ceiling.
3. `seed_bank run ... --paid-authorization ID` claims the approval once (`approved` -> `in_use`, only one
   operation at a time), re-checks prices, and every paid HTTP attempt first reserves its worst-case cost
   against the ceiling and the daily USD budget in one atomic step. The approval ends `consumed` or
   `stopped`; it never carries over to another operation.

The student never sees any of this: there is no student-facing endpoint. Management keys are read-only,
server-side, and never printed.

    python -m app.llm.paid estimate --subject matematicas --objective M09 [--questions 1]
    python -m app.llm.paid approve --authorization PA-... --max-usd 0.50 --approver parent
    python -m app.llm.paid decline --authorization PA-... --approver parent
    python -m app.llm.paid list
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

PENDING_LIMIT = 3                      # no unbounded pending authorization requests
PENDING_TTL = timedelta(hours=24)
APPROVAL_TTL = timedelta(hours=24)     # an approval not used within a day expires
INPUT_MARGIN = 1.25                    # on the largest observed prompt size
HISTORY_DAYS = 30
WORKFLOW = ("generation", "independent_solve", "review")
APPROVERS = ("parent", "administrator")
MAX_QUESTIONS = 5


class PaidRefused(RuntimeError):
    """A paid step was refused; nothing was sent and no money was committed."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _price(value: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None   # OpenRouter lists variable-price routers as -1


# ---------------------------------------------------------------- pricing, balance, estimate

@dataclass(frozen=True)
class Pricing:
    model: str
    prompt: float          # USD per input token
    completion: float      # USD per output token
    request: float         # USD per request
    reasoning: float       # USD per internal reasoning token (0 if not separately priced)
    fetched_at: str

    @property
    def output(self) -> float:
        """Reasoning tokens are counted in the output; price them at the higher of the two rates."""
        return max(self.completion, self.reasoning)

    def as_dict(self) -> dict[str, Any]:
        return {"model": self.model, "usd_per_input_token": self.prompt, "usd_per_output_token": self.completion,
                "usd_per_request": self.request, "usd_per_reasoning_token": self.reasoning,
                "fetched_at": self.fetched_at}


def current_pricing(client: Any, model: str) -> tuple[Pricing | None, str | None]:
    """Fresh prices from GET /models; (None, reason) when unavailable. Never a hardcoded price."""
    try:
        info = next((m for m in client.list_models(refresh=True) if m.id == model), None)
    except Exception as exc:  # noqa: BLE001 - any discovery failure means "unavailable", never a guess
        return None, f"model listing failed ({type(exc).__name__})"
    if info is None:
        return None, f"{model} is not listed by OpenRouter"
    prompt, completion = _price(info.prompt_price), _price(info.completion_price)
    if prompt is None or completion is None:
        return None, f"{model} has no usable token prices"
    if prompt == 0 and completion == 0:
        return None, f"{model} is listed as free; it is not a paid model"
    return Pricing(model, prompt, completion, _price(info.request_price) or 0.0,
                   _price(info.reasoning_price) or 0.0, _iso(_now())), None


def check_balance(client: Any) -> dict[str, Any]:
    """Key allowance (GET /key, app key) and account balance (GET /credits, management key only).

    A key's remaining limit is not the account balance; both are reported separately. Anything that cannot be
    read is `balance_unknown`, with the failure category (401, 403, 429 and timeouts are not "no funds").
    """
    out: dict[str, Any] = {"status": "balance_unknown", "balance_usd": None, "key_limit_usd": None,
                           "key_limit_remaining_usd": None, "key_check": None, "credits_check": None}
    key, problem = client.key_info()
    if key is not None:
        out["key_check"] = "verified"
        out["key_limit_usd"] = key.get("limit")
        out["key_limit_remaining_usd"] = key.get("limit_remaining")
    else:
        out["key_check"] = problem
    management = client.settings.management_key
    if not management:
        out["credits_check"] = "no_management_key"
        return out
    credits, problem = client.account_credits(management)
    if credits is not None and isinstance(credits.get("total_credits"), (int, float)) \
            and isinstance(credits.get("total_usage"), (int, float)):
        out["status"] = "verified"
        out["balance_usd"] = round(credits["total_credits"] - credits["total_usage"], 8)
        out["credits_check"] = "verified"
    else:
        out["credits_check"] = problem or "invalid_output"
    return out


def spend_limit(balance: dict[str, Any]) -> float | None:
    """The smallest verified amount that can still be spent (balance, key allowance), or None if none is known."""
    limits = [balance["balance_usd"]] if balance.get("status") == "verified" else []
    if isinstance(balance.get("key_limit_remaining_usd"), (int, float)):
        limits.append(balance["key_limit_remaining_usd"])
    return min(limits) if limits else None


def purpose_max_tokens(settings: Any) -> dict[str, int]:
    from app.generation.pipeline import RUBRIC_MAX_TOKENS, SOLVE_MAX_TOKENS
    return {"generation": settings.generation_max_tokens, "independent_solve": SOLVE_MAX_TOKENS,
            "review": RUBRIC_MAX_TOKENS}


def call_ceiling(pricing: Pricing, input_tokens: int, max_tokens: int) -> float:
    """Worst-case USD of one HTTP attempt: estimated input plus the full output allowance."""
    return input_tokens * pricing.prompt + max_tokens * pricing.output + pricing.request


def estimate(settings: Any, pricing: Pricing | None, pricing_problem: str | None, profile: dict[str, dict],
             balance: dict[str, Any], questions: int, requests_per_question: int) -> dict[str, Any]:
    """Whole-operation estimate. Returns status `estimate_unavailable` rather than inventing a number."""
    base = {"currency": "USD", "model": settings.paid_model, "questions": questions, "balance": balance}
    if pricing is None:
        return {**base, "status": "estimate_unavailable", "reason": pricing_problem}
    missing = [p for p in WORKFLOW if not profile.get(p, {}).get("calls")]
    if missing:
        return {**base, "status": "estimate_unavailable", "pricing": pricing.as_dict(),
                "reason": f"no observed token history for {', '.join(missing)} in the last {HISTORY_DAYS} days"}
    limits = purpose_max_tokens(settings)
    from app.generation.pipeline import MAX_GENERATION_ATTEMPTS
    per_call, expected_pass, worst_pass = {}, 0.0, 0.0
    for purpose in WORKFLOW:
        stats = profile[purpose]
        input_max = math.ceil(stats["max_in"] * INPUT_MARGIN)
        expected = stats["mean_in"] * pricing.prompt + stats["mean_out"] * pricing.output + pricing.request
        worst = call_ceiling(pricing, input_max, limits[purpose])
        per_call[purpose] = {"input_tokens_expected": round(stats["mean_in"]), "input_tokens_max": input_max,
                             "output_tokens_expected": round(stats["mean_out"]), "output_tokens_max": limits[purpose],
                             "usd_expected": round(expected, 6), "usd_max": round(worst, 6)}
        expected_pass += expected
        worst_pass += worst
    http_attempts = settings.max_retries + 1
    passes = requests_per_question * MAX_GENERATION_ATTEMPTS
    expected_usd = questions * expected_pass
    max_usd = questions * passes * http_attempts * worst_pass
    return {**base, "status": "ok", "pricing": pricing.as_dict(), "per_call": per_call,
            "calls_expected": questions * len(WORKFLOW),
            "calls_max": questions * passes * len(WORKFLOW) * http_attempts,
            "expected_usd": round(expected_usd, 6), "max_usd": round(max_usd, 6),
            "operation_cap_usd": settings.paid_max_usd_per_operation,
            "daily_cap_usd": settings.max_usd_per_day,
            "uncertainty": (
                "Expected = one pass (generation, independent solve, review) at the mean observed token counts. "
                f"Maximum = {requests_per_question} request(s) x {MAX_GENERATION_ATTEMPTS} generation attempts "
                f"(revision included) x 3 calls x {http_attempts} HTTP attempts, each at {INPUT_MARGIN:g} x the "
                "largest observed prompt and the full output limit. Actual cost is what OpenRouter reports; "
                "free models are still tried first, so part of the work may cost nothing. Prices can change "
                "before the run (re-checked at start)."),
            }


# ---------------------------------------------------------------- authorization store

# The table is created by migration L001 (app/llm/migrations.py).

_LIVE = ("pending", "approved", "in_use")


class MemoryAuthorizationStore:
    """Same contract as AuthorizationStore, for tests (one lock makes every transition atomic)."""

    def __init__(self, clock: Callable[[], datetime] = _now):
        self.rows: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.clock = clock

    def _expire(self) -> None:
        for row in self.rows.values():
            if row["status"] in _LIVE and row["expires_at"] <= self.clock():
                row["status"], row["stop_reason"] = "expired", row["stop_reason"] or "expired"

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._expire()
            if sum(r["status"] == "pending" for r in self.rows.values()) >= PENDING_LIMIT:
                raise PaidRefused(f"{PENDING_LIMIT} authorizations are already pending; decide or let them expire")
            row = {**row, "status": "pending", "ceiling_usd": None, "reserved_usd": 0.0, "spent_usd": 0.0,
                   "unknown_cost_calls": 0, "approver_role": None, "stop_reason": None, "created_at": self.clock(),
                   "expires_at": self.clock() + PENDING_TTL, "decided_at": None, "finished_at": None}
            self.rows[row["authorization_id"]] = row
            return dict(row)

    def get(self, auth_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._expire()
            row = self.rows.get(auth_id)
            return dict(row) if row else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            self._expire()
            return [dict(r) for r in self.rows.values()]

    def decide(self, auth_id: str, approve: bool, ceiling: float | None, role: str) -> bool:
        with self._lock:
            self._expire()
            row = self.rows.get(auth_id)
            if not row or row["status"] != "pending":
                return False
            row.update(status="approved" if approve else "declined", ceiling_usd=ceiling, approver_role=role,
                       decided_at=self.clock(), expires_at=self.clock() + APPROVAL_TTL)
            return True

    def claim(self, auth_id: str) -> bool:
        with self._lock:
            self._expire()
            row = self.rows.get(auth_id)
            if not row or row["status"] != "approved" or any(r["status"] == "in_use" for r in self.rows.values()):
                return False
            row["status"] = "in_use"
            return True

    def reserve(self, auth_id: str, amount: float, daily_headroom: float) -> bool:
        with self._lock:
            row = self.rows[auth_id]
            if row["status"] != "in_use" or row["expires_at"] <= self.clock():
                return False
            committed = row["spent_usd"] + row["reserved_usd"] + amount
            if committed > row["ceiling_usd"] + 1e-12 or row["reserved_usd"] + amount > daily_headroom + 1e-12:
                return False
            row["reserved_usd"] += amount
            return True

    def settle(self, auth_id: str, reserved: float, actual: float | None) -> None:
        with self._lock:
            row = self.rows[auth_id]
            row["reserved_usd"] = max(0.0, row["reserved_usd"] - reserved)
            row["spent_usd"] += reserved if actual is None else actual
            row["unknown_cost_calls"] += actual is None

    def finish(self, auth_id: str, status: str, reason: str | None) -> None:
        with self._lock:
            row = self.rows[auth_id]
            if row["status"] == "in_use":
                row.update(status=status, stop_reason=reason, finished_at=self.clock())


class AuthorizationStore:
    """PostgreSQL store; every transition is one conditional UPDATE, so concurrent processes cannot both win."""

    def __init__(self, url: str):
        import psycopg
        from psycopg.rows import dict_row

        from app.llm import migrations
        self._connect = lambda: psycopg.connect(url, row_factory=dict_row, autocommit=True)
        with self._connect() as conn:  # never creates anything: L001 is an explicit migration
            if migrations.state(conn)["state"] != "current":
                raise PaidRefused(f"llm migration {migrations.L001} is not applied; paid generation is unavailable "
                                  "(python -m app.llm.migrate apply, after a verified backup)")

    def _expire(self, conn: Any) -> None:
        conn.execute("UPDATE llm.paid_authorization SET status = 'expired', stop_reason = COALESCE(stop_reason, "
                     "'expired') WHERE status IN ('pending', 'approved', 'in_use') AND expires_at <= now()")

    @staticmethod
    def _plain(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: (float(v) if k.endswith("_usd") and v is not None else v) for k, v in row.items()}

    def create(self, row: dict[str, Any]) -> dict[str, Any]:
        from psycopg.types.json import Jsonb
        with self._connect() as conn, conn.transaction():
            self._expire(conn)
            conn.execute("LOCK TABLE llm.paid_authorization IN SHARE ROW EXCLUSIVE MODE")
            pending = conn.execute("SELECT COUNT(*) AS n FROM llm.paid_authorization WHERE status = 'pending'"
                                   ).fetchone()["n"]
            if pending >= PENDING_LIMIT:
                raise PaidRefused(f"{PENDING_LIMIT} authorizations are already pending; decide or let them expire")
            return self._plain(conn.execute(
                "INSERT INTO llm.paid_authorization (authorization_id, status, subject, objective_code, questions, "
                "model, estimate, expires_at) VALUES (%s, 'pending', %s, %s, %s, %s, %s, now() + %s) RETURNING *",
                (row["authorization_id"], row["subject"], row["objective_code"], row["questions"], row["model"],
                 Jsonb(row["estimate"]), PENDING_TTL)).fetchone())

    def get(self, auth_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            self._expire(conn)
            return self._plain(conn.execute("SELECT * FROM llm.paid_authorization WHERE authorization_id = %s",
                                            (auth_id,)).fetchone())

    def all(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            self._expire(conn)
            return [self._plain(r) for r in conn.execute(
                "SELECT * FROM llm.paid_authorization ORDER BY created_at DESC LIMIT 50")]

    def decide(self, auth_id: str, approve: bool, ceiling: float | None, role: str) -> bool:
        with self._connect() as conn:
            self._expire(conn)
            return conn.execute(
                "UPDATE llm.paid_authorization SET status = %s, ceiling_usd = %s, approver_role = %s, "
                "decided_at = now(), expires_at = now() + %s WHERE authorization_id = %s AND status = 'pending'",
                ("approved" if approve else "declined", ceiling, role, APPROVAL_TTL, auth_id)).rowcount == 1

    def claim(self, auth_id: str) -> bool:
        with self._connect() as conn, conn.transaction():
            self._expire(conn)
            conn.execute("LOCK TABLE llm.paid_authorization IN SHARE ROW EXCLUSIVE MODE")
            return conn.execute(
                "UPDATE llm.paid_authorization SET status = 'in_use' WHERE authorization_id = %s "
                "AND status = 'approved' AND NOT EXISTS (SELECT 1 FROM llm.paid_authorization WHERE status = 'in_use')",
                (auth_id,)).rowcount == 1

    def reserve(self, auth_id: str, amount: float, daily_headroom: float) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "UPDATE llm.paid_authorization SET reserved_usd = reserved_usd + %(a)s WHERE authorization_id = %(id)s "
                "AND status = 'in_use' AND expires_at > now() AND spent_usd + reserved_usd + %(a)s <= ceiling_usd "
                "AND reserved_usd + %(a)s <= %(day)s", {"a": amount, "id": auth_id, "day": daily_headroom}
            ).rowcount == 1

    def settle(self, auth_id: str, reserved: float, actual: float | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE llm.paid_authorization SET reserved_usd = GREATEST(0, reserved_usd - %(r)s), "
                "spent_usd = spent_usd + %(s)s, unknown_cost_calls = unknown_cost_calls + %(u)s "
                "WHERE authorization_id = %(id)s",
                {"r": reserved, "s": reserved if actual is None else actual, "u": int(actual is None), "id": auth_id})

    def finish(self, auth_id: str, status: str, reason: str | None) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE llm.paid_authorization SET status = %s, stop_reason = %s, finished_at = now() "
                         "WHERE authorization_id = %s AND status = 'in_use'", (status, reason, auth_id))


# ---------------------------------------------------------------- the three steps

def request_estimate(store: Any, client: Any, usage_store: Any, subject: str, objective: str | None,
                     questions: int, requests_per_question: int) -> dict[str, Any]:
    """Step 1. A `pending` authorization when the estimate is usable, else the unavailable estimate alone."""
    settings = client.settings
    if not settings.allow_paid or not settings.paid_model:
        raise PaidRefused("paid generation is disabled (OPENROUTER_ALLOW_PAID=false or no OPENROUTER_PAID_MODEL)")
    if not 1 <= questions <= MAX_QUESTIONS:
        raise PaidRefused(f"questions must be 1..{MAX_QUESTIONS}")
    pricing, problem = current_pricing(client, settings.paid_model)
    est = estimate(settings, pricing, problem, usage_store.token_profile(HISTORY_DAYS), check_balance(client),
                   questions, requests_per_question)
    if est["status"] != "ok":
        return {"authorization_id": None, "estimate": est,
                "next": "estimate_unavailable: an operator must decide on an alternative before any paid call"}
    row = store.create({"authorization_id": f"PA-{uuid.uuid4().hex[:12]}", "subject": subject,
                        "objective_code": objective, "questions": questions, "model": settings.paid_model,
                        "estimate": est})
    return {"authorization_id": row["authorization_id"], "status": "pending", "expires_at": _iso(row["expires_at"]),
            "estimate": est}


def approve(store: Any, settings: Any, auth_id: str, ceiling: float, role: str) -> dict[str, Any]:
    """Step 2 (affirmative, operation-specific). Raises PaidRefused with the reason; nothing changes then."""
    if role not in APPROVERS:
        raise PaidRefused(f"approver must be one of {APPROVERS} (never the student)")
    row = store.get(auth_id)
    if row is None or row["status"] != "pending":
        raise PaidRefused(f"{auth_id} is not pending ({row['status'] if row else 'unknown'})")
    est = row["estimate"]
    if est.get("status") != "ok":
        raise PaidRefused("estimate_unavailable: nothing to approve")
    if not settings.allow_paid or settings.paid_model != row["model"]:
        raise PaidRefused("paid generation is disabled or the configured paid model changed; estimate again")
    if not 0 < ceiling <= settings.paid_max_usd_per_operation:
        raise PaidRefused(f"the ceiling must be above 0 and at most OPENROUTER_PAID_MAX_USD_PER_OPERATION "
                          f"({settings.paid_max_usd_per_operation} USD)")
    if ceiling > settings.max_usd_per_day:
        raise PaidRefused(f"the ceiling exceeds the daily USD budget ({settings.max_usd_per_day} USD)")
    if ceiling < est["expected_usd"]:
        raise PaidRefused(f"the ceiling is below the expected cost ({est['expected_usd']} USD)")
    available = spend_limit(est["balance"])
    if available is not None and available < ceiling:
        raise PaidRefused(f"insufficient verified credit: {available} USD available, ceiling {ceiling} USD")
    if not store.decide(auth_id, True, ceiling, role):
        raise PaidRefused(f"{auth_id} was decided or expired concurrently")
    return {"authorization_id": auth_id, "status": "approved", "ceiling_usd": ceiling,
            "covers_maximum": ceiling >= est["max_usd"],
            "note": "paid calls stop when the next call's worst-case cost would pass the ceiling"}


def decline(store: Any, auth_id: str, role: str) -> dict[str, Any]:
    if role not in APPROVERS:
        raise PaidRefused(f"approver must be one of {APPROVERS}")
    if not store.decide(auth_id, False, None, role):
        raise PaidRefused(f"{auth_id} is not pending")
    return {"authorization_id": auth_id, "status": "declined", "paid_calls": 0}


@dataclass
class PaidGrant:
    """Step 3 handle for one claimed authorization; `route` reserves every paid attempt through it."""

    store: Any
    authorization_id: str
    model: str
    pricing: Pricing
    input_max: dict[str, int]
    max_usd_per_day: float
    today_paid: Callable[[], float]
    stopped: str | None = None
    calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self, purpose: str, max_tokens: int) -> float | None:
        """Reserve the worst-case cost of one attempt, or None (ceiling, daily budget or a stop reached)."""
        with self._lock:
            if self.stopped:
                return None
            amount = call_ceiling(self.pricing, self.input_max.get(purpose, max(self.input_max.values())), max_tokens)
            # Today's paid exposure: actual costs plus the liability of every paid attempt whose cost is still
            # unknown, from this and earlier authorizations (T055 review). In-flight reservations of this
            # authorization are checked by the store.
            headroom = self.max_usd_per_day - self.today_paid()
            if not self.store.reserve(self.authorization_id, amount, headroom):
                self.stopped = "authorization_ceiling"
                return None
            self.calls += 1
            return amount

    def settle(self, reserved: float, actual: float | None) -> None:
        """Release a reservation; an unknown cost is counted at its full reservation, never as zero."""
        self.store.settle(self.authorization_id, reserved, actual)

    def stop(self, reason: str) -> None:
        with self._lock:
            self.stopped = self.stopped or reason

    def finish(self) -> dict[str, Any]:
        self.store.finish(self.authorization_id, "stopped" if self.stopped and self.stopped != "authorization_ceiling"
                          else "consumed", self.stopped)
        row = self.store.get(self.authorization_id) or {}
        return {"authorization_id": self.authorization_id, "status": row.get("status"),
                "spent_usd": row.get("spent_usd"), "unknown_cost_calls": row.get("unknown_cost_calls"),
                "paid_attempts": self.calls, "stop_reason": self.stopped}


def open_grant(store: Any, client: Any, usage_store: Any, auth_id: str, subject: str,
               objective: str | None) -> PaidGrant:
    """Claim an approval for this exact operation and re-check prices and balance before any paid call."""
    settings = client.settings
    row = store.get(auth_id)
    if row is None or row["status"] != "approved":
        raise PaidRefused(f"{auth_id} is not approved ({row['status'] if row else 'unknown'})")
    if (row["subject"], row["objective_code"]) != (subject, objective):
        raise PaidRefused(f"{auth_id} was approved for {row['subject']} {row['objective_code']}, not this run")
    if not settings.allow_paid or settings.paid_model != row["model"]:
        raise PaidRefused("paid generation is disabled or the paid model changed since approval")
    if not store.claim(auth_id):
        raise PaidRefused(f"{auth_id} could not be claimed (expired, used, or another paid operation is running)")
    approved = row["estimate"]["pricing"]
    pricing, problem = current_pricing(client, row["model"])
    reason = None
    if pricing is None:
        reason = f"price check failed: {problem}"
    elif (pricing.prompt > approved["usd_per_input_token"] or pricing.completion > approved["usd_per_output_token"]
          or pricing.request > approved["usd_per_request"]
          or pricing.reasoning > approved["usd_per_reasoning_token"]):
        reason = "prices rose since the estimate; estimate again"
    else:
        available = spend_limit(check_balance(client))
        if available is not None and available < row["ceiling_usd"]:
            reason = f"insufficient verified credit ({available} USD) for the {row['ceiling_usd']} USD ceiling"
    if reason:
        store.finish(auth_id, "stopped", reason)
        raise PaidRefused(reason)
    per_call = row["estimate"]["per_call"]
    return PaidGrant(store, auth_id, row["model"], pricing,
                     {p: per_call[p]["input_tokens_max"] for p in WORKFLOW}, settings.max_usd_per_day,
                     lambda: usage_store.today()["paid_exposure_usd"])


# ---------------------------------------------------------------- CLI

def _show(row: dict[str, Any]) -> dict[str, Any]:
    est = row["estimate"]
    return {"authorization_id": row["authorization_id"], "status": row["status"], "subject": row["subject"],
            "objective": row["objective_code"], "questions": row["questions"], "model": row["model"],
            "expected_usd": est.get("expected_usd"), "max_usd": est.get("max_usd"),
            "ceiling_usd": row["ceiling_usd"], "spent_usd": row["spent_usd"],
            "unknown_cost_calls": row["unknown_cost_calls"], "approver": row["approver_role"],
            "stop_reason": row["stop_reason"], "expires_at": _iso(row["expires_at"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.llm.paid")
    sub = parser.add_subparsers(dest="command", required=True)
    est = sub.add_parser("estimate")
    est.add_argument("--subject", required=True)
    est.add_argument("--objective")
    est.add_argument("--questions", type=int, default=1)
    for name in ("approve", "decline"):
        p = sub.add_parser(name)
        p.add_argument("--authorization", required=True)
        p.add_argument("--approver", choices=APPROVERS, required=True)
    sub.choices["approve"].add_argument("--max-usd", type=float, required=True)
    sub.add_parser("list")
    args = parser.parse_args(argv)

    from app.generation.practice_set import SetLimits
    from app.llm.client import OpenRouterClient
    from app.llm.settings import LlmSettings
    from app.llm.usage import UsageStore
    from curriculum import db

    url = db.database_url()
    store = AuthorizationStore(url)
    settings = LlmSettings.load()
    try:
        if args.command == "estimate":
            with OpenRouterClient(settings) as client:
                out = request_estimate(store, client, UsageStore(url), args.subject, args.objective, args.questions,
                                       SetLimits.from_env().max_requests_per_slot)
        elif args.command == "approve":
            out = approve(store, settings, args.authorization, args.max_usd, args.approver)
        elif args.command == "decline":
            out = decline(store, args.authorization, args.approver)
        else:
            out = [_show(r) for r in store.all()]
    except PaidRefused as exc:
        print(f"REFUSED (no paid call, nothing approved): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=1, default=str))
    return 0 if not isinstance(out, dict) or out.get("authorization_id") or args.command == "list" else 1


if __name__ == "__main__":
    raise SystemExit(main())
