"""Quiz-size capacity: what a practice of each size needs, per stage (T069, PO-T069-2026-11-16).

Pure counting, no I/O. A practice of `size` questions over a subject's objectives needs, per objective, the
questions `allocate` assigns (D2: never swapped), each a distinct question of that objective, and per level the
share the composer requires: within ±1 of a third for "mixed" (`level_bounds`), every question for an explicit
level. Whether a set of per-objective, per-level counts can meet both at once is a small flow problem; `shortfall`
solves it exactly and returns the fewest extra questions (or plan cells) that would make it feasible, and where.

The same check runs on four supplies, so the first stage that fails names the cause:

1. allocation: the curriculum allocation itself (every allocated objective has evidencias);
2. plan: the fixed seeding plan's cells (`seeding.DEFAULT_TARGET` = 100 per subject). The seeder fills one
   question per planned cell, so the plan bounds what generation can ever supply: a failure here is structural;
3. generated: approved plus pending-review questions (generated, not yet decided by the tutor);
4. approved: the eligible questions the composer can serve now.

Counts are necessary conditions. The real composer (`BankComposer.compose`) is still the only authority on
whether a size composes: it also refuses near duplicates, so a size can pass every count and still not compose.
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from itertools import product
from typing import Any

from app.allocation import MIXED_CYCLE, QUESTION_COUNTS, allocate
from app.practice.bank_allocation import level_bounds

Supply = Mapping[str, Mapping[str, int]]  # objective code -> level -> distinct questions (or plan cells)
STAGES = ("allocation", "plan", "generated", "approved")


def levels_for(difficulty: str) -> tuple[str, ...]:
    return MIXED_CYCLE if difficulty == "mixed" else (difficulty,)


def demand(objectives: list[dict[str, Any]], size: int, difficulty: str) -> dict[str, int]:
    """Questions per objective that a practice of `size` allocates (objectives with none are left out)."""
    plan = allocate(objectives, size, difficulty)["allocation"]
    return {row["workbook_code"]: row["questions"] for row in plan if row["questions"]}


def plan_cells(objectives: list[dict[str, Any]], target: int) -> dict[str, Counter[str]]:
    """Cells per objective and level in a seeding plan of `target` cells (the same `allocate` as `build_plan`)."""
    cells: dict[str, Counter[str]] = {o["workbook_code"]: Counter() for o in objectives}
    for row in allocate(objectives, target, "mixed")["allocation"]:
        cells[row["workbook_code"]].update(s["difficulty"] for s in row["slots"])
    return cells


def _max_flow(need: dict[str, int], supply: Supply, quota: dict[str, int]) -> tuple[int, dict[tuple[str, str], int]]:
    """Max flow source -> objective (need) -> level (supply) -> sink (quota); returns the value and the edge flows."""
    cap: dict[tuple[str, str], int] = {}
    adj: dict[str, list[str]] = {}

    def edge(a: str, b: str, c: int) -> None:
        cap[(a, b)] = cap.get((a, b), 0) + c
        cap.setdefault((b, a), 0)
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)

    for code, n in need.items():
        edge("S", f"o:{code}", n)
        for level in quota:
            edge(f"o:{code}", f"l:{level}", int(supply.get(code, {}).get(level, 0)))
    for level, q in quota.items():
        edge(f"l:{level}", "T", q)
    total = 0
    while True:
        parent: dict[str, str] = {"S": "S"}
        queue = deque(["S"])
        while queue and "T" not in parent:
            a = queue.popleft()
            for b in adj.get(a, ()):
                if b not in parent and cap[(a, b)] > 0:
                    parent[b] = a
                    queue.append(b)
        if "T" not in parent:
            break
        path, b = [], "T"
        while b != "S":
            path.append((parent[b], b))
            b = parent[b]
        push = min(cap[e] for e in path)
        for a, b in path:
            cap[(a, b)] -= push
            cap[(b, a)] += push
        total += push
    flows = {(code, level): cap[(f"l:{level}", f"o:{code}")] for code in need for level in quota}
    return total, flows


def shortfall(need: dict[str, int], supply: Supply, size: int, difficulty: str) -> dict[str, Any]:
    """Fewest extra questions that make `supply` fill `need` within the level share, and where they go.

    Every split of the practice over levels within the share is tried; the best one leaves `missing` slots
    unfilled. Each unfilled slot needs one more question of an objective still short and a level still short
    (the two totals are equal), so `missing` is exact. `objectives` and `levels` say which are short in that
    best split; `objective_only` counts what the objectives lack whatever their level.
    """
    levels = levels_for(difficulty)
    low, high = level_bounds(size) if difficulty == "mixed" else (size, size)
    best: tuple[int, dict[str, int], dict[tuple[str, str], int]] | None = None
    for split in product(range(low, high + 1), repeat=len(levels)):
        if sum(split) != size:
            continue
        quota = dict(zip(levels, split))
        value, flows = _max_flow(need, supply, quota)
        if best is None or value > best[0]:
            best = (value, quota, flows)
        if value == size:
            break
    assert best is not None  # some split always sums to `size` (level_bounds spans a third of it)
    value, quota, flows = best
    short_objectives = {code: {"needed": n, "fillable": sum(flows[(code, lv)] for lv in levels)}
                        for code, n in need.items() if sum(flows[(code, lv)] for lv in levels) < n}
    short_levels = {lv: {"needed": quota[lv], "fillable": sum(flows[(code, lv)] for code in need)}
                    for lv in levels if sum(flows[(code, lv)] for code in need) < quota[lv]}
    objective_only = sum(max(0, n - sum(int(supply.get(code, {}).get(lv, 0)) for lv in levels))
                         for code, n in need.items())
    return {"missing": size - value, "objective_only": objective_only,
            "objectives": short_objectives, "levels": short_levels}


def cause(gap: dict[str, Any]) -> str | None:
    """Why a supply falls short: objectives lack questions outright, or only the level balance fails."""
    if not gap["missing"]:
        return None
    return "objective_count" if gap["objective_only"] else "difficulty_distribution"


def stages(objectives: list[dict[str, Any]], size: int, difficulty: str, plan: Supply,
           pending: Supply, approved: Supply, composes: bool | None = None) -> dict[str, Any]:
    """The four count stages for one practice choice, plus the composer's verdict when given.

    `first_failure` is the earliest stage that fails; `blocker` classifies the remaining gap:
    structural (the plan cannot hold the practice), generation (planned but not generated yet), review
    (generated, awaiting the tutor), or duplicates (counts suffice, the composer still refuses: near duplicates).
    """
    by_code = {o["workbook_code"]: o for o in objectives}
    need = demand(objectives, size, difficulty)
    no_evidence = [code for code in need if not by_code[code]["evidences"]]
    generated = {code: Counter(approved.get(code, {})) + Counter(pending.get(code, {})) for code in by_code}
    gaps = {"plan": shortfall(need, plan, size, difficulty),
            "generated": shortfall(need, generated, size, difficulty),
            "approved": shortfall(need, approved, size, difficulty)}
    ok = {"allocation": not no_evidence, **{k: not g["missing"] for k, g in gaps.items()}}
    first = next((s for s in STAGES if not ok[s]), None)
    if first is None:
        blocker = None if composes in (None, True) else "duplicates"
    elif first in ("allocation", "plan") and not ok["approved"]:
        blocker = "structural"
    else:
        blocker = {"plan": None, "generated": "generation", "approved": "review"}.get(first)
    return {"size": size, "difficulty": difficulty, "ok": ok, "first_failure": first, "blocker": blocker,
            "composes": composes, "need": need, "missing": {k: g["missing"] for k, g in gaps.items()},
            "cause": {k: cause(g) for k, g in gaps.items()}, "approved_gap": gaps["approved"],
            "plan_gap": gaps["plan"]}


def structural(objectives: list[dict[str, Any]], target: int,
               sizes: tuple[int, ...] = QUESTION_COUNTS) -> dict[str, Any]:
    """Can the plan of `target` cells hold every size? Whole subject (each difficulty) and each single objective.

    For every choice the minimum extra plan cells is exact (`shortfall` on the plan alone). Single-objective
    practices are reported per objective with the largest size the plan holds at each difficulty.
    """
    cells = plan_cells(objectives, target)
    whole = {}
    for difficulty in ("mixed", *MIXED_CYCLE):
        whole[difficulty] = [{"size": n, "extra_cells": shortfall(demand(objectives, n, difficulty), cells, n,
                                                                  difficulty)["missing"]} for n in sizes]
    single = {}
    for o in objectives:
        mine = [o]
        row = {"cells": dict(sorted(cells[o["workbook_code"]].items())), "evidences": len(o["evidences"])}
        for difficulty in ("mixed", *MIXED_CYCLE):
            fits = [n for n in sizes if not shortfall(demand(mine, n, difficulty), cells, n, difficulty)["missing"]]
            row[difficulty] = {"largest": max(fits, default=0),
                               "extra_cells_for_max": shortfall(demand(mine, max(sizes), difficulty), cells,
                                                                max(sizes), difficulty)["missing"]}
        single[o["workbook_code"]] = row
    return {"target": target, "objectives": len(objectives), "whole_subject": whole, "single_objective": single}
