"""RCA-004 remediation of the writing exercise bank (T029, ADR-027).

Steps, each repeatable: identify accepted exercises whose review came from their generator, quarantine
them, revalidate each with an independent reviewer (generator excluded), and generate Nivel 1 replacements
only when the eligible L1 inventory is below its minimum. Uses DATABASE_URL and the configured OpenRouter
models, budgets and usage records; never prints the key; never touches drafts or submissions.

Usage:
    .venv/Scripts/python.exe scripts/dev/remediate_writing_review.py --dry-run          # identify + inventory
    .venv/Scripts/python.exe scripts/dev/remediate_writing_review.py --out report.json  # full remediation
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
from app.writing import revalidation, seeding  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402
from curriculum.catalog import open_catalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="identify and print the inventory; change nothing")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    store = WritingStore(url)
    affected = revalidation.self_reviewed(url)
    print("AFFECTED", [(a["exercise_id"], a["generator_model"], a["reviewer_model"]) for a in affected])
    if args.dry_run:
        print("INVENTORY", json.dumps(revalidation.inventory(store)))
        return 0
    if args.out is None:
        parser.error("--out is required unless --dry-run is given")
    report: dict = {"affected": affected, "quarantine": revalidation.quarantine(store, affected),
                    "validations": [], "replacement": None}
    passed = {v["exercise_id"] for v in store.validations() if v["status"] == "passed"}
    with OpenRouterClient(LlmSettings.load()) as client, open_catalog(url) as catalog:
        usage = UsageStore(url)
        for row in affected:
            if row["exercise_id"] in passed:
                continue
            result = revalidation.revalidate(client, usage, catalog, store, row["exercise_id"], row["generator_model"])
            report["validations"].append(result)
            print(f"  {row['exercise_id']}: {result['status']} reviewer={result['reviewer_model']} "
                  f"called={result['models_called']} calls={result['calls']} "
                  f"tokens={result['tokens_in']}/{result['tokens_out']} cost=${result['cost_usd']} "
                  f"reasons={'; '.join(result['reasons'])[:300]}")
        if revalidation.inventory(store)["gap"].get("writing_conventions"):
            report["replacement"] = seeding.seed(client, usage, catalog, store)
            t = report["replacement"]["totals"]
            print(f"  L1 replacement: gap={report['replacement']['gap']} attempts={t['attempts']} calls={t['calls']} "
                  f"tokens={t['tokens_in']}/{t['tokens_out']} cost=${t['cost_usd']}")
    report["inventory"] = revalidation.inventory(store)
    report["eligibility"] = {a["exercise_id"]: store.eligibility(a["exercise_id"]) for a in affected}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print("ELIGIBILITY", report["eligibility"])
    print("INVENTORY", json.dumps(report["inventory"]))
    return 0 if not report["inventory"]["gap"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
