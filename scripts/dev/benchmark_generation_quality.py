"""T065: before/after generation-quality benchmark on a fixed sample of cells (live, free models only).

Each cell runs the real pipeline (generate_one: deterministic checks, independent solve, rubric) once per arm:
  legacy  - the generation prompt of a Git revision (default origin/main, prompt 1.3.0)
  current - the working tree's prompt
Validation is the working tree's in both arms; the rubric prompt is identical in both, so only the generator
instructions differ. Usage goes to an in-memory store (no database writes). Paid generation is forced off
and the run stops at --max-calls sent calls.

Usage:
    .venv/Scripts/python.exe scripts/dev/benchmark_generation_quality.py --out bench.json [--max-calls 100]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# The cells production rejected on 2026-11-11 (hard requests answered with one-step items, grounding).
CELLS = [
    ("matematicas", "M03", "hard"), ("matematicas", "M02", "hard"), ("espanol", "EL01", "hard"),
    ("ciencias", "C01", "hard"), ("estudios_sociales", "ES01", "hard"), ("estudios_sociales", "ES01", "easy"),
]
PRODUCTION_GENERATION_MODELS = "nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-26b-a4b-it:free"


def legacy_prompts(revision: str):
    source = subprocess.run(["git", "show", f"{revision}:app/generation/prompts.py"], cwd=ROOT, check=True,
                            capture_output=True, text=True, encoding="utf-8").stdout
    path = Path(tempfile.mkdtemp()) / "legacy_prompts.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("legacy_prompts", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(reason: str) -> str:
    if "difficulty_match" in reason:
        return "difficulty"
    if reason.startswith(("F01", "F02", "R03")):
        return "grounding"
    if "budget" in reason:
        return "call_limit"
    if "solve" in reason:
        return "independent_solve"
    if "invalid output" in reason or "truncat" in reason:
        return "output"
    return "other: " + reason.split(":")[0][:40]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--legacy-revision", default="origin/main")
    parser.add_argument("--max-calls", type=int, default=100)
    parser.add_argument("--arms", default="legacy,current")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    os.environ.update({"OPENROUTER_ALLOW_PAID": "false",
                       "OPENROUTER_QUESTION_GENERATION_MODELS": PRODUCTION_GENERATION_MODELS})

    import psycopg

    from curriculum import db
    from curriculum.catalog import open_catalog
    from app.generation import pipeline, prompts
    from app.generation.grounding import build_grounding
    from app.llm.client import OpenRouterClient
    from app.llm.settings import LlmSettings
    from app.llm.usage import MemoryUsageStore
    from app.main import BASELINE_VERSION

    settings = LlmSettings.load()
    assert not settings.allow_paid
    client = OpenRouterClient(settings)
    current_messages = prompts.generation_messages
    arms = {"legacy": legacy_prompts(args.legacy_revision).generation_messages, "current": current_messages}
    conn: psycopg.Connection = open_catalog(db.database_url(), db.DEFAULT_SCHEMA)
    results, sent = [], 0
    try:
        for subject, code, difficulty in CELLS:
            bundle = build_grounding(conn, BASELINE_VERSION, subject, code, None)
            for arm in args.arms.split(","):
                if sent >= args.max_calls:
                    print(f"stop: {sent} calls sent (limit {args.max_calls})")
                    break
                prompts.generation_messages = arms[arm]
                try:
                    outcome = pipeline.generate_one(client, MemoryUsageStore(), bundle, difficulty)
                finally:
                    prompts.generation_messages = current_messages
                summary = outcome.summary()
                sent += summary["calls"]
                attempts = (outcome.validation or {}).get("attempts", [])
                row = {"arm": arm, "subject": subject, "objective": code, "difficulty": difficulty,
                       "status": outcome.status, "calls": summary["calls"], "attempts": attempts,
                       "rubric": (outcome.validation or {}).get("rubric"), "reasons": outcome.reasons,
                       "stem": (outcome.item or {}).get("stem")}
                results.append(row)
                print(f"{arm:7} {code} {difficulty:6} -> {outcome.status:11} calls={summary['calls']} "
                      f"attempts={[a['verdict'] for a in attempts]} {outcome.reasons[:2]}")
    finally:
        conn.close()
    report = {"cells": CELLS, "arms": {}}
    for arm in args.arms.split(","):
        rows = [r for r in results if r["arm"] == arm]
        attempts = [a for r in rows for a in r["attempts"]]
        lost = Counter(classify(reason) for a in attempts if a["verdict"] != "accept" for reason in a["reasons"][:1])
        calls = sum(r["calls"] for r in rows)
        accepted = sum(r["status"] == "accepted" for r in rows)
        difficulty_judged = [a for a in attempts if a["verdict"] == "accept" or any(
            "difficulty_match" in x or "rubric" in x for x in a["reasons"])]
        difficulty_failed = sum(any("difficulty_match" in x for x in a["reasons"]) for a in attempts)
        report["arms"][arm] = {
            "cells": len(rows), "accepted": accepted, "calls": calls, "item_attempts": len(attempts),
            "accepted_per_call": round(accepted / calls, 3) if calls else None,
            "calls_per_accepted": round(calls / accepted, 1) if accepted else None,
            "difficulty_pass": f"{len(difficulty_judged) - difficulty_failed}/{len(difficulty_judged)}",
            "grounding_failures": lost.get("grounding", 0), "lost_attempts_by_cause": dict(lost)}
    print(json.dumps(report["arms"], indent=1))
    args.out.write_text(json.dumps({**report, "results": results}, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
