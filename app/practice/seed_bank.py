"""Question bank seeding and educational review (T047, ADR-034).

    python -m app.practice.seed_bank run --subject matematicas [--target 100] [--max-calls 20]
    python -m app.practice.seed_bank report --subject matematicas [--cells]
    python -m app.practice.seed_bank review-sample --subject matematicas --out FILE
    python -m app.practice.seed_bank review-record --subject matematicas --decisions FILE [--reviewer tutor]
    python -m app.practice.seed_bank quarantine --request-id REQ --reason wrong_key [--reviewer tutor]

Reads DATABASE_URL and CURRICULUM_BASELINE like the application; `run` uses the OpenRouter settings and the
shared daily budget. Standard output is counts and identifiers only; question text goes only to the review file.
Exit codes: 0 done, 1 refused or failed, 3 another run holds the subject (SEED BUSY), 4 lock lost.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SUBJECTS = ("espanol", "matematicas", "ciencias", "estudios_sociales")


def _llm_factory(url: str):
    def factory():
        from app.generation.store import GenerationStore
        from app.llm.client import OpenRouterClient
        from app.llm.settings import LlmSettings
        from app.llm.usage import UsageStore

        return OpenRouterClient(LlmSettings.load()), UsageStore(url), GenerationStore(url)
    return factory


def _batch_id(url: str, baseline: str, subject: str) -> str:
    from app.practice import seeding

    batch = seeding.current_batch(url, baseline, subject)
    if batch is None:
        raise seeding.SeedError(f"no current batch for {subject}; run `seed_bank run` first")
    return batch["batch_id"]


def main(argv: list[str] | None = None) -> int:
    from app.practice import seeding
    from curriculum import catalog, db, importer

    parser = argparse.ArgumentParser(prog="python -m app.practice.seed_bank")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--target", type=int, default=seeding.DEFAULT_TARGET)
    run.add_argument("--max-calls", type=int, default=20)
    rep = sub.add_parser("report")
    rep.add_argument("--cells", action="store_true", help="include the per-cell rows")
    sample = sub.add_parser("review-sample")
    sample.add_argument("--out", type=Path, required=True)
    record = sub.add_parser("review-record")
    record.add_argument("--decisions", type=Path, required=True)
    for p in (run, rep, sample, record):
        p.add_argument("--subject", choices=SUBJECTS, required=True)
    for p in (record, quar := sub.add_parser("quarantine")):
        p.add_argument("--reviewer", default="tutor")
    quar.add_argument("--request-id", required=True)
    quar.add_argument("--reason", choices=seeding.REASONS, required=True)
    args = parser.parse_args(argv)

    url = db.database_url()
    baseline = os.environ.get("CURRICULUM_BASELINE", importer.DEFAULT_VERSION)
    conn = catalog.open_catalog(url)
    try:
        if args.command == "run":
            out = seeding.run(url, conn, baseline, args.subject, _llm_factory(url), args.target, args.max_calls)
            out["coverage"].pop("cells")
        elif args.command == "report":
            out = seeding.report(url, conn, _batch_id(url, baseline, args.subject))
            if not args.cells:
                out["coverage"].pop("cells")
        elif args.command == "review-sample":
            batch_id = _batch_id(url, baseline, args.subject)
            rows = seeding.review_sample(url, batch_id)
            args.out.write_text(json.dumps(seeding.review_export(url, conn, batch_id), ensure_ascii=False,
                                           indent=1), encoding="utf-8")
            out = {"batch_id": batch_id, "round": rows[0]["round"], "sampled": len(rows), "file": str(args.out)}
        elif args.command == "review-record":
            decisions = json.loads(args.decisions.read_text(encoding="utf-8"))
            decisions = decisions.get("questions", decisions) if isinstance(decisions, dict) else decisions
            out = seeding.review_record(url, _batch_id(url, baseline, args.subject),
                                        [{k: d.get(k, "") for k in ("request_id", "verdict", "reason")}
                                         for d in decisions], args.reviewer)
        else:
            out = seeding.quarantine(url, args.request_id, args.reason, args.reviewer)
    except seeding.SeedBusy as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except seeding.LockLost as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except seeding.SeedError as exc:
        print(f"REFUSED (nothing changed): {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
