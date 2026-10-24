"""Practice sessions, items and answers in PostgreSQL (schema `practice`), ADR-013.

A session is identified only by a random token; no student identity is stored.
Items keep their answer keys here, server side; the API decides what a student
may see.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ACTIVE = ("queued", "running")

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS practice;
CREATE TABLE IF NOT EXISTS practice.session (
    session_id         TEXT PRIMARY KEY,
    client_request_id  TEXT NOT NULL UNIQUE,
    fingerprint        TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at         TIMESTAMPTZ,
    finished_at        TIMESTAMPTZ,
    baseline_version   TEXT NOT NULL,
    subject            TEXT NOT NULL,
    config             JSONB NOT NULL,
    allocation         JSONB NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('queued', 'running', 'complete', 'partial', 'failed')),
    stop_reason        TEXT,
    slots_total        INTEGER NOT NULL,
    slots_done         INTEGER NOT NULL DEFAULT 0,
    practice_set_id    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_session_active_config ON practice.session (fingerprint)
    WHERE status IN ('queued', 'running');
CREATE TABLE IF NOT EXISTS practice.item (
    session_id      TEXT NOT NULL REFERENCES practice.session (session_id),
    slot            INTEGER NOT NULL,
    objective_code  TEXT NOT NULL,
    evidence_id     TEXT NOT NULL,
    item            JSONB NOT NULL,
    PRIMARY KEY (session_id, slot)
);
-- T013 (ADR-014): set composition (bank vs generated) and an anonymous per-tab hash for freshness.
ALTER TABLE practice.session ADD COLUMN IF NOT EXISTS browser_hash TEXT;
ALTER TABLE practice.session ADD COLUMN IF NOT EXISTS bank_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE practice.item ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'generated'
    CHECK (source IN ('bank', 'generated'));
ALTER TABLE practice.item ADD COLUMN IF NOT EXISTS source_request_id TEXT;
-- Practice cancellation: the student left before answering every question. Generation status is kept.
ALTER TABLE practice.session ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS practice.answer (
    session_id    TEXT NOT NULL,
    slot          INTEGER NOT NULL,
    chosen_label  TEXT NOT NULL CHECK (chosen_label IN ('A', 'B', 'C', 'D')),
    is_correct    BOOLEAN NOT NULL,
    answered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, slot),
    FOREIGN KEY (session_id, slot) REFERENCES practice.item (session_id, slot)
);
-- T017 (ADR-017): sessions without a row are student sessions; others are excluded from learning metrics.
CREATE TABLE IF NOT EXISTS practice.session_classification (
    session_id      TEXT PRIMARY KEY REFERENCES practice.session (session_id),
    classification  TEXT NOT NULL CHECK (classification IN ('student', 'automated_test', 'quarantined')),
    reason          TEXT NOT NULL,
    audit_ref       TEXT NOT NULL,
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS practice.classification_audit (
    audit_id        BIGSERIAL PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES practice.session (session_id),
    action          TEXT NOT NULL CHECK (action IN ('classify', 'rollback')),
    previous        TEXT,
    classification  TEXT,
    reason          TEXT NOT NULL,
    audit_ref       TEXT NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def fingerprint(baseline: str, config: dict[str, Any]) -> str:
    canonical = json.dumps({"baseline": baseline, **config, "objective_codes": sorted(config["objective_codes"])},
                           sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PracticeStore:
    def __init__(self, url: str):
        self.url = url
        with self._connect() as conn:
            conn.execute(SCHEMA_SQL)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True)

    def create_or_get(self, client_request_id: str, baseline: str, config: dict[str, Any],
                      allocation: list[dict[str, Any]], browser_hash: str | None = None
                      ) -> tuple[dict[str, Any], bool]:
        """Insert a queued session, or return the existing one for the same request or active configuration."""
        fp = fingerprint(baseline, config)
        slots_total = sum(len(row["slots"]) for row in allocation)
        with self._connect() as conn:
            existing = conn.execute("SELECT * FROM practice.session WHERE client_request_id = %s",
                                    (client_request_id,)).fetchone()
            if existing:
                return existing, False
            row = conn.execute(
                """INSERT INTO practice.session (session_id, client_request_id, fingerprint, baseline_version,
                       subject, config, allocation, status, slots_total, browser_hash)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s)
                   ON CONFLICT DO NOTHING RETURNING *""",
                (secrets.token_hex(16), client_request_id, fp, baseline, config["subject"], Jsonb(config),
                 Jsonb(allocation), slots_total, browser_hash)).fetchone()
            if row:
                return row, True
            # Lost a race: same request id, or an active session for the same configuration.
            existing = conn.execute(
                """SELECT * FROM practice.session WHERE client_request_id = %s
                   OR (fingerprint = %s AND status IN ('queued', 'running'))
                   ORDER BY created_at LIMIT 1""", (client_request_id, fp)).fetchone()
            return existing, False

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM practice.session WHERE session_id = %s", (session_id,)).fetchone()

    def add_bank_items(self, session_id: str, picks: list[dict[str, Any]], complete: bool) -> dict[str, Any]:
        """Store bank items for their slots; a fully covered set is complete at once (no job)."""
        with psycopg.connect(self.url, row_factory=dict_row) as conn, conn.transaction():
            for pick in picks:
                self._insert_item(conn, session_id, pick)
            status = "'complete', finished_at = now(), started_at = now()" if complete else "status"
            return conn.execute(
                f"""UPDATE practice.session SET bank_count = %s, slots_done = %s, status = {status},
                        updated_at = now() WHERE session_id = %s RETURNING *""",
                (len(picks), len(picks), session_id)).fetchone()

    def mark_running(self, session_id: str) -> None:
        self._update(session_id, "status = 'running', started_at = now()")

    def progress(self, session_id: str, slots_done: int) -> None:
        self._update(session_id, "slots_done = GREATEST(slots_done, %s)", slots_done)

    def finish(self, session_id: str, status: str, stop_reason: str | None, practice_set_id: str | None,
               items: list[dict[str, Any]]) -> None:
        """Store accepted items and the final status in one transaction."""
        with psycopg.connect(self.url) as conn, conn.transaction():
            for row in items:
                self._insert_item(conn, session_id, row)
            conn.execute(
                """UPDATE practice.session SET status = %s, stop_reason = %s, practice_set_id = %s,
                       slots_done = slots_total, finished_at = now(), updated_at = now() WHERE session_id = %s""",
                (status, stop_reason, practice_set_id, session_id))

    def fail_interrupted(self) -> int:
        """Sessions left active by a previous server process can no longer finish."""
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE practice.session SET status = 'failed', stop_reason = 'interrupted',
                       finished_at = now(), updated_at = now() WHERE status IN ('queued', 'running')""")
            return cur.rowcount

    def items(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT i.slot, i.objective_code, i.evidence_id, i.item, i.source, a.chosen_label, a.is_correct
                   FROM practice.item i LEFT JOIN practice.answer a USING (session_id, slot)
                   WHERE i.session_id = %s ORDER BY i.slot""", (session_id,)).fetchall()

    def answer(self, session_id: str, slot: int, label: str, is_correct: bool) -> tuple[dict[str, Any], bool]:
        """Record the first answer for a slot; later submissions return the stored one."""
        with self._connect() as conn:
            row = conn.execute(
                """INSERT INTO practice.answer (session_id, slot, chosen_label, is_correct)
                   VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING chosen_label, is_correct""",
                (session_id, slot, label, is_correct)).fetchone()
            if row:
                return row, True
            return conn.execute("SELECT chosen_label, is_correct FROM practice.answer "
                                "WHERE session_id = %s AND slot = %s", (session_id, slot)).fetchone(), False

    @staticmethod
    def _insert_item(conn: psycopg.Connection, session_id: str, row: dict[str, Any]) -> None:
        conn.execute(
            """INSERT INTO practice.item (session_id, slot, objective_code, evidence_id, item, source,
                   source_request_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (session_id, row["slot"], row["objective_code"], row["evidence_id"], Jsonb(row["item"]),
             row.get("source", "generated"), row.get("source_request_id")))

    def cancel(self, session_id: str) -> str:
        """Mark a ready practice as cancelled; answers stay, unanswered questions stay unanswered.

        Returns "cancelled", "already_cancelled", "finished" (every question answered) or "not_ready".
        """
        with psycopg.connect(self.url, row_factory=dict_row) as conn, conn.transaction():
            session = conn.execute("SELECT status, cancelled_at FROM practice.session WHERE session_id = %s "
                                   "FOR UPDATE", (session_id,)).fetchone()
            if session["cancelled_at"] is not None:
                return "already_cancelled"
            if session["status"] not in ("complete", "partial"):
                return "not_ready"
            open_slots = conn.execute(
                """SELECT COUNT(*) AS n FROM practice.item i LEFT JOIN practice.answer a USING (session_id, slot)
                   WHERE i.session_id = %s AND a.slot IS NULL""", (session_id,)).fetchone()["n"]
            if open_slots == 0:
                return "finished"
            conn.execute("UPDATE practice.session SET cancelled_at = now(), updated_at = now() "
                         "WHERE session_id = %s", (session_id,))
            return "cancelled"

    def _update(self, session_id: str, assignment: str, *params: Any) -> None:
        with self._connect() as conn:
            conn.execute(f"UPDATE practice.session SET {assignment}, updated_at = now() WHERE session_id = %s",
                         (*params, session_id))
