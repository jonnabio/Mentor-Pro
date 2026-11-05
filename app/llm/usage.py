"""LLM usage records in PostgreSQL (schema `llm`), per llm-cost-observability (ADR-009).

Stores IDs and metrics only: no prompts, responses, API keys or student data.
A missing cost is NULL with cost_source = 'missing' — never assumed to be zero.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.llm.client import Attempt

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS llm;
CREATE TABLE IF NOT EXISTS llm.usage_record (
    call_id          TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL,
    practice_set_id  TEXT,
    purpose          TEXT NOT NULL CHECK (purpose IN ('generation', 'repair', 'independent_solve', 'review',
                                                      'evaluation', 'ingestion', 'connectivity_test')),
    attempt          INTEGER NOT NULL CHECK (attempt >= 1),
    is_fallback      BOOLEAN NOT NULL,
    model_requested  TEXT NOT NULL,
    model_used       TEXT,
    provider         TEXT,
    tier             TEXT NOT NULL CHECK (tier IN ('free', 'paid', 'unknown')),
    tokens_in        INTEGER CHECK (tokens_in >= 0),
    tokens_out       INTEGER CHECK (tokens_out >= 0),
    cost_usd         NUMERIC(14, 8) CHECK (cost_usd >= 0),
    cost_source      TEXT NOT NULL CHECK (cost_source IN ('provider_reported', 'generation_endpoint', 'missing')),
    latency_ms       INTEGER NOT NULL CHECK (latency_ms >= 0),
    status           TEXT NOT NULL CHECK (status IN ('ok', 'error', 'rate_limited', 'timeout',
                                                     'budget_blocked', 'invalid_output')),
    error_kind       TEXT,
    generation_id    TEXT,
    started_at       TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_started ON llm.usage_record (started_at);
"""
# T055 columns are added only by the explicit migration L001 (app/llm/migrations.py), never at start-up.


def paid_exposure(record: dict[str, Any]) -> float:
    """USD a paid attempt counts against the daily budget: the actual cost once known, else the worst-case
    liability held when it was sent (T055). Reconciling a cost replaces the liability, never adds to it."""
    if record.get("tier") != "paid" or record.get("status") == "budget_blocked":
        return 0.0
    if record.get("cost_usd") is not None:
        return float(record["cost_usd"])
    return float(record.get("liability_usd") or 0.0)


@dataclass(frozen=True)
class UsageContext:
    request_id: str
    purpose: str
    practice_set_id: str | None = None
    subject: str | None = None              # T055: never student data
    objective_code: str | None = None
    authorization_id: str | None = None     # set on paid calls made under an adult's approval


