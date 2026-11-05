"""Explicit migrations of the `llm` schema (T055). See app/llm/migrations.py.

    python -m app.llm.migrate status
    python -m app.llm.migrate apply [--dry-run]
    python -m app.llm.migrate rollback

Reads DATABASE_URL like the application. Output is counts and digests only.
"""

from __future__ import annotations

import argparse
import json
import sys

from app.llm import migrations


def main(argv: list[str] | None = None) -> int:
    from curriculum import db

    parser = argparse.ArgumentParser(prog="python -m app.llm.migrate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("apply").add_argument("--dry-run", action="store_true")
    sub.add_parser("rollback")
    args = parser.parse_args(argv)
    url = db.database_url()
    try:
        if args.command == "status":
            with migrations._connect(url) as conn:
                report = migrations.state(conn)
        elif args.command == "apply":
            report = migrations.apply(url, dry_run=args.dry_run)
        else:
            report = migrations.rollback(url)
    except migrations.MigrationError as exc:
        print(f"REFUSED (nothing changed): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
