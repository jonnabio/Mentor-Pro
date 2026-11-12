"""T065: replay the grounding checks (F01/F02) on recorded generation attempts. No LLM call, no database.

Input: a JSON export {"attempts": [...], "concepts": {code: concepts_es}} of generation.question_attempt rows
(item, objective_code, status, reasons) and the curricular concepts. The facts given to the checker are the
objective's concept lines, as in production (GroundingBundle.concept_lines); the records are the item's own
source_refs excerpts (the evidence text).

Usage:
    .venv/Scripts/python.exe scripts/dev/replay_grounding.py --export attempts.json [--show]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.generation.validation import item_checker  # noqa: E402


def concept_lines(concepts: str) -> list[str]:
    return [line.strip().lstrip("•").strip() for line in concepts.splitlines() if line.strip()]


def replay(export: dict) -> list[dict]:
    rows = []
    for a in export["attempts"]:
        item = a.get("item") or {}
        if not item.get("subject_checks", {}).get("facts"):
            continue
        records = {s["record_id"]: {"text_es": s.get("excerpt", "")} for s in item.get("source_refs", [])}
        facts = concept_lines(export["concepts"].get(a["objective_code"], ""))
        checks = item_checker.check_facts(item, records, facts)
        failed = [c["id"] for c in checks if c["status"] == "fail"]
        rows.append({"request_id": a["request_id"], "objective": a["objective_code"], "status": a["status"],
                     "failed": failed, "detail": [c["message"] for c in checks if c["status"] == "fail"]})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", type=Path, required=True)
    parser.add_argument("--show", action="store_true", help="print every failing attempt")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rows = replay(json.loads(args.export.read_text(encoding="utf-8")))
    passed = sum(1 for r in rows if not r["failed"])
    print(f"checker {item_checker.CHECKER_VERSION}: {len(rows)} fact items, grounding pass {passed}/{len(rows)}")
    print("failures by check:", dict(Counter(f for r in rows for f in r["failed"])))
    if args.show:
        for r in rows:
            if r["failed"]:
                print(f"  {r['request_id']} {r['objective']} ({r['status']}): {'; '.join(r['detail'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
