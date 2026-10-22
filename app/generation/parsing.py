"""Parsing of untrusted model output (never executed, never trusted for metadata)."""

from __future__ import annotations

import json
import re
from typing import Any

RE_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
RE_LETTER = re.compile(r"\b([ABCD])\b")
RUBRIC_KEYS = ("alignment", "clarity", "distractor_quality", "language", "difficulty_match")
MODEL_FIELDS = ("stimulus", "stem", "options", "answer_key", "explanation", "distractor_rationales",
                "cognitive_verb", "subject_checks")


class OutputError(ValueError):
    """Model output could not be parsed into the expected shape."""


def extract_json(text: str) -> dict[str, Any]:
    """First JSON object in the text (tolerates code fences and surrounding prose)."""
    cleaned = RE_FENCE.sub("", (text or "").strip())
    start = cleaned.find("{")
    if start == -1:
        raise OutputError("no JSON object in model output")
    decoder = json.JSONDecoder()
    try:
        value, _ = decoder.raw_decode(cleaned[start:])
    except json.JSONDecodeError as exc:
        raise OutputError(f"invalid JSON: {exc.msg}") from None
    if not isinstance(value, dict):
        raise OutputError("model output is not a JSON object")
    return value


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
    if isinstance(fields["answer_key"], str):
        fields["answer_key"] = fields["answer_key"].strip().upper()[:1]
    return fields


def parse_solve(text: str) -> str | None:
    """Letter chosen by the blind solver; None for AMBIGUA or unparseable output."""
    upper = (text or "").strip().upper()
    if "AMBIGU" in upper:
        return None
    letters = set(RE_LETTER.findall(upper))
    return letters.pop() if len(letters) == 1 else None


def parse_rubric(text: str) -> dict[str, int]:
    raw = extract_json(text)
    scores = {}
    for key in RUBRIC_KEYS:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value not in (0, 1, 2):
            raise OutputError(f"rubric {key} must be 0, 1 or 2")
        scores[key] = value
    return scores
