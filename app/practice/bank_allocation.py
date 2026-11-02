"""Bank-only practice composition (T048, ADR-035).

A bank-only practice is assembled completely from eligible bank questions before
any session exists; it never calls the LLM or queues generation.

Rules (PO decisions D1-D4, 2026-11-01):
  1. Questions per objective come from `allocate` unchanged; no objective is
     swapped for another (D2).
  2. Within an objective, a slot takes any evidencia × difficulty cell that has
     an unused eligible question, spreading evidencias before one repeats (D1).
     Every question keeps the exact objective, evidencia and difficulty it records.
  3. "mixed" is a balance: each level within ±1 of a third of the practice (D3).
     An explicit level is never substituted.
  4. Unseen questions are preferred; seen ones fill only when no unseen one fits.
     No question or near duplicate appears twice in a practice.
"""

from __future__ import annotations

import math
import secrets
from collections import Counter
from typing import Any

import psycopg

from app.allocation import MIXED_CYCLE, QUESTION_COUNTS, allocate
from app.generation.validation import duplicate_reason
from app.practice.bank import QuestionBank


class Shortage(Exception):
    """Not enough eligible bank questions; `largest` is the largest permitted size that fits now (0 if none)."""

    def __init__(self, requested: int, largest: int):
        super().__init__(f"bank shortage: requested {requested}, largest feasible {largest}")
        self.requested, self.largest = requested, largest


def level_bounds(total: int) -> tuple[int, int]:
    """Allowed count per level for a mixed practice of `total` questions (within ±1 of a third)."""
    return max(0, math.ceil(total / 3 - 1)), math.floor(total / 3 + 1)


class BankComposer:
    """Compose bank-only practices for one objective selection; bank lookups are cached per objective.

    `db` is an optional bank connection shared by the lookups (one connection per request, not per objective).
    """

    def __init__(self, bank: QuestionBank, catalog: psycopg.Connection, baseline: str, subject: str,
                 objectives: list[dict[str, Any]], difficulty: str, db: psycopg.Connection | None = None):
        self.bank, self.catalog, self.baseline, self.subject, self.db = bank, catalog, baseline, subject, db
        self.objectives, self.difficulty = objectives, difficulty
        self.levels = MIXED_CYCLE if difficulty == "mixed" else (difficulty,)
        self.seen = bank.seen_questions()
        self._cache: dict[str, list[dict[str, Any]]] = {}

    def _candidates(self, objective: dict[str, Any]) -> list[dict[str, Any]]:
        code = objective["workbook_code"]
        if code not in self._cache:
            evidences = {e["id"]: e["ordinal"] for e in objective["evidences"]}
            self._cache[code] = self.bank.candidates(self.catalog, self.baseline, self.subject, code,
                                                     evidences, self.levels, db=self.db)
        return self._cache[code]

    def compose(self, count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
        """(allocation, picks) for a complete practice of `count`, or None when the bank cannot fill it."""
        plan = allocate(self.objectives, count, self.difficulty)["allocation"]
        by_code = {o["workbook_code"]: o for o in self.objectives}
        low, high = level_bounds(count) if self.difficulty == "mixed" else (count, count)
        levels: Counter[str] = Counter()
        chosen: list[dict[str, Any]] = []
        allocation, picks = [], []
        sequence = 0
        for row in plan:
            objective = by_code[row["workbook_code"]]
            ordinals = {e["id"]: e["ordinal"] for e in objective["evidences"]}
            pool = self._candidates(objective)
            uses: Counter[str] = Counter()
            slots = []
            for _ in range(row["questions"]):
                usable = [c for c in pool if levels[c["difficulty"]] < high
                          and all(c["item"]["item_id"] != p["item_id"] for p in chosen)
                          and duplicate_reason(c["item"], chosen) is None]
                if not usable:
                    return None
                # Spread evidencias first, then the level furthest below its share, then unseen; ties by ordinal.
                def rank(c: dict[str, Any]) -> tuple:
                    return (uses[c["evidence_id"]], levels[c["difficulty"]], c["item"]["item_id"] in self.seen,
                            ordinals[c["evidence_id"]], MIXED_CYCLE.index(c["difficulty"]))
                best = min(rank(c)[:2] for c in usable)
                cell = [c for c in usable if rank(c)[:2] == best]
                fresh = [c for c in cell if c["item"]["item_id"] not in self.seen]
                first = min(rank(c)[3:] for c in (fresh or cell))
                pick = secrets.choice([c for c in (fresh or cell) if rank(c)[3:] == first])
                sequence += 1
                uses[pick["evidence_id"]] += 1
                levels[pick["difficulty"]] += 1
                chosen.append(pick["item"])
                slots.append({"slot": sequence, "evidence_id": pick["evidence_id"],
                              "evidence_ordinal": ordinals[pick["evidence_id"]], "difficulty": pick["difficulty"]})
                picks.append({"slot": sequence, "objective_code": row["workbook_code"],
                              "evidence_id": pick["evidence_id"], "item": pick["item"], "source": "bank",
                              "source_request_id": pick["request_id"]})
            allocation.append({**row, "evidences_covered": len({s["evidence_id"] for s in slots}), "slots": slots})
        if any(levels[level] < low for level in self.levels):
            return None
        return allocation, picks

    def compose_or_shortage(self, count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """A complete practice of `count`; raises Shortage with the largest smaller permitted size that fits."""
        result = self.compose(count)
        if result is not None:
            return result
        largest = next((n for n in sorted(QUESTION_COUNTS, reverse=True) if n < count and self.compose(n)), 0)
        raise Shortage(count, largest)
