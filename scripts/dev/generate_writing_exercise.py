"""Live T021 check: generate one Producción escrita exercise with OpenRouter (ADR-020).

Uses the real catalog and writing store (DATABASE_URL) and OpenRouter (OPENROUTER_API_KEY from .env),
with the configured free models, budgets and usage records. Writes the outcome to --out and prints a
summary. Never prints the key.

Usage:
    .venv/Scripts/python.exe scripts/dev/generate_writing_exercise.py --level L2 --difficulty medium \\
        --criteria EE03,EE04 --out exercise.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.llm.client import OpenRouterClient  # noqa: E402
from app.llm.settings import LlmSettings  # noqa: E402
from app.llm.usage import UsageStore  # noqa: E402
from app.writing import generation  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402
from curriculum.catalog import open_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", required=True, help="L1-L5")
    parser.add_argument("--difficulty", default="medium", choices=sorted(generation.DIFFICULTY_ES))
    parser.add_argument("--criteria", required=True, help="comma-separated EE codes, e.g. EE03,EE04")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    started = time.monotonic()
    with OpenRouterClient(LlmSettings.load()) as client, open_catalog(url) as catalog:
        outcome = generation.generate_exercise(client, UsageStore(url), catalog, WritingStore(url), args.level,
                                               args.difficulty, args.criteria.split(","))
    attempts = []
    for a in outcome.attempts:
        attempts.append({"request_id": a.request_id, "status": a.status, "checks": a.checks, "review": a.review,
                         "reasons": a.reasons, "summary": a.summary(),
                         "usage": [{k: u[k] for k in ("purpose", "attempt", "model_used", "status", "tokens_in",
                                                       "tokens_out", "cost_usd", "cost_source", "latency_ms")}
                                   for u in a.usage]})
    report = {"status": outcome.status, "stop_reason": outcome.stop_reason, "exercise": outcome.exercise,
              "attempts": attempts, "duration_s": round(time.monotonic() - started, 1)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    calls = sum(a["summary"]["calls"] for a in attempts)
    tokens = (sum(a["summary"]["tokens_in"] for a in attempts), sum(a["summary"]["tokens_out"] for a in attempts))
    cost = round(sum(a["summary"]["cost_usd"] for a in attempts), 8)
    print(f"WRITING={outcome.status} stop={outcome.stop_reason} attempts={len(attempts)} calls={calls} "
          f"tokens={tokens[0]}/{tokens[1]} cost=${cost} "
          f"complete={all(a['summary']['cost_complete'] for a in attempts)} {report['duration_s']} s")
    for a in attempts:
        print(f"  {a['request_id']} {a['status']} models={a['summary']['models_used']} "
              f"reasons={'; '.join(a['reasons'])[:300]}")
    if outcome.exercise:
        print(f"  exercise {outcome.exercise['exercise_id']}: {outcome.exercise['topic_es']}")
    return 0 if outcome.status == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
