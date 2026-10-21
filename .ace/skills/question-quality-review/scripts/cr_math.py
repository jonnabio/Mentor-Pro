"""Exact arithmetic and Costa Rican (es-CR) number parsing.

Used by the deterministic item checker and the math-answer-verification skill.
All arithmetic is exact (fractions.Fraction); floats are never used.

Number formats accepted (MEP usage: decimal comma, thousands grouped by space):

    12 500      -> 12500        3,25     -> 13/4
    9498,5      -> 18997/2      3/4      -> 3/4
    2 1/2       -> 5/2 (mixed)  -7       -> -7

Rejected as ambiguous: a dot followed by exactly three digits ("1.000"),
because it reads as either one thousand or one.
"""

from __future__ import annotations

import ast
import re
from fractions import Fraction

__all__ = ["AmbiguousNumberError", "parse_number", "parse_quantity", "evaluate"]


class AmbiguousNumberError(ValueError):
    """Raised when a number string has more than one plausible reading."""


_INT_GROUPED = r"\d{1,3}(?: \d{3})+|\d+"
_RE_MIXED = re.compile(rf"^(-?)({_INT_GROUPED}) (\d+)/(\d+)$")
_RE_FRACTION = re.compile(r"^(-?)(\d+)/(\d+)$")
_RE_DECIMAL = re.compile(rf"^(-?)({_INT_GROUPED})(?:,(\d+))?$")


def parse_number(text: str) -> Fraction:
    """Parse an es-CR number string into an exact Fraction.

    @param text - number as written in an item, e.g. "12 500", "3,5", "2 1/2"
    @returns exact value
    @throws AmbiguousNumberError for "1.000"-style strings
    @throws ValueError when the string is not a number
    """
    s = " ".join(text.strip().replace("−", "-").replace(" ", " ").split())
    if not s:
        raise ValueError("empty number")

    m = _RE_MIXED.match(s)
    if m:
        sign, whole, num, den = m.groups()
        if int(den) == 0:
            raise ValueError(f"zero denominator: {text!r}")
        value = int(whole.replace(" ", "")) + Fraction(int(num), int(den))
        return -value if sign else value

    m = _RE_FRACTION.match(s)
    if m:
        sign, num, den = m.groups()
        if int(den) == 0:
            raise ValueError(f"zero denominator: {text!r}")
        value = Fraction(int(num), int(den))
        return -value if sign else value

    m = _RE_DECIMAL.match(s)
    if m:
        sign, whole, frac = m.groups()
        value = Fraction(int(whole.replace(" ", "")))
        if frac:
            value += Fraction(int(frac), 10 ** len(frac))
        return -value if sign else value

    if "." in s:
        raise AmbiguousNumberError(f"dot separator is ambiguous in MEP style: {text!r}")
    raise ValueError(f"not a number: {text!r}")


def parse_quantity(text: str) -> tuple[Fraction, str]:
    """Split an option such as "2,5 kg" or "₡12 500" into (value, unit).

    The colón sign is reported as the unit "₡". Unit is "" when absent.
    """
    raw = text.strip()
    unit = ""
    if raw.startswith("₡"):
        unit, raw = "₡", raw[1:].strip()
    m = re.match(r"^(.*?\d)\s*([^\d\s][^\d]*)?$", raw)
    if not m:
        raise ValueError(f"not a quantity: {text!r}")
    number, trailing = m.group(1), (m.group(2) or "").strip()
    if trailing:
        if unit:
            raise ValueError(f"two units in {text!r}")
        unit = trailing
    return parse_number(number), unit


_ALLOWED_BINOPS = {ast.Add, ast.Sub, ast.Mult, ast.Div}
MAX_EXPRESSION_LENGTH = 200


def evaluate(expression: str) -> Fraction:
    """Evaluate + - * / ( ) over es-CR numbers exactly.

    Numbers use plain digits or a decimal comma ("2,5"); write thousands
    without separators inside expressions ("12500"). Dots, names, calls and
    any other syntax are rejected.
    """
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"expression longer than {MAX_EXPRESSION_LENGTH} characters")
    if "." in expression:
        raise AmbiguousNumberError("dots are not allowed in expressions")
    normalized = expression.replace("×", "*").replace("÷", "/").replace("−", "-")
    # Decimal comma -> exact fraction literal, e.g. "2,5" -> "(25/10)".
    normalized = re.sub(
        r"(\d+),(\d+)",
        lambda m: f"({int(m.group(1) + m.group(2))}/{10 ** len(m.group(2))})",
        normalized,
    )
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {expression!r}") from exc
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return Fraction(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval_node(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise ZeroDivisionError("division by zero in expression")
        return left / right
    raise ValueError(f"unsupported syntax: {ast.dump(node)}")
