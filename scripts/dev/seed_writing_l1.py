"""Seed the Nivel 1 Producción escrita inventory (T023): generate only missing categories.

Uses the real catalog and writing store (DATABASE_URL) and OpenRouter with the configured free models,
budgets and usage records. Existing exercises, drafts and submissions are never changed. Writes the
report to --out and prints a summary; never prints the key. Exit code 0 only when no gap remains.

Usage:
    .venv/Scripts/python.exe scripts/dev/seed_writing_l1.py --out l1-seed.json
    .venv/Scripts/python.exe scripts/dev/seed_writing_l1.py --inventory      # read-only inventory
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.llm.client import OpenRouterClient  # noqa: E402
from app.llm.settings import LlmSettings  # noqa: E402
from app.llm.usage import UsageStore  # noqa: E402
from app.writing import seeding  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402
from curriculum.catalog import open_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    parser.add_argument("--inventory", action="store_true", help="only print the stored L1 inventory")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    store = WritingStore(url)
    if args.inventory:
        print(json.dumps(seeding.inventory(store), indent=1))
        return 0
    if args.out is None:
        parser.error("--out is required unless --inventory is given")
    with OpenRouterClient(LlmSettings.load()) as client, open_catalog(url) as catalog:
        report = seeding.seed(client, UsageStore(url), catalog, store, args.difficulty)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    t = report["totals"]
    print(f"L1_SEED gap={report['gap']} attempts={t['attempts']} accepted={t['accepted']} rejected={t['rejected']} "
          f"calls={t['calls']} tokens={t['tokens_in']}/{t['tokens_out']} cost=${t['cost_usd']} "
          f"complete={t['cost_complete']}")
    for r in report["results"]:
        print(f"  {r['category']}: {r['status']} {r.get('exercise_id') or ''} {r.get('stop_reason') or ''}")
        for a in r["attempts"]:
            print(f"    {a['request_id']} {a['status']} models={a['models_used']} "
                  f"reasons={'; '.join(a['reasons'])[:300]}")
    return 0 if not report["gap"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
