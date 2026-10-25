"""Apply editorial revisions to stored writing exercises (ADR-023). Repeatable; never overwrites.

Default spec: the T024 Nivel 1 revisions; --specs names another file (for example the T025 L2 revision).

Each revision is validated (W02-W07, W09-W15) before it is appended to writing.exercise_revision; the
original record, the original tutor-only reference, generation histories, drafts and submissions are kept.
--dry-run validates and prints without writing.

Usage:
    .venv/Scripts/python.exe scripts/dev/revise_writing_l1.py --dry-run
    .venv/Scripts/python.exe scripts/dev/revise_writing_l1.py
    .venv/Scripts/python.exe scripts/dev/revise_writing_l1.py --specs scripts/dev/fixtures/writing-revisions-T025.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.writing import revisions  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402
from curriculum.catalog import open_catalog  # noqa: E402

SPECS = ROOT / "scripts" / "dev" / "fixtures" / "writing-revisions-T024.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--specs", type=Path, default=SPECS)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    store = WritingStore(url)
    specs = json.loads(args.specs.read_text(encoding="utf-8"))
    with open_catalog(url) as catalog:
        if args.dry_run:
            for spec in specs:
                if any(r["reason"] == spec["reason"] for r in store.revisions(spec["exercise_id"])):
                    print(spec["exercise_id"], "present")
                    continue
                current = store.record(spec["exercise_id"])
                ref = store.reference_correction(spec["exercise_id"])
                ref = {k: ref[k] for k in ("corrected_text_es", "corrections", "ambiguities_es")} if ref else None
                record, reference = revisions.revise(spec, current, ref)
                checks = revisions.checks_for(catalog, store, record, reference, "PNE2026-SUM-v1.0")
                failed = [f"{c['id']}: {c['message']}" for c in checks if c["status"] == "fail"]
                print(spec["exercise_id"], "valid" if not failed else failed)
            return 0
        results = revisions.apply_revisions(store, catalog, specs)
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0 if all(r["status"] in ("revised", "present") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
