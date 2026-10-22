"""Parsing of untrusted model output (never executed, never trusted for metadata)."""

from __future__ import annotations

import json
import re
from typing import Any

RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
RE_LETTER = re.compile(r"\b([ABCD])\b")
RUBRIC_KEYS = ("alignment", "clarity", "distractor_quality", "language", "difficulty_match")
# Keys the model may author inside subject_checks; anything else is dropped.
SUBJECT_CHECK_KEYS = {
    "math": ("expression", "select", "unit"),
    "reading": ("quoted_spans", "key_support_span"),
    "facts": ("support_terms",),
}
MODEL_FIELDS = ("stimulus", "stem", "options", "answer_key", "explanation", "distractor_rationales",
                "cognitive_verb", "subject_checks")


class OutputError(ValueError):
    """Model output could not be parsed into the expected shape."""


def extract_json(text: str, required: tuple[str, ...] = ()) -> dict[str, Any]:
    """A JSON object from the text, tolerating code fences and surrounding prose or reasoning.

    Without `required`, the first decodable object is returned. With `required`,
    the last decodable object containing all those keys is returned (reasoning
    text before the answer may contain other braces).
    """
    cleaned = RE_FENCE.sub("", (text or "").strip())
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    position = cleaned.find("{")
    while position != -1:
        try:
            value, _ = decoder.raw_decode(cleaned[position:])
            if isinstance(value, dict):
                if not required:
                    return value
                found.append(value)
        except json.JSONDecodeError:
            pass
        position = cleaned.find("{", position + 1)
    matching = [v for v in found if all(k in v for k in required)]
    if matching:
        return matching[-1]
    raise OutputError("no valid JSON object in model output")


def model_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields the model is allowed to author; metadata is set by code."""
    missing = [f for f in MODEL_FIELDS if f not in raw]
    if missing:
        raise OutputError(f"model output missing fields: {missing}")
    fields = {f: raw[f] for f in MODEL_FIELDS}
    stimulus = fields["stimulus"] if isinstance(fields["stimulus"], dict) else {}
    stype = stimulus.get("type") if stimulus.get("type") in ("none", "text", "table") else "none"
    fields["stimulus"] = {"type": stype}
    if stype != "none":
        fields["stimulus"]["text"] = str(stimulus.get("text", ""))
    checks = fields["subject_checks"] if isinstance(fields["subject_checks"], dict) else {}
    fields["subject_checks"] = {
        block: {k: v for k, v in checks[block].items() if k in keys}
        for block, keys in SUBJECT_CHECK_KEYS.items() if isinstance(checks.get(block), dict)
    }
    if isinstance(fields["answer_key"], str):
        fields["answer_key"] = fields["answer_key"].strip().upper()[:1]
    return fields


def parse_solve(text: str) -> str | None:
    """Letter chosen by the blind solver; None for AMBIGUA or unparseable output."""
    lines = [line.strip() for line in (text or "").strip().upper().splitlines() if line.strip()]
    if not lines:
        return None
    final = lines[-1]  # reasoning, if leaked into content, comes before the answer
    if "AMBIGU" in final:
        return None
    letters = set(RE_LETTER.findall(final))
    return letters.pop() if len(letters) == 1 else None


def parse_rubric(text: str) -> dict[str, int]:
    raw = extract_json(text, required=RUBRIC_KEYS)
    scores = {}
    for key in RUBRIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2):
            raise OutputError(f"rubric {key} must be 0, 1 or 2")
        scores[key] = value
    return scores
