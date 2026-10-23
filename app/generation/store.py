"""Generation records in PostgreSQL (schema `generation`), ADR-010 and ADR-011.

One row per generate request: objective code, evidencia, models, tokens, cost,
verdict and the full validation result and item (dev inspection and audit).
Practice sets (T007) add one row per set and one per approved slot item.
No student data.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.generation.pipeline import GenerationOutcome

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS generation;
CREATE TABLE IF NOT EXISTS generation.question_attempt (
    request_id        TEXT PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    baseline_version  TEXT NOT NULL,
    objective_code    TEXT NOT NULL,
    evidence_id       TEXT NOT NULL,
    difficulty        TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    status            TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'unavailable')),
    verdict           TEXT,
    item_id           TEXT,
    models_used       TEXT[] NOT NULL,
    calls             INTEGER NOT NULL,
    tokens_in         INTEGER NOT NULL,
    tokens_out        INTEGER NOT NULL,
    cost_usd          NUMERIC(14, 8) NOT NULL,
    cost_complete     BOOLEAN NOT NULL,
    checker_version   TEXT,
    prompt_version    TEXT NOT NULL,
    validation        JSONB,
    item              JSONB,
    reasons           JSONB NOT NULL
);
ALTER TABLE generation.question_attempt ADD COLUMN IF NOT EXISTS practice_set_id TEXT;
ALTER TABLE generation.question_attempt ADD COLUMN IF NOT EXISTS slot INTEGER;
CREATE TABLE IF NOT EXISTS generation.practice_set (
    practice_set_id    TEXT PRIMARY KEY,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    baseline_version   TEXT NOT NULL,
    subject            TEXT NOT NULL,
    config             JSONB NOT NULL,
    allocation         JSONB NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('complete', 'partial')),
    stop_reason        TEXT,
    requested          INTEGER NOT NULL,
    accepted           INTEGER NOT NULL,
    requests           INTEGER NOT NULL,
    rejected_attempts  INTEGER NOT NULL,
    calls              INTEGER NOT NULL,
    tokens_in          INTEGER NOT NULL,
    tokens_out         INTEGER NOT NULL,
    cost_usd           NUMERIC(14, 8) NOT NULL,
    cost_complete      BOOLEAN NOT NULL,
    duration_ms        INTEGER NOT NULL,
    limits             JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS generation.practice_set_item (
    practice_set_id  TEXT NOT NULL REFERENCES generation.practice_set (practice_set_id),
    slot             INTEGER NOT NULL,
    objective_code   TEXT NOT NULL,
    evidence_id      TEXT NOT NULL,
    difficulty       TEXT NOT NULL,
    item_id          TEXT NOT NULL,
    request_id       TEXT NOT NULL REFERENCES generation.question_attempt (request_id),
    item             JSONB NOT NULL,
    PRIMARY KEY (practice_set_id, slot)
);
"""


class GenerationStore:
    def __init__(self, url: str):
        self.url = url
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL)

    def add(self, outcome: GenerationOutcome, baseline: str, difficulty: str, prompt_version: str,
            practice_set_id: str | None = None, slot: int | None = None) -> None:
        summary = outcome.summary()
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(
                """INSERT INTO generation.question_attempt (request_id, baseline_version, objective_code,
                       evidence_id, difficulty, status, verdict, item_id, models_used, calls, tokens_in,
                       tokens_out, cost_usd, cost_complete, checker_version, prompt_version, validation, item, reasons,
                       practice_set_id, slot)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (outcome.request_id, baseline, outcome.objective_code, outcome.evidence_id, difficulty,
                 outcome.status, (outcome.validation or {}).get("verdict"), (outcome.item or {}).get("item_id"),
                 summary["models_used"], summary["calls"], summary["tokens_in"], summary["tokens_out"],
                 summary["cost_usd"], summary["cost_complete"], (outcome.validation or {}).get("checker_version"),
                 prompt_version, Jsonb(outcome.validation) if outcome.validation else None,
                 Jsonb(outcome.item) if outcome.item else None, Jsonb(outcome.reasons), practice_set_id, slot),
            )

    def add_set(self, result: Any, baseline: str, config: dict[str, Any], allocation: list[dict[str, Any]],
                limits: dict[str, Any]) -> None:
        """Persist a practice set and its approved items, after every attempt row has been added."""
        summary = result.summary()
        with psycopg.connect(self.url) as conn, conn.transaction():
            conn.execute(
                """INSERT INTO generation.practice_set (practice_set_id, baseline_version, subject, config,
                       allocation, status, stop_reason, requested, accepted, requests, rejected_attempts, calls,
                       tokens_in, tokens_out, cost_usd, cost_complete, duration_ms, limits)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (result.practice_set_id, baseline, result.subject, Jsonb(config), Jsonb(allocation), result.status,
                 result.stop_reason, summary["requested"], summary["accepted"], summary["requests"],
                 summary["rejected_attempts"], summary["calls"], summary["tokens_in"], summary["tokens_out"],
                 summary["cost_usd"], summary["cost_complete"], summary["duration_ms"], Jsonb(limits)),
            )
            for slot in result.slots:
                if slot.status == "accepted":
                    conn.execute(
                        """INSERT INTO generation.practice_set_item (practice_set_id, slot, objective_code,
                               evidence_id, difficulty, item_id, request_id, item)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (result.practice_set_id, slot.slot, slot.objective_code, slot.evidence_id, slot.difficulty,
                         slot.item["item_id"], slot.request_id, Jsonb(slot.item)),
                    )

    def recent_stems(self, evidence_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Accepted items for the same evidencia, used as the duplicate-check bank."""
        with psycopg.connect(self.url) as conn:
            rows = conn.execute(
                "SELECT item FROM generation.question_attempt WHERE evidence_id = %s AND status = 'accepted' "
                "ORDER BY created_at DESC LIMIT %s", (evidence_id, limit)).fetchall()
        return [r[0] for r in rows]


class MemoryGenerationStore:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.sets: list[dict[str, Any]] = []

    def add(self, outcome: GenerationOutcome, baseline: str, difficulty: str, prompt_version: str,
            practice_set_id: str | None = None, slot: int | None = None) -> None:
        self.rows.append({"outcome": outcome, "baseline": baseline, "difficulty": difficulty,
                          "practice_set_id": practice_set_id, "slot": slot})

    def add_set(self, result: Any, baseline: str, config: dict[str, Any], allocation: list[dict[str, Any]],
                limits: dict[str, Any]) -> None:
        self.sets.append({"result": result, "baseline": baseline, "config": config, "allocation": allocation,
                          "limits": limits})

    def recent_stems(self, evidence_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return [r["outcome"].item for r in self.rows
                if r["outcome"].status == "accepted" and r["outcome"].evidence_id == evidence_id][:limit]
