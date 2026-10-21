"""Exact arithmetic and es-CR number parsing (math-answer-verification)."""

from fractions import Fraction

import pytest

from cr_math import AmbiguousNumberError, evaluate, parse_number, parse_quantity


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12 500", Fraction(12500)),
        ("1 000 000", Fraction(1000000)),
        ("9498,5", Fraction(18997, 2)),
        ("3,25", Fraction(13, 4)),
        ("0,05", Fraction(1, 20)),
        ("3/4", Fraction(3, 4)),
        ("2 1/2", Fraction(5, 2)),
        ("2 100/200", Fraction(5, 2)),
        ("-7", Fraction(-7)),
        ("−3", Fraction(-3)),
        ("12 500", Fraction(12500)),
    ],
)
def test_parse_number_accepts_mep_formats(text, expected):
    assert parse_number(text) == expected


@pytest.mark.parametrize("text", ["1.000", "2.5", "12.500,75"])
def test_parse_number_rejects_dot_separators_as_ambiguous(text):
    with pytest.raises(AmbiguousNumberError):
        parse_number(text)


@pytest.mark.parametrize("text", ["", "abc", "3/0", "12 50"])
def test_parse_number_rejects_non_numbers(text):
    with pytest.raises(ValueError):
        parse_number(text)


@pytest.mark.parametrize(
    ("text", "value", "unit"),
    [
        ("2,5 kg", Fraction(5, 2), "kg"),
        ("₡12 500", Fraction(12500), "₡"),
        ("15 cm", Fraction(15), "cm"),
        ("12", Fraction(12), ""),
    ],
)
def test_parse_quantity_splits_value_and_unit(text, value, unit):
    assert parse_quantity(text) == (value, unit)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("144 / 12", Fraction(12)),
        ("0,1 + 0,2", Fraction(3, 10)),
        ("2 * (8 + 5)", Fraction(26)),
        ("(7 + 9 + 8) / 3", Fraction(8)),
        ("3/4 + 1/8", Fraction(7, 8)),
        ("2,5 × 1000", Fraction(2500)),
        ("-3 + 5", Fraction(2)),
    ],
)
def test_evaluate_is_exact(expression, expected):
    assert evaluate(expression) == expected


@pytest.mark.parametrize("expression", ['__import__("os")', "2 ** 8", "x + 1", "abs(-1)", "1 if 1 else 2"])
def test_evaluate_rejects_non_arithmetic(expression):
    with pytest.raises(ValueError):
        evaluate(expression)


def test_evaluate_rejects_dots_and_long_input():
    with pytest.raises(AmbiguousNumberError):
        evaluate("1.5 + 1")
    with pytest.raises(ValueError):
        evaluate("1+" * 150 + "1")


def test_evaluate_rejects_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        evaluate("5 / (2 - 2)")
