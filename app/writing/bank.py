"""Controlled transfer of the approved writing exercise bank between databases (T032, ADR-031).

Export reads the eligible exercises of one database with everything that makes them approved: the record
and its editorial revisions, the tutor-only reference corrections, the accepted generation attempt, the
eligibility history, the independent validations and the LLM usage rows that name the generating and
reviewing models (RCA-004 evidence). Quarantined exercises are never exported. Drafts, submissions and
evaluations are never read.

Import checks every exercise against the destination (curriculum baseline present, same rubric file,
valid contracts, independent review evidence, L1 reference present) and inserts the accepted ones in one
transaction. Existing exercises are never changed: an identical one is reported unchanged, a different one
is rejected. --dry-run performs the same inserts and rolls back. Run by an administrator, never at startup.

Usage (inside the image, see docs/runbooks/production-deployment.md):
    python -m app.writing.bank export --out writing-bank.json
    python -m app.writing.bank import writing-bank.json --dry-run --report report.json
    python -m app.writing.bank import writing-bank.json --report report.json
    python -m app.writing.bank inventory
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.llm.router import same_model
from app.writing import contracts
from app.writing.store import WritingStore

BUNDLE_VERSION = "writing-bank-1"
STUDENT_TABLES = ("student_attempt", "draft", "submission", "evaluation", "criterion_score")
JSONB = {
    "writing.exercise": {"record"},
    "writing.generation_attempt": {"checks", "review", "reasons", "exercise", "reference"},
    "writing.reference_correction": {"corrections", "ambiguities_es"},
    "writing.exercise_revision": {"record", "reference", "checks"},
    "writing.independent_validation": {"checks", "review", "reasons"},
    "writing.eligibility_event": set(),
    "llm.usage_record": set(),
}


def _plain(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"not serialisable: {type(value).__name__}")


def _rubric() -> tuple[str, str]:
    rubric = contracts.rubric()
    return rubric["rubric_id"], rubric["source"]["file_sha256"]


# ------------------------------------------------------------------ export

def export_bank(url: str) -> dict[str, Any]:
    store = WritingStore(url)
    exercises, skipped = [], []
    with psycopg.connect(url, row_factory=dict_row) as conn:
        for row in store.exercises(eligible_only=False):
            eid = row["exercise_id"]
            if not row["eligible"]:
                skipped.append({"exercise_id": eid, "reason": "quarantined"})
                continue
            one = lambda q: conn.execute(q, (eid,)).fetchone()  # noqa: E731
            many = lambda q: conn.execute(q, (eid,)).fetchall()  # noqa: E731
            exercise = one("SELECT * FROM writing.exercise WHERE exercise_id = %s")
            validations = many("SELECT * FROM writing.independent_validation WHERE exercise_id = %s "
                               "ORDER BY created_at")
            attempt = conn.execute("SELECT * FROM writing.generation_attempt WHERE request_id = %s",
                                   (exercise["generation_request_id"],)).fetchone()
            request_ids = [r["request_id"] for r in validations] + ([attempt["request_id"]] if attempt else [])
            exercises.append({
                "exercise": exercise,
                "generation_attempt": attempt,
                "reference_correction": one("SELECT * FROM writing.reference_correction WHERE exercise_id = %s"),
                "revisions": many("SELECT * FROM writing.exercise_revision WHERE exercise_id = %s ORDER BY revision"),
                "eligibility_events": [{k: v for k, v in e.items() if k != "event_id"} for e in many(
                    "SELECT * FROM writing.eligibility_event WHERE exercise_id = %s ORDER BY event_id")],
                "independent_validations": validations,
                "usage": conn.execute(
                    "SELECT * FROM llm.usage_record WHERE request_id = ANY(%s) AND status = 'ok' "
                    "AND purpose IN ('generation', 'review') ORDER BY started_at", (request_ids,)).fetchall(),
            })
    rubric_id, rubric_sha = _rubric()
    bundle = {"bundle_version": BUNDLE_VERSION, "exported_at": datetime.now(timezone.utc).isoformat(),
              "rubric_id": rubric_id, "rubric_sha256": rubric_sha, "exercises": exercises, "skipped": skipped}
    return json.loads(json.dumps(bundle, default=_plain))


# ------------------------------------------------------------------ checks

def _models(item: dict[str, Any], request_id: str | None) -> tuple[str | None, str | None]:
    """(generator, reviewer) of a request: the latest ok usage row of each purpose, as revalidation reads them."""
    found: dict[str, str | None] = {"generation": None, "review": None}
    for u in item.get("usage") or []:
        if u["request_id"] == request_id and u["purpose"] in found:
            found[u["purpose"]] = u["model_used"]
    return found["generation"], found["review"]


def check_item(item: dict[str, Any], baselines: set[str]) -> list[str]:
    """Problems that keep one exported exercise out of the destination (empty = acceptable)."""
    problems: list[str] = []
    exercise = item.get("exercise") or {}
    record = exercise.get("record") or {}
    eid = exercise.get("exercise_id")
    rubric_id, rubric_sha = _rubric()
    if not eid or record.get("exercise_id") != eid:
        return ["exercise record missing or for another exercise"]
    records = [record] + [r["record"] for r in item.get("revisions") or []]
    # The current revision must pass today's contracts; earlier ones were superseded by editorial revisions
    # (ADR-023) and are kept unchanged for history.
    problems += [f"revision {len(records)}: {p}" for p in contracts.validate_exercise(records[-1])]
    for n, rec in enumerate(records, 1):
        if rec.get("exercise_id") != eid:
            problems.append(f"revision {n}: record is for another exercise")
        if (rec.get("evaluation") or {}).get("rubric_sha256") != rubric_sha:
            problems.append(f"revision {n}: rubric file differs from the destination's {rubric_id}")
    if exercise.get("rubric_id") != rubric_id or exercise.get("rubric_sha256") != rubric_sha:
        problems.append("exercise rubric differs from the destination rubric")
    if exercise.get("baseline_version") not in baselines:
        problems.append(f"curriculum baseline {exercise.get('baseline_version')} is not in the destination")
    revisions = [r["revision"] for r in item.get("revisions") or []]
    if revisions != list(range(2, len(revisions) + 2)):
        problems.append(f"editorial revisions are not consecutive from 2: {revisions}")
    attempt = item.get("generation_attempt")
    if not attempt or attempt.get("status") != "accepted" or attempt.get("exercise_id") != eid \
            or attempt.get("request_id") != exercise.get("generation_request_id"):
        problems.append("accepted generation attempt missing")
    events = item.get("eligibility_events") or []
    if events and events[-1]["status"] != "eligible":
        problems.append("quarantined in the source")
    validations = {v["validation_id"]: v for v in item.get("independent_validations") or []}
    if any(e.get("validation_id") and e["validation_id"] not in validations for e in events):
        problems.append("eligibility event refers to a validation that is not in the bundle")
    # RCA-004: the accepted review must come from another model, or a passed independent validation must
    # have reinstated the exercise.
    generator, reviewer = _models(item, exercise.get("generation_request_id"))
    reinstated = bool(events) and events[-1]["status"] == "eligible" and \
        (validations.get(events[-1].get("validation_id")) or {}).get("status") == "passed"
    passed = validations.get(events[-1].get("validation_id")) if reinstated else None
    if passed and (not passed.get("reviewer_model") or same_model(passed["reviewer_model"],
                                                                  passed.get("generator_model"))):
        reinstated = False
    if not reinstated and (not generator or not reviewer or same_model(reviewer, generator)):
        problems.append(f"no independent review evidence (generator {generator}, reviewer {reviewer})")
    if record.get("exercise_type") == "conventions_editing" and not item.get("reference_correction"):
        problems.append("tutor reference correction missing for a correction exercise")
    return problems


# ------------------------------------------------------------------ import

def _insert(conn: psycopg.Connection, table: str, row: dict[str, Any], conflict: str = "") -> int:
    schema, name = table.split(".")
    cols = list(row)
    values = [Jsonb(row[c]) if c in JSONB[table] and row[c] is not None else row[c] for c in cols]
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) {}").format(
        sql.Identifier(schema, name), sql.SQL(", ").join(map(sql.Identifier, cols)),
        sql.SQL(", ").join(sql.Placeholder() * len(cols)), sql.SQL(conflict))
    return conn.execute(query, values).rowcount


def _same(conn: psycopg.Connection, item: dict[str, Any]) -> bool:
    """True when the destination already holds this exercise with the same records and revisions."""
    eid = item["exercise"]["exercise_id"]
    row = conn.execute("SELECT record FROM writing.exercise WHERE exercise_id = %s", (eid,)).fetchone()
    revisions = [r["record"] for r in conn.execute(
        "SELECT record FROM writing.exercise_revision WHERE exercise_id = %s ORDER BY revision", (eid,))]
    return row["record"] == item["exercise"]["record"] and revisions == [r["record"] for r in item["revisions"]]


def counts(conn: psycopg.Connection) -> dict[str, int]:
    tables = ("exercise",) + STUDENT_TABLES
    return {t: conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier("writing", t)))
            .fetchone()["n"] for t in tables}


def inventory(url: str) -> dict[str, Any]:
    store = WritingStore(url)
    levels: dict[str, list[str]] = {lv["code"]: [] for lv in contracts.levels()["levels"]}
    quarantined = []
    for row in store.exercises(eligible_only=False):
        (levels[row["level"]] if row["eligible"] else quarantined).append(row["exercise_id"])
    return {"eligible": levels, "eligible_total": sum(map(len, levels.values())), "quarantined": quarantined}


def import_bank(url: str, bundle: dict[str, Any], dry_run: bool = False,
                catalog_schema: str = "curriculum") -> dict[str, Any]:
    if bundle.get("bundle_version") != BUNDLE_VERSION:
        raise ValueError(f"unsupported bundle version {bundle.get('bundle_version')!r}")
    WritingStore(url)  # creates the writing schema when absent
    from app.llm.usage import UsageStore
    UsageStore(url)
    report: dict[str, Any] = {"dry_run": dry_run, "bundle_exported_at": bundle.get("exported_at"),
                              "imported": [], "unchanged": [], "rejected": [],
                              "skipped_in_source": bundle.get("skipped", [])}
    with psycopg.connect(url, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('writing:bank-import'))")
            baselines = {r["baseline_version"] for r in conn.execute(sql.SQL(
                "SELECT DISTINCT baseline_version FROM {}").format(sql.Identifier(catalog_schema, "assertion")))}
            report["counts_before"] = counts(conn)
            for item in bundle["exercises"]:
                eid = (item.get("exercise") or {}).get("exercise_id")
                problems = check_item(item, baselines)
                if problems:
                    report["rejected"].append({"exercise_id": eid, "problems": problems})
                    continue
                if conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s", (eid,)).fetchone():
                    if _same(conn, item):
                        report["unchanged"].append(eid)
                    else:
                        report["rejected"].append({"exercise_id": eid, "problems": [
                            "a different exercise with this id already exists (never overwritten)"]})
                    continue
                _insert(conn, "writing.exercise", item["exercise"])
                _insert(conn, "writing.generation_attempt", item["generation_attempt"],
                        "ON CONFLICT (request_id) DO NOTHING")
                if item.get("reference_correction"):
                    _insert(conn, "writing.reference_correction", item["reference_correction"])
                for revision in item["revisions"]:
                    _insert(conn, "writing.exercise_revision", revision)
                for validation in item["independent_validations"]:
                    _insert(conn, "writing.independent_validation", validation,
                            "ON CONFLICT (validation_id) DO NOTHING")
                for event in item["eligibility_events"]:
                    _insert(conn, "writing.eligibility_event", event)
                for usage in item["usage"]:
                    _insert(conn, "llm.usage_record", usage, "ON CONFLICT (call_id) DO NOTHING")
                report["imported"].append({"exercise_id": eid, "level": item["exercise"]["level"],
                                           "revision": 1 + len(item["revisions"])})
            report["counts_after"] = counts(conn)
            untouched = all(report["counts_before"][t] == report["counts_after"][t] for t in STUDENT_TABLES)
            report["student_records_untouched"] = untouched
            if not untouched:  # cannot happen: nothing above writes student tables
                raise RuntimeError("student records changed during import")
            if dry_run:
                raise _Rollback(report)  # leaves the transaction: everything above is rolled back
    return report


class _Rollback(Exception):
    def __init__(self, report: dict[str, Any]):
        super().__init__("dry run")
        self.report = report


def import_or_dry_run(url: str, bundle: dict[str, Any], dry_run: bool,
                      catalog_schema: str = "curriculum") -> dict[str, Any]:
    try:
        return import_bank(url, bundle, dry_run, catalog_schema)
    except _Rollback as rollback:  # the transaction was rolled back; nothing was written
        return rollback.report


# ------------------------------------------------------------------ command line

def main(argv: list[str] | None = None) -> int:
    from curriculum import db

    parser = argparse.ArgumentParser(prog="python -m app.writing.bank")
    sub = parser.add_subparsers(dest="command", required=True)
    exp = sub.add_parser("export")
    exp.add_argument("--out", type=Path, required=True)
    imp = sub.add_parser("import")
    imp.add_argument("bundle", type=Path)
    imp.add_argument("--dry-run", action="store_true")
    imp.add_argument("--report", type=Path)
    sub.add_parser("inventory")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    if args.command == "inventory":
        print(json.dumps(inventory(url), indent=1, ensure_ascii=False))
        return 0
    if args.command == "export":
        bundle = export_bank(url)
        args.out.write_text(json.dumps(bundle, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"exported {len(bundle['exercises'])} eligible exercises; skipped "
              f"{[s['exercise_id'] for s in bundle['skipped']]}")
        return 0
    report = import_or_dry_run(url, json.loads(args.bundle.read_text(encoding="utf-8")), args.dry_run)
    if args.report:
        args.report.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("dry_run", "imported", "unchanged", "rejected",
                                             "counts_before", "counts_after", "student_records_untouched")},
                     indent=1, ensure_ascii=False))
    return 1 if report["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
