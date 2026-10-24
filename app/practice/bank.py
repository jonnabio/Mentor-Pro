"""Validated question bank (T013, ADR-014).

The bank is the set of accepted generation attempts (`generation.question_attempt`).
An item may be served only if it is eligible under the current quality policy:

- validated by the current checker version with verdict `accept`; or
- explicitly revalidated: the current deterministic checker passes on the stored
  item and grounding, the key is proven by the current rules or was confirmed by
  a recorded agreeing blind solve, and the recorded rubric is all 2.

Revalidations are stored in `generation.bank_revalidation`, one row per item and
checker version; historical attempt rows are never modified.
"""

from __future__ import annotations

import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.generation.grounding import GroundingError, build_grounding
from app.generation.validation import CHECKER_VERSION, deterministic_check, duplicate_reason

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS generation.bank_revalidation (
    request_id       TEXT NOT NULL REFERENCES generation.question_attempt (request_id),
    checker_version  TEXT NOT NULL,
    eligible         BOOLEAN NOT NULL,
    reasons          JSONB NOT NULL,
    revalidated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (request_id, checker_version)
);
"""


def revalidate(item: dict[str, Any], validation: dict[str, Any] | None, bundle: Any) -> tuple[bool, list[str]]:
    """Re-run the current deterministic checker; reuse recorded solve and rubric evidence."""
    det = deterministic_check(item, bundle.records(), bundle.concept_lines)
    reasons = list(det["reasons"])
    if det["deterministic_status"] != "pass":
        return False, reasons or ["deterministic checks fail"]
    validation = validation or {}
    if det["requires_independent_solve"] and not (validation.get("independent_solve") or {}).get("agrees_with_key"):
        return False, reasons + ["current rules require an agreeing blind solve and none is recorded"]
    rubric = validation.get("rubric") or {}
    if not rubric or any(v != 2 for v in rubric.values()):
        return False, reasons + [f"recorded rubric is not all 2: {rubric}"]
    return True, reasons


class QuestionBank:
    def __init__(self, url: str):
        self.url = url
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA_SQL)

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row, autocommit=True)

    def eligible(self, catalog: psycopg.Connection, baseline: str, subject: str, objective_code: str,
                 evidence_ordinal: int, evidence_id: str, difficulty: str) -> list[dict[str, Any]]:
        """Eligible bank items for one slot (exact baseline, evidencia and difficulty)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT q.request_id, q.item, q.validation, q.checker_version, q.verdict, r.eligible
                   FROM generation.question_attempt q
                   LEFT JOIN generation.bank_revalidation r
                          ON r.request_id = q.request_id AND r.checker_version = %s
                   WHERE q.status = 'accepted' AND q.item IS NOT NULL AND q.baseline_version = %s
                     AND q.objective_code = %s AND q.evidence_id = %s AND q.difficulty = %s
                     AND q.item->>'subject' = %s
                   ORDER BY q.created_at""",
                (CHECKER_VERSION, baseline, objective_code, evidence_id, difficulty, subject)).fetchall()
            eligible = []
            bundle = None
            for row in rows:
                if row["checker_version"] == CHECKER_VERSION and row["verdict"] == "accept":
                    eligible.append(row)
                    continue
                if row["eligible"] is None:
                    if bundle is None:
                        try:
                            bundle = build_grounding(catalog, baseline, subject, objective_code, evidence_ordinal)
                        except GroundingError:
                            return []
                    ok, reasons = revalidate(row["item"], row["validation"], bundle)
                    conn.execute(
                        """INSERT INTO generation.bank_revalidation (request_id, checker_version, eligible, reasons)
                           VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                        (row["request_id"], CHECKER_VERSION, ok, Jsonb(reasons)))
                    row["eligible"] = ok
                if row["eligible"]:
                    eligible.append(row)
        return eligible

    def seen_questions(self) -> set[str]:
        """Canonical item IDs ever served to the (single, anonymous) student, from server history (T014).

        PostgreSQL is the source of truth for exposure across practices, tabs and browser sessions.
        """
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT item->>'item_id' AS item_id FROM practice.item").fetchall()
        return {r["item_id"] for r in rows}

    def compose(self, catalog: psycopg.Connection, baseline: str, subject: str, allocation: list[dict[str, Any]],
                browser_hash: str | None) -> dict[int, dict[str, Any]]:
        """Pick bank items for as many allocation slots as possible; slot -> pick.

        Each slot keeps its allocated objective, evidencia and difficulty. No item (or near duplicate)
        appears twice in the set; items never served before are preferred (global server history; the
        browser hash is kept on the session but no longer decides freshness).
        """
        seen = self.seen_questions()
        picks: dict[int, dict[str, Any]] = {}
        chosen: list[dict[str, Any]] = []
        for row in allocation:
            for slot in row["slots"]:
                candidates = self.eligible(catalog, baseline, subject, row["workbook_code"],
                                           slot["evidence_ordinal"], slot["evidence_id"], slot["difficulty"])
                usable = [c for c in candidates if duplicate_reason(c["item"], chosen) is None
                          and all(c["item"]["item_id"] != p["item_id"] for p in chosen)]
                if not usable:
                    continue
                fresh = [c for c in usable if c["item"]["item_id"] not in seen]
                pick = secrets.choice(fresh or usable)
                chosen.append(pick["item"])
                picks[slot["slot"]] = {"slot": slot["slot"], "objective_code": row["workbook_code"],
                                       "evidence_id": slot["evidence_id"], "item": pick["item"],
                                       "source": "bank", "source_request_id": pick["request_id"]}
        return picks
