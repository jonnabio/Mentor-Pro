"""Deterministic balanced allocation (pure function)."""

import pytest

from app.allocation import allocate


def objectives(*spec):
    """spec: (code, evidence_count) pairs."""
    return [{"workbook_code": code,
             "evidences": [{"id": f"{code}-E{i}", "ordinal": i} for i in range(1, n + 1)]}
            for code, n in spec]


def counts(result):
    return {a["workbook_code"]: a["questions"] for a in result["allocation"]}


def test_even_split():
    result = allocate(objectives(("M01", 3), ("M02", 3)), 10, "easy")
    assert counts(result) == {"M01": 5, "M02": 5}
    assert result["uncovered_codes"] == []


def test_remainder_goes_to_first_codes_in_order():
    result = allocate(objectives(("M03", 2), ("M01", 2), ("M02", 2)), 10, "easy")
    assert counts(result) == {"M01": 4, "M02": 3, "M03": 3}


def test_result_independent_of_selection_order():
    a = allocate(objectives(("C02", 4), ("C01", 1), ("C03", 2)), 20, "mixed")
    b = allocate(objectives(("C03", 2), ("C02", 4), ("C01", 1)), 20, "mixed")
    assert a == b


def test_repeated_calls_are_identical():
    spec = objectives(*[(f"ES{i:02d}", 3) for i in range(1, 30)])
    assert allocate(spec, 30, "mixed") == allocate(spec, 30, "mixed")


def test_fewer_questions_than_objectives_uses_spread_subset():
    spec = objectives(*[(f"M{i:02d}", 2) for i in range(1, 23)])  # 22 objectives
    result = allocate(spec, 5, "medium")
    assert sum(counts(result).values()) == 5
    assert result["covered_codes"] == ["M01", "M05", "M09", "M14", "M18"]
    assert len(result["uncovered_codes"]) == 17
    assert set(result["covered_codes"]).isdisjoint(result["uncovered_codes"])


def test_evidences_cycle_before_repeating():
    result = allocate(objectives(("EL01", 3)), 5, "easy")
    assert [s["evidence_ordinal"] for s in result["allocation"][0]["slots"]] == [1, 2, 3, 1, 2]
    assert result["allocation"][0]["evidences_covered"] == 3


def test_mixed_difficulty_cycles_globally():
    result = allocate(objectives(("M01", 1), ("M02", 1)), 5, "mixed")
    levels = [s["difficulty"] for a in result["allocation"] for s in a["slots"]]
    assert levels == ["easy", "medium", "hard", "easy", "medium"]


def test_fixed_difficulty_applies_to_all():
    result = allocate(objectives(("M01", 2)), 10, "hard")
    assert {s["difficulty"] for s in result["allocation"][0]["slots"]} == {"hard"}


def test_slots_are_numbered_sequentially():
    result = allocate(objectives(("M01", 2), ("M02", 2)), 10, "easy")
    assert [s["slot"] for a in result["allocation"] for s in a["slots"]] == list(range(1, 11))


@pytest.mark.parametrize(("spec", "n", "difficulty"), [
    (objectives(("M01", 1)), 5, "extreme"),
    (objectives(("M01", 1)), 0, "easy"),
    ([], 5, "easy"),
    (objectives(("M01", 0)), 5, "easy"),
])
def test_invalid_inputs(spec, n, difficulty):
    with pytest.raises(ValueError):
        allocate(spec, n, difficulty)
