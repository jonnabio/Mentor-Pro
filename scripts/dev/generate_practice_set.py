"""Live T007 check: one validated practice set via the dev endpoint.

Uses the real catalog (DATABASE_URL) and OpenRouter (OPENROUTER_API_KEY from .env).
Writes the full response to --out and prints a summary. Never prints the key.

Usage:
    .venv/Scripts/python.exe scripts/dev/generate_practice_set.py --out set.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.main import create_app  # noqa: E402

REQUEST = {"subject": "matematicas", "scope": "selected_objectives", "objective_codes": ["M02", "M04", "M05"],
           "difficulty": "medium", "question_count": 5}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--objectives", help="comma-separated objective codes (default M02,M04,M05)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    request = dict(REQUEST)
    if args.objectives:
        request["objective_codes"] = args.objectives.split(",")
    response = TestClient(create_app(dev_endpoints=True)).post("/api/dev/practice-sets/generate", json=request)
    data = response.json()
    args.out.write_text(json.dumps({"http_status": response.status_code, **data}, ensure_ascii=False, indent=2)
                        + "\n", encoding="utf-8")
    if response.status_code != 200:
        print(response.status_code, data)
        return 1
    s = data["summary"]
    print(f"{data['practice_set_id']} -> {data['status']} (stop: {data['stop_reason']}) | "
          f"accepted {s['accepted']}/{s['requested']} | generation attempts {s['generation_attempts']} "
          f"(rejected {s['rejected_attempts']}) | requests {s['requests']} | calls {s['calls']} | "
          f"tokens {s['tokens_in']}/{s['tokens_out']} | cost ${s['cost_usd']} complete={s['cost_complete']} | "
          f"{s['duration_ms'] / 1000:.0f} s | models {s['models_used']}")
    for slot in data["slots"]:
        print(f"  slot {slot['slot']} {slot['objective_code']} {slot['evidence_id'][-6:]} [{slot['difficulty']}] "
              f"-> {slot['status']} after {len(slot['requests'])} request(s)")
    for row in data["rejections"]:
        print(f"    rejected slot {row['slot']} {row['request_id']} #{row['attempt']} {row['verdict']}: "
              f"{'; '.join(row['reasons'])[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