def to_record(attempt: Attempt, ctx: UsageContext, tier: str, is_fallback: bool,
              started_at: datetime | None = None) -> dict[str, Any]:
    """Map an Attempt to an LlmUsageRecord dict (.ace/schemas/question-engine/llm-usage-record.schema.json)."""
    return {
        "schema_version": "1.0",
        "call_id": f"call-{uuid.uuid4().hex}",
        "request_id": ctx.request_id,
        "practice_set_id": ctx.practice_set_id,
        "purpose": ctx.purpose,
        "attempt": attempt.attempt,
        "is_fallback": is_fallback,
        "model_requested": attempt.model_requested,
        "model_used": attempt.model_used,
        "provider": attempt.provider,
        "tier": tier,
        "tokens_in": attempt.tokens_in,
        "tokens_out": attempt.tokens_out,
        "cost_usd": attempt.cost_usd,
        "cost_source": attempt.cost_source,
        "latency_ms": attempt.latency_ms,
        "status": attempt.status,
        "started_at": (started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generation_id": attempt.generation_id,
        "error_kind": attempt.error_kind,
        "subject": ctx.subject,
        "objective_code": ctx.objective_code,
        "reasoning_tokens": attempt.reasoning_tokens,
        "failure_category": attempt.failure_category,
        "authorization_id": ctx.authorization_id if tier == "paid" else None,
        "liability_usd": None,   # set by the router for paid attempts (worst-case USD reserved)
    }


def blocked_record(model: str, ctx: UsageContext, tier: str, is_fallback: bool, attempt: int = 1) -> dict[str, Any]:
    """Record for a call that budget enforcement refused to send."""
    return to_record(Attempt(model, attempt, "budget_blocked", 0, error_kind="budget"), ctx, tier, is_fallback)


class UsageStore:
    """PostgreSQL-backed store. Use MemoryUsageStore in tests that need no database."""

    def __init__(self, url: str):
        from app.llm.migrations import usage_columns

        self.url = url
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)  # the original table only (pre-T055 behavior)
            self.columns = usage_columns(conn)

    @property
    def migrated(self) -> bool:
        """True when L001's columns exist (written only by `python -m app.llm.migrate apply`)."""
        return "liability_usd" in self.columns

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True)

    def add(self, record: dict[str, Any]) -> None:
        # Unmigrated database: T055 fields are dropped, so the row is exactly what earlier images wrote.
        columns = [c for c in record if c in self.columns]
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO llm.usage_record ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
                [record[c] for c in columns],
            )

    def today(self) -> dict[str, Any]:
        """Sent requests, paid spend (USD) and paid calls with unknown cost, for the current UTC day."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT COUNT(*) FILTER (WHERE status <> 'budget_blocked') AS requests,
                          COALESCE(SUM(cost_usd) FILTER (WHERE tier = 'paid'), 0) AS paid_usd,
                          COALESCE(SUM(COALESCE(cost_usd, {liability}, 0))
                                   FILTER (WHERE tier = 'paid' AND status <> 'budget_blocked'), 0) AS paid_exposure,
                          COUNT(*) FILTER (WHERE tier = 'paid' AND status = 'ok' AND cost_usd IS NULL) AS paid_unknown
                   FROM llm.usage_record WHERE started_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                         AT TIME ZONE 'UTC'""".format(liability="liability_usd" if self.migrated else "NULL")
            ).fetchone()
        return {"requests": row["requests"], "paid_usd": float(row["paid_usd"]),
                "paid_exposure_usd": float(row["paid_exposure"]), "paid_unknown": row["paid_unknown"]}

    def token_profile(self, days: int) -> dict[str, dict[str, float]]:
        """Observed tokens of successful calls per purpose (T055 estimates): calls, max_in, mean_in, mean_out."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT purpose, COUNT(*) AS calls, MAX(tokens_in) AS max_in, AVG(tokens_in) AS mean_in,
                          AVG(tokens_out) AS mean_out FROM llm.usage_record
                   WHERE status = 'ok' AND tokens_in IS NOT NULL AND tokens_out IS NOT NULL
                     AND started_at >= now() - make_interval(days => %s) GROUP BY purpose""", (days,)).fetchall()
        return {r["purpose"]: {"calls": r["calls"], "max_in": int(r["max_in"]), "mean_in": float(r["mean_in"]),
                               "mean_out": float(r["mean_out"])} for r in rows}

    def rows_since(self, since: datetime) -> list[dict[str, Any]]:
        """Usage rows since `since` (T055 cost report); IDs and metrics only."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM llm.usage_record WHERE started_at >= %s ORDER BY started_at",
                                (since,)).fetchall()
        return [{**r, **{k: None if r.get(k) is None else float(r[k]) for k in ("cost_usd", "liability_usd")}}
                for r in rows]

    def set_cost(self, call_id: str, cost: float) -> None:
        """Reconciliation: fill a missing cost from OpenRouter's generation metadata (never overwrites)."""
        with self._connect() as conn:
            conn.execute("UPDATE llm.usage_record SET cost_usd = %s, cost_source = 'generation_endpoint' "
                         "WHERE call_id = %s AND cost_usd IS NULL", (cost, call_id))


class MemoryUsageStore:
    """In-memory store with the same interface (tests, dry runs)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def add(self, record: dict[str, Any]) -> None:
        self.records.append(record)

    def today(self) -> dict[str, Any]:
        sent = [r for r in self.records if r["status"] != "budget_blocked"]
        paid = [r for r in self.records if r["tier"] == "paid"]
        return {
            "requests": len(sent),
            "paid_usd": sum(r["cost_usd"] or 0 for r in paid),
            "paid_exposure_usd": sum(paid_exposure(r) for r in paid),
            "paid_unknown": sum(1 for r in paid if r["status"] == "ok" and r["cost_usd"] is None),
        }

    def token_profile(self, days: int) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for purpose in {r["purpose"] for r in self.records}:
            ok = [r for r in self.records if r["purpose"] == purpose and r["status"] == "ok"
                  and r.get("tokens_in") is not None and r.get("tokens_out") is not None]
            if ok:
                out[purpose] = {"calls": len(ok), "max_in": max(r["tokens_in"] for r in ok),
                                "mean_in": sum(r["tokens_in"] for r in ok) / len(ok),
                                "mean_out": sum(r["tokens_out"] for r in ok) / len(ok)}
        return out

    def rows_since(self, since: datetime) -> list[dict[str, Any]]:
        stamp = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        return [dict(r) for r in self.records if r["started_at"] >= stamp]

    def set_cost(self, call_id: str, cost: float) -> None:
        for r in self.records:
            if r["call_id"] == call_id and r["cost_usd"] is None:
                r["cost_usd"], r["cost_source"] = cost, "generation_endpoint"
