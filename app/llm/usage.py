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


@dataclass(frozen=True)
class UsageContext:
    request_id: str
    purpose: str
    practice_set_id: str | None = None


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
    }


def blocked_record(model: str, ctx: UsageContext, tier: str, is_fallback: bool, attempt: int = 1) -> dict[str, Any]:
    """Record for a call that budget enforcement refused to send."""
    return to_record(Attempt(model, attempt, "budget_blocked", 0), ctx, tier, is_fallback)


class UsageStore:
    """PostgreSQL-backed store. Use MemoryUsageStore in tests that need no database."""

    def __init__(self, url: str):
        self.url = url
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True)

    def add(self, record: dict[str, Any]) -> None:
        columns = [c for c in record if c != "schema_version"]
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
                          COUNT(*) FILTER (WHERE tier = 'paid' AND status = 'ok' AND cost_usd IS NULL) AS paid_unknown
                   FROM llm.usage_record WHERE started_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                         AT TIME ZONE 'UTC'"""
            ).fetchone()
        return {"requests": row["requests"], "paid_usd": float(row["paid_usd"]), "paid_unknown": row["paid_unknown"]}


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
            "paid_unknown": sum(1 for r in paid if r["status"] == "ok" and r["cost_usd"] is None),
        }
