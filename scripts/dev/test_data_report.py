"""Report test-generated practice records in the student database (T014.1, ADR-016). Read-only.

The connection sets default_transaction_read_only=on, so nothing can be deleted or updated.
Each practice session is classified:

- confirmed_test: identifiers only the mocked browser runner creates (practice_set_id `set-mock-…`,
  item_id `Q-mock-…`, source_request_id `req-mock-…`) or the seeded test bank (`e2e-bank-…`).
- probable_test: no such identifier, but the browser script's fingerprint: created within
  ADJACENT_S seconds of a confirmed test session, or a scripted configuration (Matemáticas
  M02/M04/M05 or M02/M06) answered with the scripted labels A, B, C, D, A in slot order.
- presumed_student: everything else.

Only probable_test needs a human decision. No question text, answer content or student data is printed.

Usage:
    .venv/Scripts/python.exe scripts/dev/test_data_report.py --out docs/progress/T016_test_data_report.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from curriculum import db  # noqa: E402

ADJACENT_S = 120
SCRIPTED_LABELS = "ABCDA"
SCRIPTED_CONFIGS = (["M02", "M04", "M05"], ["M02", "M06"])

SESSIONS_SQL = """
SELECT s.session_id, s.created_at, s.subject, s.status, s.cancelled_at IS NOT NULL AS cancelled,
       s.config->'objective_codes' AS objectives, s.config->>'difficulty' AS difficulty,
       s.practice_set_id, s.bank_count,
       (SELECT COUNT(*) FROM practice.item i WHERE i.session_id = s.session_id) AS items,
       (SELECT COUNT(*) FROM practice.answer a WHERE a.session_id = s.session_id) AS answers,
       (SELECT string_agg(a.chosen_label, '' ORDER BY a.slot) FROM practice.answer a
         WHERE a.session_id = s.session_id) AS labels,
       EXISTS (SELECT 1 FROM practice.item i WHERE i.session_id = s.session_id
               AND (i.item->>'item_id' LIKE 'Q-mock-%' OR i.item->>'item_id' LIKE 'Q-e2e-%'
                    OR i.source_request_id LIKE 'req-mock-%' OR i.source_request_id LIKE 'e2e-%')) AS test_items
FROM practice.session s ORDER BY s.created_at
"""


def classify(rows: list[dict]) -> None:
    confirmed_times = []
    for row in rows:
        reasons = []
        if (row["practice_set_id"] or "").startswith("set-mock-"):
            reasons.append("practice_set_id set-mock-…")
        if row["test_items"]:
            reasons.append("mock or e2e item identifiers")
        row["class"], row["evidence"] = ("confirmed_test", reasons) if reasons else ("presumed_student", [])
        if reasons:
            confirmed_times.append(row["created_at"])
    for row in rows:
        if row["class"] != "presumed_student":
            continue
        gap = min((abs((row["created_at"] - t).total_seconds()) for t in confirmed_times), default=None)
        if gap is not None and gap <= ADJACENT_S:
            row["evidence"].append(f"{gap:.0f} s from a confirmed test session")
        labels = row["labels"] or ""
        if row["subject"] == "matematicas" and row["objectives"] in SCRIPTED_CONFIGS and labels \
                and SCRIPTED_LABELS.startswith(labels):
            row["evidence"].append(f"scripted configuration answered {labels}")
        if row["evidence"]:
            row["class"] = "probable_test"


def render(rows: list[dict], database: str) -> str:
    totals = {c: {"sessions": 0, "items": 0, "answers": 0}
              for c in ("confirmed_test", "probable_test", "presumed_student")}
    for row in rows:
        t = totals[row["class"]]
        t["sessions"] += 1
        t["items"] += row["items"]
        t["answers"] += row["answers"]
    lines = [
        "# Test Data in the Student Database (T014.1)",
        "",
        f"> **Generated:** {datetime.now().astimezone():%Y-%m-%d %H:%M %Z} (read-only query of `{database}`)",
        "> **Action taken:** none. Cleanup requires explicit Product Owner approval.",
        "",
        "## Summary",
        "",
        "| Class | Sessions | Questions | Answers |",
        "|-------|----------|-----------|---------|",
        *(f"| {c} | {t['sessions']} | {t['items']} | {t['answers']} |" for c, t in totals.items()),
        f"| **Total** | {len(rows)} | {sum(r['items'] for r in rows)} | {sum(r['answers'] for r in rows)} |",
        "",
        "Classification rules are in the docstring of `scripts/dev/test_data_report.py`.",
        "",
    ]
    for cls, title in (("probable_test", "Ambiguous: Probable Test Sessions (decision needed)"),
                       ("presumed_student", "Presumed Student Sessions"),
                       ("confirmed_test", "Confirmed Test Sessions")):
        selected = [r for r in rows if r["class"] == cls]
        lines += [f"## {title}", ""]
        if not selected:
            lines += ["None.", ""]
            continue
        lines += ["| Session | Created | Subject | Objectives | Difficulty | Status | Bank | Answers | Evidence |",
                  "|---------|---------|---------|------------|------------|--------|------|---------|----------|"]
        for r in selected:
            status = r["status"] + (", cancelled" if r["cancelled"] else "")
            lines.append(f"| `{r['session_id'][:12]}` | {r['created_at']:%Y-%m-%d %H:%M:%S} | {r['subject']} | "
                         f"{', '.join(r['objectives'] or [])} | {r['difficulty']} | {status} | "
                         f"{r['bank_count']}/{r['items']} | {r['answers']} | {'; '.join(r['evidence']) or '—'} |")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    url = db.database_url()
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10,
                         options="-c default_transaction_read_only=on") as conn:
        rows = conn.execute(SESSIONS_SQL).fetchall()
    classify(rows)
    args.out.write_text(render(rows, db.database_name(url)), encoding="utf-8")
    counts = {c: sum(r["class"] == c for r in rows) for c in ("confirmed_test", "probable_test", "presumed_student")}
    print(f"REPORT={args.out} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
