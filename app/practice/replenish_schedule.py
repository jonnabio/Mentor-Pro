"""Scheduled replenishment ticks (T066; ADR-036 amendment).

A host timer (cron) runs `python -m app.practice.replenish tick` in the app container. One tick:

1. does nothing unless `MENTOR_PRO_REPLENISH_SCHEDULE=on` and the administrator has not paused the schedule
   (`replenish pause` / `resume`, stored in the database so no restart is needed);
2. takes a global non-blocking advisory lock, so two ticks never run at once (a second one is recorded as
   `skipped: busy`); PostgreSQL releases it if the tick dies;
3. runs `replenishment.run` for subjects in rotation, starting after the subject the previous tick ended on,
   until `MENTOR_PRO_REPLENISH_TICK_CALLS` calls are spent or a budget or provider stop occurs.
   `replenishment.run` keeps its own guarantees: one pending request per cell (candidates awaiting review
   are never generated again), the per-subject seeding lock, planned gap cells only, the shared daily budget
   and free models only (no paid opener is ever passed);
4. records the tick (status, per-subject results, error) in `generation.replenish_tick`.

Nothing here records a tutor verdict: generated candidates stay held from practices until a human approves.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.practice import replenishment, seeding

SCHEDULE_LOCK = (seeding.LOCK_NAMESPACE, 0)  # subject locks use crc32 keys masked to 31 bits, never 0 in practice
STALE_MINUTES = 120
BUDGET_STOPS = ("daily_budget", "provider_rate_limited")

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS generation;
CREATE TABLE IF NOT EXISTS generation.replenish_schedule (
    id          SMALLINT PRIMARY KEY CHECK (id = 1),
    paused      BOOLEAN NOT NULL DEFAULT false,
    reason      TEXT,
    next_index  INTEGER NOT NULL DEFAULT 0 CHECK (next_index >= 0),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO generation.replenish_schedule (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS generation.replenish_tick (
    tick_id      TEXT PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL CHECK (status IN ('running', 'ok', 'skipped', 'failed', 'abandoned')),
    reason       TEXT,
    calls        INTEGER NOT NULL DEFAULT 0 CHECK (calls >= 0),
    generated    INTEGER NOT NULL DEFAULT 0 CHECK (generated >= 0),
    detail       JSONB NOT NULL DEFAULT '[]'::jsonb,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS idx_replenish_tick_started ON generation.replenish_tick (started_at DESC);
"""


class ScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduleSettings:
    enabled: bool = False
    tick_calls: int = 10

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> ScheduleSettings:
        raw = env.get("MENTOR_PRO_REPLENISH_SCHEDULE", "off").strip().lower()
        if raw not in ("on", "off"):
            raise ScheduleError("MENTOR_PRO_REPLENISH_SCHEDULE must be on or off")
        try:
            calls = int(env.get("MENTOR_PRO_REPLENISH_TICK_CALLS", cls.tick_calls))
        except ValueError:
            raise ScheduleError("MENTOR_PRO_REPLENISH_TICK_CALLS must be an integer") from None
        if not 1 <= calls <= 50:
            raise ScheduleError("MENTOR_PRO_REPLENISH_TICK_CALLS must be 1..50")
        return cls(enabled=raw == "on", tick_calls=calls)


def ensure_schema(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL)


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def set_paused(url: str, paused: bool, reason: str | None = None) -> dict[str, Any]:
    ensure_schema(url)
    with _connect(url) as conn:
        conn.execute("UPDATE generation.replenish_schedule SET paused = %s, reason = %s, updated_at = now() "
                     "WHERE id = 1", (paused, reason))
    return status(url, ScheduleSettings.from_env())


def _record(conn: psycopg.Connection, status_: str, reason: str | None) -> str:
    tick_id = f"tick-{uuid.uuid4().hex[:12]}"
    conn.execute("INSERT INTO generation.replenish_tick (tick_id, status, reason, finished_at) "
                 "VALUES (%s, %s, %s, CASE WHEN %s = 'running' THEN NULL ELSE now() END)",
                 (tick_id, status_, reason, status_))
    return tick_id


