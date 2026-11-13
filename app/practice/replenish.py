"""Question bank inventory and replenishment (T061, T062; ADR-036).

    python -m app.practice.replenish inventory [--subject S]          # counts per objective and difficulty
    python -m app.practice.replenish assess [--subject S]             # snapshot + open/close requests, no LLM
    python -m app.practice.replenish run --subject S --max-calls N    # generate candidates for open requests
    python -m app.practice.replenish requests [--subject S] [--all]
    python -m app.practice.replenish tick                              # one scheduled pass (T066, host timer)
    python -m app.practice.replenish schedule-status
    python -m app.practice.replenish pause --reason TEXT | resume

Reads DATABASE_URL, CURRICULUM_BASELINE and the MENTOR_PRO_REPLENISH_* policy settings. `run` uses the
OpenRouter settings, free models only, and the shared daily budget. Output is counts and identifiers only, never
question text. Candidates are held from practices until a human tutor approves them
(`seed_bank item-review-sample` / `item-review-record`); this tool never records a verdict.
Exit codes: 0 done (a skipped tick included), 1 refused, 3 another seeding run holds the subject, 4 lock lost,
5 a tick failed (recorded in generation.replenish_tick).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.practice.seed_bank import SUBJECTS, _llm_factory


def main(argv: list[str] | None = None) -> int:
    from app.practice import replenish_schedule, replenishment, seeding
    from curriculum import catalog, db, importer

    parser = argparse.ArgumentParser(prog="python -m app.practice.replenish")
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    assess = sub.add_parser("assess")
    run = sub.add_parser("run")
    reqs = sub.add_parser("requests")
    reqs.add_argument("--all", action="store_true", help="include closed requests")
    for p in (inv, assess, reqs):
        p.add_argument("--subject", choices=SUBJECTS)
    run.add_argument("--subject", choices=SUBJECTS, required=True)
    run.add_argument("--max-calls", type=int, required=True)
    inv.add_argument("--cells", action="store_true", help="include the per-cell rows")
    sub.add_parser("tick", help="one bounded scheduled replenishment pass (T066)")
    sub.add_parser("schedule-status")
    pause = sub.add_parser("pause")
    pause.add_argument("--reason", required=True)
    sub.add_parser("resume")
    args = parser.parse_args(argv)

    url = db.database_url()
    baseline = os.environ.get("CURRICULUM_BASELINE", importer.DEFAULT_VERSION)
    subjects = [args.subject] if getattr(args, "subject", None) else list(SUBJECTS)
    try:
        policy = replenishment.Policy.from_env()
        schedule = replenish_schedule.ScheduleSettings.from_env()
    except (replenishment.PolicyError, replenish_schedule.ScheduleError) as exc:
        print(f"REFUSED (nothing changed): {exc}", file=sys.stderr)
        return 1
    if args.command in ("schedule-status", "pause", "resume"):
        out = (replenish_schedule.status(url, schedule) if args.command == "schedule-status"
               else replenish_schedule.set_paused(url, args.command == "pause", getattr(args, "reason", None)))
        print(json.dumps(out, indent=1, default=str))
        return 0
    conn = catalog.open_catalog(url)
    try:
        if args.command == "tick":
            out = replenish_schedule.tick(url, conn, baseline, _llm_factory(url), policy, schedule, SUBJECTS)
            print(f"TICK {out['status'].upper()} {out['tick_id']} reason={out['reason']} calls={out['calls']} "
                  f"generated={out['generated']}" + (f" error={out['error']}" if out["error"] else ""))
            print(json.dumps(out, indent=1, default=str))
            return 5 if out["status"] == "failed" else 0
        if args.command == "inventory":
            out = {}
            for subject in subjects:
                rows = replenishment.inventory(url, conn, baseline, subject)
                out[subject] = {"totals": replenishment.totals(rows), **({"cells": rows} if args.cells else {})}
        elif args.command == "assess":
            out = {s: replenishment.assess(url, conn, baseline, s, policy) for s in subjects}
        elif args.command == "run":
            out = replenishment.run(url, conn, baseline, args.subject, _llm_factory(url), policy, args.max_calls)
        else:
            replenishment.ensure_schema(url)
            out = {s: replenishment.requests(url, baseline, s, pending_only=not args.all) for s in subjects}
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
    print(json.dumps({"policy": policy.__dict__, **out} if args.command != "run" else out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
