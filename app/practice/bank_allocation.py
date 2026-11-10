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


SEARCH_LIMIT = 20_000  # search states per practice size; far above what 30 slots need in practice


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
        """(allocation, picks) for a complete practice of `count`, or None when the bank cannot fill it.

        Depth-first over slots, each trying candidates in preference order, so the first complete practice is
        the greedy one whenever greedy succeeds; a dead end backtracks instead of reporting a shortage. A failed
        partial practice is remembered by its set of chosen questions (which fixes its level and evidencia
        counts), so no state is explored twice; SEARCH_LIMIT bounds the work per size.
        """
        plan = allocate(self.objectives, count, self.difficulty)["allocation"]
        by_code = {o["workbook_code"]: o for o in self.objectives}
        low, high = level_bounds(count) if self.difficulty == "mixed" else (count, count)
        slots = [(row, by_code[row["workbook_code"]]) for row in plan for _ in range(row["questions"])]
        if not self._enough_stock(plan, by_code, low):
            return None  # T063: a cheap count proves the shortage before any search
        levels: Counter[str] = Counter()
        chosen: list[dict[str, Any]] = []  # candidate rows, in slot order
        failed: set[frozenset[str]] = set()
        budget = [SEARCH_LIMIT]

        def options(index: int) -> list[dict[str, Any]]:
            row, objective = slots[index]
            ordinals = {e["id"]: e["ordinal"] for e in objective["evidences"]}
            mine = [c for c, (r, _) in zip(chosen, slots) if r is row]
            uses = Counter(c["evidence_id"] for c in mine)
            items = [c["item"] for c in chosen]
            usable = [c for c in self._candidates(objective) if levels[c["difficulty"]] < high
                      and all(c["item"]["item_id"] != i["item_id"] for i in items)
                      and duplicate_reason(c["item"], items) is None]
            # Spread evidencias first, then the level furthest below its share, then unseen; ties by ordinal,
            # then at random among equals.
            noise = {id(c): secrets.randbits(32) for c in usable}
            return sorted(usable, key=lambda c: (uses[c["evidence_id"]], levels[c["difficulty"]],
                                                 c["item"]["item_id"] in self.seen, ordinals[c["evidence_id"]],
                                                 MIXED_CYCLE.index(c["difficulty"]), noise[id(c)]))

        def search(index: int) -> bool:
            if index == len(slots):
                return all(levels[level] >= low for level in self.levels)
            short = sum(max(0, low - levels[level]) for level in self.levels)
            key = frozenset(c["request_id"] for c in chosen)
            if short > len(slots) - index or key in failed or budget[0] <= 0:
                return False
            budget[0] -= 1
            for c in options(index):
                chosen.append(c)
                levels[c["difficulty"]] += 1
                if search(index + 1):
                    return True
                chosen.pop()
                levels[c["difficulty"]] -= 1
            failed.add(key)
            return False

        if not search(0):
            return None
        allocation, picks = [], []
        for row in plan:
            ordinals = {e["id"]: e["ordinal"] for e in by_code[row["workbook_code"]]["evidences"]}
            rows = []
            for c in chosen[len(picks):len(picks) + row["questions"]]:
                slot = len(picks) + 1
                rows.append({"slot": slot, "evidence_id": c["evidence_id"],
                             "evidence_ordinal": ordinals[c["evidence_id"]], "difficulty": c["difficulty"]})
                picks.append({"slot": slot, "objective_code": row["workbook_code"], "evidence_id": c["evidence_id"],
                              "item": c["item"], "source": "bank", "source_request_id": c["request_id"]})
            allocation.append({**row, "evidences_covered": len({s["evidence_id"] for s in rows}), "slots": rows})
        return allocation, picks

    def _enough_stock(self, plan: list[dict[str, Any]], by_code: dict[str, Any], low: int) -> bool:
        """Necessary conditions only: each objective holds as many distinct questions as its slots, and each
        required level holds its minimum share across the practice. False means no search can succeed."""
        per_level: Counter[str] = Counter()
        for row in plan:
            if not row["questions"]:
                continue
            rows = self._candidates(by_code[row["workbook_code"]])
            if len({c["item"]["item_id"] for c in rows}) < row["questions"]:
                return False
            for c in {c["item"]["item_id"]: c for c in rows}.values():
                per_level[c["difficulty"]] += 1
        return all(per_level[level] >= low for level in self.levels)

    def available_sizes(self, sizes: tuple[int, ...]) -> list[int]:
        """T063: the permitted sizes the bank composes now, checked by the real composer in ascending order.

        Checking stops at the first size that does not compose, so a size is offered only when every smaller
        one is (never more questions than the bank genuinely holds; at worst a size is offered late).
        """
        ready = []
        for size in sorted(sizes):
            if self.compose(size) is None:
                break
            ready.append(size)
        return ready

    def compose_or_shortage(self, count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """A complete practice of `count`; raises Shortage with the largest smaller permitted size that fits."""
        result = self.compose(count)
        if result is not None:
            return result
        largest = next((n for n in sorted(QUESTION_COUNTS, reverse=True) if n < count and self.compose(n)), 0)
        raise Shortage(count, largest)


DIFFICULTIES = ("mixed", "easy", "medium", "hard")


def readiness(bank: Any, catalog: Any, baseline: str, subject: str,
              objectives: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only bank-only readiness for a subject (T056): what the real composer can assemble now.

    Counts only (no question text): eligible questions per objective and difficulty, and for each difficulty
    the largest permitted whole-subject size it composes plus the objectives the size-5 plan needs but lacks.
    """
    first = BankComposer(bank, catalog, baseline, subject, objectives, "mixed")
    inventory: dict[str, dict[str, int]] = {}
    for objective in objectives:
        counts = Counter(c["difficulty"] for c in first._candidates(objective))
        if counts:
            inventory[objective["workbook_code"]] = dict(sorted(counts.items()))
    by_difficulty = {}
    for difficulty in DIFFICULTIES:
        composer = BankComposer(bank, catalog, baseline, subject, objectives, difficulty)
        plan = allocate(objectives, 5, difficulty)["allocation"]
        levels = MIXED_CYCLE if difficulty == "mixed" else (difficulty,)
        missing = [r["workbook_code"] for r in plan if r["questions"]
                   and not any(inventory.get(r["workbook_code"], {}).get(level) for level in levels)]
        largest = next((n for n in sorted(QUESTION_COUNTS, reverse=True) if composer.compose(n)), 0)
        by_difficulty[difficulty] = {"size5_objectives": [r["workbook_code"] for r in plan if r["questions"]],
                                     "missing_objectives": missing, "largest_size": largest}
    return {"subject": subject, "eligible": sum(sum(v.values()) for v in inventory.values()),
            "seen": len(bank.seen_questions()), "inventory": inventory, "composition": by_difficulty}