def tick(url: str, catalog: psycopg.Connection, baseline: str, llm_factory: Callable[[], tuple],
         policy: replenishment.Policy, settings: ScheduleSettings, subjects: tuple[str, ...],
         run: Callable[..., dict[str, Any]] = replenishment.run) -> dict[str, Any]:
    """One bounded scheduled pass. Returns the recorded tick; never raises for a failed subject run."""
    ensure_schema(url)
    with _connect(url) as conn:
        conn.execute("UPDATE generation.replenish_tick SET status = 'abandoned', finished_at = now(), "
                     "error = 'no finish recorded (process ended)' WHERE status = 'running' "
                     "AND started_at < now() - make_interval(mins => %s)", (STALE_MINUTES,))
        state = conn.execute("SELECT paused, reason, next_index FROM generation.replenish_schedule "
                             "WHERE id = 1").fetchone()
        if not settings.enabled:
            return _finish_skip(conn, "disabled")
        if state["paused"]:
            return _finish_skip(conn, "paused")
    lock = psycopg.connect(url, autocommit=True, row_factory=dict_row)
    try:
        if not lock.execute("SELECT pg_try_advisory_lock(%s, %s) AS ok", SCHEDULE_LOCK).fetchone()["ok"]:
            with _connect(url) as conn:
                return _finish_skip(conn, "busy")
        with _connect(url) as conn:
            tick_id = _record(conn, "running", None)
        detail: list[dict[str, Any]] = []
        calls = generated = 0
        reason = None
        failed = None
        start = state["next_index"] % len(subjects)
        order = subjects[start:] + subjects[:start]
        next_index = start
        for offset, subject in enumerate(order):
            remaining = settings.tick_calls - calls
            if remaining <= 0:
                reason = "tick_call_limit"
                break
            next_index = (start + offset + 1) % len(subjects)
            # T067: a subject's share of the tick, so one subject cannot take every call; leftovers go on.
            share = max(policy.objective_calls, -(-settings.tick_calls // len(subjects)))
            try:
                out = run(url, catalog, baseline, subject, llm_factory, policy, min(remaining, share))
            except seeding.SeedBusy:
                detail.append({"subject": subject, "skipped": "subject_busy"})
                continue
            except Exception as exc:  # noqa: BLE001 - recorded and reported, the tick never dies silently
                failed = f"{subject}: {type(exc).__name__}: {exc}"[:500]
                detail.append({"subject": subject, "error": type(exc).__name__})
                break
            calls += out["calls"]
            generated += out["generated"]
            detail.append({"subject": subject, "opened": out["opened"], "generated": out["generated"],
                           "calls": out["calls"], "stop_reason": out["stop_reason"],
                           "pending": len(out["pending"]),
                           "objectives": [{k: r.get(k) for k in ("objective_code", "tier_name", "levels",
                                                                  "generated", "calls", "stop_reason")}
                                          for r in out.get("runs", [])]})
            if out["stop_reason"] in BUDGET_STOPS:
                reason = out["stop_reason"]
                break
        with _connect(url) as conn:
            conn.execute("UPDATE generation.replenish_schedule SET next_index = %s, updated_at = now() "
                         "WHERE id = 1", (next_index,))
            row = conn.execute(
                "UPDATE generation.replenish_tick SET status = %s, reason = %s, calls = %s, generated = %s, "
                "detail = %s, error = %s, finished_at = now() WHERE tick_id = %s RETURNING *",
                ("failed" if failed else "ok", reason, calls, generated, Jsonb(detail), failed, tick_id)).fetchone()
        return dict(row)
    finally:
        lock.close()


def _finish_skip(conn: psycopg.Connection, reason: str) -> dict[str, Any]:
    tick_id = _record(conn, "skipped", reason)
    return dict(conn.execute("SELECT * FROM generation.replenish_tick WHERE tick_id = %s", (tick_id,)).fetchone())


def status(url: str, settings: ScheduleSettings, limit: int = 10) -> dict[str, Any]:
    """Read-only: switch, pause state, recent ticks and consecutive failures (for the administrator)."""
    ensure_schema(url)
    with _connect(url) as conn:
        state = conn.execute("SELECT paused, reason, next_index, updated_at FROM generation.replenish_schedule "
                             "WHERE id = 1").fetchone()
        ticks = conn.execute("SELECT tick_id, started_at, finished_at, status, reason, calls, generated, detail, "
                             "error FROM generation.replenish_tick ORDER BY started_at DESC LIMIT %s",
                             (limit,)).fetchall()
    failures = 0
    for t in ticks:
        if t["status"] == "skipped":
            continue
        if t["status"] not in ("failed", "abandoned"):
            break
        failures += 1
    return {"enabled": settings.enabled, "tick_calls": settings.tick_calls, "paused": state["paused"],
            "pause_reason": state["reason"], "next_index": state["next_index"],
            "consecutive_failures": failures, "recent": ticks}
