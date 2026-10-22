"""Live T006 check: one question each for M02, EL01, C01, ES01 via the dev endpoint.

Uses the real catalog (DATABASE_URL) and OpenRouter (OPENROUTER_API_KEY from .env).
Writes the full responses to --out and prints a summary. Never prints the key.

Usage:
    .venv/Scripts/python.exe scripts/dev/generate_examples.py --out examples.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.main import create_app  # noqa: E402

CASES = [
    ("matematicas", "M02", "medium", 3),   # E3 Compara decimales
    ("espanol", "EL01", "medium", 8),       # E8 Elige la idea fundamental respaldada por el texto
    ("ciencias", "C01", "easy", 1),         # E1 partes de la célula
    ("estudios_sociales", "ES01", "medium", 2),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", help="objective code to run alone, e.g. M02")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    client = TestClient(create_app(dev_endpoints=True))
    results = []
    for subject, code, difficulty, ordinal in CASES:
        if args.only and code != args.only:
            continue
        response = client.post("/api/dev/questions/generate", json={
            "subject": subject, "objective_code": code, "difficulty": difficulty, "evidence_ordinal": ordinal})
        data = response.json()
        results.append({"http_status": response.status_code, **data})
        usage = data.get("usage", {})
        print(f"{code} E{ordinal} [{difficulty}] -> {data.get('status', response.status_code)} "
              f"| verdict={(data.get('validation') or {}).get('verdict')} | models={usage.get('models_used')} "
              f"| calls={usage.get('calls')} tokens={usage.get('tokens_in')}/{usage.get('tokens_out')} "
              f"| cost=${usage.get('cost_usd')} complete={usage.get('cost_complete')} "
              f"| latency={usage.get('latency_ms')} ms")
        for reason in data.get("reasons", [])[:4]:
            print(f"    reason: {reason}")
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
