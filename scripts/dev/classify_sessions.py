"""Classify historical practice sessions in the student database (T017, ADR-017).

Dry run by default: recompute the T016 classes (test_data_report.classify), compare them with the
frozen manifest and print what would change. Nothing is ever deleted; sessions, items and answers
are never modified. Exclusion is recorded in practice.session_classification.

Usage:
    .venv/Scripts/python.exe scripts/dev/classify_sessions.py --freeze      # write the manifest (once)
    .venv/Scripts/python.exe scripts/dev/classify_sessions.py               # dry run
    .venv/Scripts/python.exe scripts/dev/classify_sessions.py --apply --backup FILE.dump --metrics OUT.json
    .venv/Scripts/python.exe scripts/dev/classify_sessions.py --rollback T017-2026-10-24
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "dev"))
from curriculum import db  # noqa: E402
from test_data_report import SESSIONS_SQL, classify  # noqa: E402

MANIFEST = ROOT / "docs" / "progress" / "T017_classification_manifest.json"
AUDIT_REF = "T017-2026-10-24"
TARGET = {"confirmed_test": "automated_test", "probable_test": "quarantined", "presumed_student": "student"}
EXPECTED = {"confirmed_test": (103, 308), "probable_test": (14, 68), "presumed_student": (2, 5)}  # sessions, answers
REASONS = {
    "automated_test": "T016 report: mocked browser runner identifiers (set-mock / Q-mock); PO decision T017",
    "quarantined": "T016 report: probable browser test (timing or scripted answers); PO decision T017",
    "student": "T016 report: no test marker; PO decision T017 (preserve)",
}


def current_classes(conn: psycopg.Connection) -> dict[str, dict]:
    rows = conn.execute(SESSIONS_SQL).fetchall()
    classify(rows)
    return {r["session_id"]: {"class": r["class"], "answers": r["answers"]} for r in rows}


def check(current: dict[str, dict], manifest: dict[str, dict]) -> list[str]:
    """Differences between the database and the manifest, plus the approved totals; empty means safe."""
    problems = []
    for cls, (sessions, answers) in EXPECTED.items():
        ids = [s for s, v in manifest.items() if v["class"] == cls]
        got = (len(ids), sum(manifest[s]["answers"] for s in ids))
        if got != (sessions, answers):
            problems.append(f"manifest {cls}: {got} != approved {(sessions, answers)}")
    for sid, expected in manifest.items():
        actual = current.get(sid)
        if actual is None:
            problems.append(f"session {sid[:12]} missing from the database")
        elif actual != expected:
            problems.append(f"session {sid[:12]}: database {actual} != manifest {expected}")
    for sid in current.keys() - manifest.keys():
        problems.append(f"session {sid[:12]} not in the manifest (created after the T016 report)")
    return problems


def verify_backup(path: Path) -> None:
    pg_restore = shutil.which("pg_restore") or r"C:\Program Files\PostgreSQL\17\bin\pg_restore.exe"
    listing = subprocess.run([pg_restore, "--list", str(path)], capture_output=True, text=True, check=False)
    if listing.returncode != 0 or "TABLE DATA practice answer" not in listing.stdout:
        raise SystemExit(f"backup {path} is not a readable pg_dump archive with practice.answer data")


def metrics(url: str) -> dict:
    """Dashboard summary per subject (the same calculation as GET /api/dashboard)."""
    from app.main import BASELINE_VERSION, SUBJECTS
    from app.practice.mastery import Thresholds, subject_dashboard
    from curriculum.catalog import list_objectives

    out = {}
    with db.connect(url, read_only=True) as conn:
        for code, _ in SUBJECTS:
            s = subject_dashboard(conn, BASELINE_VERSION, code, list_objectives(conn, BASELINE_VERSION, code),
                                  Thresholds.from_env())
            out[code] = {k: s[k] for k in ("objective_count", "total_answers", "practice_accuracy",
                                           "distinct_questions", "mastery_accuracy", "repeat_exposure_rate",
                                           "status_counts")}
    return out


def apply(conn: psycopg.Connection, manifest: dict[str, dict]) -> dict[str, int]:
    """One transaction under an advisory lock; idempotent; refuses conflicting earlier classifications."""
    written = {"inserted": 0, "unchanged": 0}
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('practice.session_classification'))")
        existing = {r["session_id"]: r["classification"] for r in
                    conn.execute("SELECT session_id, classification FROM practice.session_classification")}
        for sid, entry in sorted(manifest.items()):
            target = TARGET[entry["class"]]
            if sid in existing:
                if existing[sid] != target:
                    raise SystemExit(f"session {sid[:12]} already classified {existing[sid]}, not {target}")
                written["unchanged"] += 1
                continue
            conn.execute("""INSERT INTO practice.session_classification
                                (session_id, classification, reason, audit_ref) VALUES (%s, %s, %s, %s)""",
                         (sid, target, REASONS[target], AUDIT_REF))
            conn.execute("""INSERT INTO practice.classification_audit
                                (session_id, action, previous, classification, reason, audit_ref)
                            VALUES (%s, 'classify', NULL, %s, %s, %s)""", (sid, target, REASONS[target], AUDIT_REF))
            written["inserted"] += 1
    return written


def rollback(conn: psycopg.Connection, audit_ref: str) -> int:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('practice.session_classification'))")
        rows = conn.execute("SELECT session_id, classification FROM practice.session_classification "
                            "WHERE audit_ref = %s", (audit_ref,)).fetchall()
        for r in rows:
            conn.execute("""INSERT INTO practice.classification_audit
                                (session_id, action, previous, classification, reason, audit_ref)
                            VALUES (%s, 'rollback', %s, NULL, 'rollback of ' || %s, %s)""",
                         (r["session_id"], r["classification"], audit_ref, audit_ref))
        conn.execute("DELETE FROM practice.session_classification WHERE audit_ref = %s", (audit_ref,))
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--freeze", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--rollback", metavar="AUDIT_REF")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--metrics", type=Path, help="write before/after dashboard metrics here (--apply)")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()

    if args.rollback:
        with psycopg.connect(url, row_factory=dict_row) as conn:
            print(f"ROLLBACK={rollback(conn, args.rollback)} sessions returned to student")
        return 0

    with psycopg.connect(url, row_factory=dict_row, options="-c default_transaction_read_only=on") as conn:
        current = current_classes(conn)
    if args.freeze:
        if MANIFEST.exists():
            raise SystemExit(f"{MANIFEST.name} already exists; it is frozen")
        MANIFEST.write_text(json.dumps({"audit_ref": AUDIT_REF, "sessions": current}, indent=1, sort_keys=True)
                            + "\n", encoding="utf-8", newline="\n")
        print(f"FROZEN={len(current)} sessions")
        return 0

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["sessions"]
    problems = check(current, manifest)
    for cls, target in TARGET.items():
        ids = [s for s, v in manifest.items() if v["class"] == cls]
        print(f"PLAN {target:15} {len(ids):4} sessions {sum(manifest[s]['answers'] for s in ids):4} answers")
    if problems:
        print("REFUSED:\n  " + "\n  ".join(problems))
        return 3
    if not args.apply:
        print("DRY_RUN=ok (nothing written)")
        return 0
    if not args.backup or not args.backup.is_file():
        raise SystemExit("--apply requires --backup with an existing pg_dump archive")
    verify_backup(args.backup)
    from app.practice.store import PracticeStore

    PracticeStore(url)  # the application's own DDL: creates the classification tables if missing
    before = metrics(url)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        written = apply(conn, manifest)
    after = metrics(url)
    if args.metrics:
        args.metrics.write_text(json.dumps({"before": before, "after": after}, indent=1) + "\n",
                                encoding="utf-8", newline="\n")
    print(f"APPLIED={written} audit_ref={AUDIT_REF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
