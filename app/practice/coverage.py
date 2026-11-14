"""Coverage deficits from the real composer and the generation priority they imply (T067, ADR-036).

`report` asks the bank composer (`BankComposer.compose`) which whole-subject practice sizes compose now and,
for each size, what the allocation needs that the approved bank lacks:

- mixed practices of every permitted size (5..30): per objective, the questions the allocation assigns minus
  the distinct eligible questions it holds; per level, the minimum share (`level_bounds`) minus what is held;
- single-level practices of size 5 (easy, medium, hard): the same per objective, for that level only.

A size is reported `composes: true` only when the composer assembles it; the shortfalls are the counted
necessary conditions, so a size can fail with no counted shortfall (duplicates or evidencia spread), reported
as such. Counts only, no question text.

`priorities` orders objectives for generation (PO-QBANK-COMPLETION-2026-11-14, T067):

1. the objectives (and levels) blocking the smallest mixed size that does not compose;
2. objectives with no eligible question at all;
3. objectives blocking a single-level size-5 practice, at that level;
4. objectives blocking a larger mixed size, smallest size first;
5. everything else (inventory depth), then performance (mastered) requests.

Within a tier, objectives whose recent content yield is zero come after the others, then by objective code.
Levels within an objective: the level the deficit names first, then levels without a zero content yield; then,
for unblocking tiers (1-3), easy, medium, hard (hard is rejected for difficulty most often), and for depth
tiers (4-5) the level the subject holds least of. The fixed 100-cell plan, its objectives and its cells are unchanged:
the order only decides which planned gap cells are tried first.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.allocation import MIXED_CYCLE, QUESTION_COUNTS, allocate
from app.practice.bank_allocation import BankComposer, level_bounds

LEVELS = ("easy", "medium", "hard")
TIER_NAMES = {1: "unblock_smallest_size", 2: "missing_objective", 3: "single_level_coverage",
              4: "next_size", 5: "depth", 6: "performance"}
LOW_YIELD_MIN = 3  # content attempts (accepted or rejected) with none accepted before a cell is "low yield"


def held(bank: Any, catalog: Any, baseline: str, subject: str,
         objectives: list[dict[str, Any]]) -> tuple[BankComposer, dict[str, Counter[str]]]:
    """The mixed composer and, per objective, distinct eligible questions per level."""
    composer = BankComposer(bank, catalog, baseline, subject, objectives, "mixed")
    counts: dict[str, Counter[str]] = {}
    for o in objectives:
        rows = {c["item"]["item_id"]: c["difficulty"] for c in composer._candidates(o)}
        counts[o["workbook_code"]] = Counter(rows.values())
    return composer, counts


def _deficit(objectives: list[dict[str, Any]], counts: dict[str, Counter[str]], size: int,
             difficulty: str) -> dict[str, Any]:
    plan = allocate(objectives, size, difficulty)["allocation"]
    levels = MIXED_CYCLE if difficulty == "mixed" else (difficulty,)
    low = level_bounds(size)[0] if difficulty == "mixed" else size
    objectives_short = {}
    for row in plan:
        if not row["questions"]:
            continue
        have = sum(counts[row["workbook_code"]][level] for level in levels)
        if have < row["questions"]:
            objectives_short[row["workbook_code"]] = {"needed": row["questions"], "held": have}
    in_plan = [row["workbook_code"] for row in plan if row["questions"]]
    levels_short = {}
    for level in levels:
        have = sum(counts[code][level] for code in in_plan)
        if have < low:
            levels_short[level] = {"needed": low, "held": have}
    return {"objectives": objectives_short, "levels": levels_short}


def report(bank: Any, catalog: Any, baseline: str, subject: str,
           objectives: list[dict[str, Any]]) -> dict[str, Any]:
    """Read-only: which sizes compose now and exactly what each missing size still needs."""
    composer, counts = held(bank, catalog, baseline, subject, objectives)
    mixed = []
    for size in sorted(QUESTION_COUNTS):
        composes = composer.compose(size) is not None
        entry = {"size": size, "composes": composes}
        if not composes:
            entry.update(_deficit(objectives, counts, size, "mixed"))
        mixed.append(entry)
    single = {}
    for level in LEVELS:
        one = BankComposer(bank, catalog, baseline, subject, objectives, level, db=composer.db)
        composes = one.compose(5) is not None
        single[level] = {"size": 5, "composes": composes,
                         **({} if composes else _deficit(objectives, counts, 5, level))}
    available = [e["size"] for e in mixed if e["composes"]]
    return {"subject": subject,
            "eligible": sum(sum(c.values()) for c in counts.values()),
            "held": {code: dict(sorted(c.items())) for code, c in counts.items() if c},
            "available_mixed": available,
            "smallest_missing_mixed": next((e["size"] for e in mixed if not e["composes"]), None),
            "mixed": mixed, "single_level_size5": single}


def priorities(cov: dict[str, Any], codes: list[str],
               yields: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    """objective -> {rank, tier, tier_name, size, levels}: the generation order (lower rank first)."""
    yields = yields or {}
    level_total = Counter()
    for c in cov["held"].values():
        level_total.update(c)
    found: dict[str, dict[str, Any]] = {}

    def add(code: str, tier: int, size: int | None, levels: list[str]) -> None:
        if code not in found:
            found[code] = {"tier": tier, "size": size, "need_levels": list(levels)}
        elif found[code]["tier"] == tier:
            found[code]["need_levels"] += [lv for lv in levels if lv not in found[code]["need_levels"]]

    missing = [e for e in cov["mixed"] if not e["composes"]]
    if missing:
        first = missing[0]
        short_levels = list(first["levels"])
        for code in sorted(first["objectives"]):
            add(code, 1, first["size"], short_levels)
        if not first["objectives"] and short_levels:  # level share only: any objective of the subject helps
            for code in codes:
                add(code, 1, first["size"], short_levels)
    for code in codes:
        if not cov["held"].get(code):
            add(code, 2, None, [])
    for level in LEVELS:
        for code in sorted(cov["single_level_size5"][level].get("objectives", {})):
            add(code, 3, 5, [level])
    for entry in missing[1:]:
        for code in sorted(entry["objectives"]):
            add(code, 4, entry["size"], list(entry["levels"]))
    for code in codes:
        add(code, 5, None, [])

    def low_yield(code: str, level: str) -> bool:
        y = yields.get((code, level), {})
        return y.get("content_attempts", 0) >= LOW_YIELD_MIN and not y.get("accepted", 0)

    out = {}
    for code, f in found.items():
        need = [lv for lv in MIXED_CYCLE if lv in f["need_levels"]]
        # Unblocking (tiers 1-3) wants any accepted question soonest: easy, medium, hard (hard questions are the
        # most often rejected for difficulty). Depth (tiers 4-5) builds the level the subject holds least of.
        balance = f["tier"] >= 4
        rest = sorted((lv for lv in LEVELS if lv not in need),
                      key=lambda lv: (low_yield(code, lv), level_total[lv] if balance else 0, LEVELS.index(lv)))
        out[code] = {"tier": f["tier"], "tier_name": TIER_NAMES[f["tier"]], "size": f["size"],
                     "levels": need + rest, "low_yield": all(low_yield(code, lv) for lv in LEVELS)}
    ordered = sorted(out, key=lambda c: (out[c]["tier"], out[c]["low_yield"], c))
    for rank, code in enumerate(ordered):
        out[code]["rank"] = rank
    return out
