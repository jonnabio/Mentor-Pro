"""T069: quiz-size capacity counting (pure, no database): exact shortfall, stages and the plan's structure."""

from __future__ import annotations

from collections import Counter

import pytest

from app.allocation import QUESTION_COUNTS
from app.practice import capacity
from app.practice.bank_allocation import BankComposer
from test_bank_only_practice import FakeBank, objectives, stock


def supply(**cells):
    """supply(M01="eemh") -> {"M01": Counter(easy=2, medium=1, hard=1)}"""
    names = {"e": "easy", "m": "medium", "h": "hard"}
    return {code: Counter(names[c] for c in spec) for code, spec in cells.items()}


def test_enough_per_objective_and_per_level_has_no_shortfall():
    objs = objectives(2)
    need = capacity.demand(objs, 6, "mixed")
    assert need == {"M01": 3, "M02": 3}
    gap = capacity.shortfall(need, supply(M01="emh", M02="emh"), 6, "mixed")
    assert gap == {"missing": 0, "objective_only": 0, "objectives": {}, "levels": {}}


def test_an_objective_short_of_questions_is_counted_exactly():
    gap = capacity.shortfall({"M01": 3, "M02": 3}, supply(M01="emh", M02="e"), 6, "mixed")
    assert gap["missing"] == 2 and gap["objective_only"] == 2
    assert gap["objectives"] == {"M02": {"needed": 3, "fillable": 1}}
    assert capacity.cause(gap) == "objective_count"


def test_a_level_balance_failure_is_not_an_objective_count_failure():
    # 6 questions per objective, but all easy: mixed 6 needs at least one of each level (bounds 1..3).
    gap = capacity.shortfall({"M01": 3, "M02": 3}, supply(M01="eee", M02="eee"), 6, "mixed")
    assert gap["objective_only"] == 0 and gap["missing"] == 3
    assert set(gap["levels"]) == {"medium", "hard"}
    assert capacity.cause(gap) == "difficulty_distribution"


def test_an_explicit_level_counts_only_that_level():
    gap = capacity.shortfall({"M01": 2, "M02": 3}, supply(M01="eeh", M02="hhh"), 5, "hard")
    assert gap["missing"] == 1 and gap["objectives"] == {"M01": {"needed": 2, "fillable": 1}}


@pytest.mark.parametrize("per_cell,levels", [(1, ("easy", "medium", "hard")), (2, ("easy", "medium")),
                                              (1, ("hard",)), (3, ("easy", "medium", "hard"))])
def test_counts_never_promise_a_size_the_composer_cannot_build(per_cell, levels):
    """Counting is a necessary condition: whenever the composer builds a size, the counts allow it too, and with
    distinct questions (no near duplicates) the two agree exactly."""
    objs = objectives(4)
    rows = stock(objs, per_cell, levels=levels)
    held = {o["workbook_code"]: Counter() for o in objs}
    for r in rows:
        held[r["objective_code"]][r["difficulty"]] += 1
    for difficulty in ("mixed", "easy", "medium", "hard"):
        comp = BankComposer(FakeBank(rows), None, "TEST-v1", "matematicas", objs, difficulty)
        for size in QUESTION_COUNTS:
            counted = not capacity.shortfall(capacity.demand(objs, size, difficulty), held, size, difficulty)["missing"]
            assert counted == (comp.compose(size) is not None), (per_cell, levels, difficulty, size)


def test_stages_name_the_first_failure_and_the_blocker():
    objs = objectives(2)
    plan = capacity.plan_cells(objs, 6)
    assert {k: sum(v.values()) for k, v in plan.items()} == {"M01": 3, "M02": 3}
    empty = {o["workbook_code"]: Counter() for o in objs}
    full = supply(M01="emh", M02="emh")
    # Planned, nothing generated: generation is missing.
    s = capacity.stages(objs, 6, "mixed", plan, empty, empty)
    assert (s["first_failure"], s["blocker"]) == ("generated", "generation")
    # Generated, awaiting the tutor: review is missing.
    s = capacity.stages(objs, 6, "mixed", plan, full, empty)
    assert (s["first_failure"], s["blocker"], s["missing"]["approved"]) == ("approved", "review", 6)
    # Approved: every count passes; the composer's verdict decides (near duplicates otherwise).
    assert capacity.stages(objs, 6, "mixed", plan, empty, full, composes=True)["blocker"] is None
    assert capacity.stages(objs, 6, "mixed", plan, empty, full, composes=False)["blocker"] == "duplicates"
    # Larger than the plan holds and not already approved: structural.
    s = capacity.stages(objs, 10, "mixed", plan, empty, full)
    assert (s["first_failure"], s["blocker"], s["missing"]["plan"]) == ("plan", "structural", 4)


def test_structural_reports_whole_subject_and_single_objective_limits():
    objs = objectives(4)
    out = capacity.structural(objs, 100)
    assert all(r["extra_cells"] == 0 for r in out["whole_subject"]["mixed"])     # 25 cells per objective
    m01 = out["single_objective"]["M01"]
    assert sum(m01["cells"].values()) == 25 and m01["mixed"]["largest"] == 25
    assert m01["mixed"]["extra_cells_for_max"] == 5                              # 30 - 25
    small = capacity.structural(objs, 12)                                        # 3 cells per objective
    assert [r["extra_cells"] for r in small["whole_subject"]["mixed"]] == [0, 0, 3, 8, 13, 18]
