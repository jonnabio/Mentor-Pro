"""Deterministic, balanced allocation of practice questions (no I/O, no randomness).

Rules:
  1. Objectives are ordered by workbook code, so the same selection always
     yields the same allocation regardless of the order the student clicked.
  2. question_count >= objectives: every objective gets floor(n / k) questions;
     the first (n mod k) objectives in order get one extra.
  3. question_count < objectives: a deterministic, evenly spaced subset of n
     objectives (index floor(i * k / n)) gets one question each; the rest are
     reported as not covered.
  4. Within an objective, questions cycle through its evidencias in ordinal
     order, so evidence coverage is spread before any evidencia repeats.
  5. Difficulty "mixed" cycles easy -> medium -> hard over the global question
     sequence; other levels apply to every question.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

DIFFICULTIES = ("easy", "medium", "hard", "mixed")
MIXED_CYCLE = ("easy", "medium", "hard")
QuestionCount = Literal[5, 10, 15, 20, 25, 30]  # permitted practice sizes (T048)
QUESTION_COUNTS: tuple[int, ...] = get_args(QuestionCount)


def _spread_subset(count: int, size: int) -> list[int]:
    """Indices of `count` items spread evenly over `size` items (count < size)."""
    return [i * size // count for i in range(count)]


def allocate(objectives: list[dict[str, Any]], question_count: int, difficulty: str) -> dict[str, Any]:
    """Allocate `question_count` questions over `objectives`.

    @param objectives - catalog objectives, each with "workbook_code" and "evidences"
    @returns {"allocation": [...], "covered_codes": [...], "uncovered_codes": [...]}
    @throws ValueError for an unknown difficulty, a non-positive count or no objectives
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty {difficulty!r}")
    if question_count < 1:
        raise ValueError("question_count must be positive")
    if not objectives:
        raise ValueError("no objectives to allocate")

    ordered = sorted(objectives, key=lambda o: o["workbook_code"])
    k = len(ordered)
    if question_count >= k:
        base, extra = divmod(question_count, k)
        counts = [base + (1 if i < extra else 0) for i in range(k)]
    else:
        chosen = set(_spread_subset(question_count, k))
        counts = [1 if i in chosen else 0 for i in range(k)]

    allocation: list[dict[str, Any]] = []
    sequence = 0
    for objective, n in zip(ordered, counts):
        if n == 0:
            continue
        evidences = sorted(objective["evidences"], key=lambda e: e["ordinal"])
        if not evidences:
            raise ValueError(f"objective {objective['workbook_code']} has no evidencias")
        slots = []
        for j in range(n):
            level = MIXED_CYCLE[sequence % 3] if difficulty == "mixed" else difficulty
            evidence = evidences[j % len(evidences)]
            slots.append({"slot": sequence + 1, "evidence_id": evidence["id"],
                          "evidence_ordinal": evidence["ordinal"], "difficulty": level})
            sequence += 1
        allocation.append({
            "workbook_code": objective["workbook_code"],
            "questions": n,
            "evidences_covered": len({s["evidence_id"] for s in slots}),
            "evidences_total": len(evidences),
            "slots": slots,
        })

    covered = [a["workbook_code"] for a in allocation]
    uncovered = [o["workbook_code"] for o, n in zip(ordered, counts) if n == 0]
    return {"allocation": allocation, "covered_codes": covered, "uncovered_codes": uncovered}
