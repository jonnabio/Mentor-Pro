"""Explicit migrations of the writing schema (T036, ADR-032).

    python -m app.writing.migrate status
    python -m app.writing.migrate apply [--dry-run]
    python -m app.writing.migrate repair
    python -m app.writing.migrate rollback

Reads DATABASE_URL like the application. Output is counts and digests only, never student text.
"""

from __future__ import annotations

import argparse
import json
import sys

import psycopg

from app.writing import migrations


def main(argv: list[str] | None = None) -> int:
    from curriculum import db

    parser = argparse.ArgumentParser(prog="python -m app.writing.migrate")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    apply = sub.add_parser("apply")
    apply.add_argument("--dry-run", action="store_true")
    sub.add_parser("repair")
    sub.add_parser("rollback")
    args = parser.parse_args(argv)
    url = db.database_url()
    try:
        if args.command == "status":
            with psycopg.connect(url) as conn:
                report = {"state": migrations.state(conn)}
        elif args.command == "apply":
            report = migrations.apply(url, dry_run=args.dry_run)
        elif args.command == "repair":
            report = migrations.repair(url)
        else:
            report = migrations.rollback(url)
    except migrations.MigrationError as exc:
        print(f"MIGRATION FAILED (nothing changed): {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
