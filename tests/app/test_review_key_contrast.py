"""M5: the proposed answer in the tutor's question review must be readable in both colour schemes.

The T068 rule fixed a pale background without a text colour, so in dark mode the theme's light text sat on a
light background. The rule must use the theme tokens, and each scheme must meet WCAG AA contrast (4.5:1).
"""

from __future__ import annotations

import re
from pathlib import Path

STYLES = Path(__file__).resolve().parents[2] / "app" / "static" / "styles.css"


def _css() -> str:
    return STYLES.read_text(encoding="utf-8")


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block))


def _schemes() -> dict[str, dict[str, str]]:
    css = _css()
    light = _tokens(re.search(r"^:root\s*\{(.*?)\}", css, re.S | re.M).group(1))
    dark = {**light, **_tokens(re.search(r"prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{(.*?)\}", css, re.S).group(1))}
    return {"light": light, "dark": dark}


def _luminance(hex_colour: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _review_key_rule() -> str:
    match = re.search(r"\.review-options li\.review-key\s*\{(.*?)\}", _css(), re.S)
    assert match, "review-key rule missing"
    return match.group(1)


def test_review_key_uses_theme_tokens_only():
    rule = _review_key_rule()
    assert "var(--text)" in rule and "var(--accent-soft)" in rule and "var(--accent)" in rule
    assert not re.search(r"#[0-9a-fA-F]{3,6}", rule), "hard-coded colours break one of the schemes"


def test_review_key_text_meets_wcag_aa_in_both_schemes():
    for name, t in _schemes().items():
        ratio = _contrast(t["text"], t["accent-soft"])
        assert ratio >= 4.5, f"{name}: text on proposed answer {ratio:.2f}:1"


def test_review_key_border_is_distinguishable_in_both_schemes():
    for name, t in _schemes().items():
        assert _contrast(t["accent"], t["surface"]) >= 3, f"{name}: accent border too faint"
