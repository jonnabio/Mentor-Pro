"""Student question reports (T072, ADR-038 D3-D4).

The student reports a question of a practice session; the report holds the question out of new practices
(`bank.NOT_REPORTED_SQL`) until the tutor resolves it:

- retain: the question is valid; the reports close as `retained` and the hold clears. No verdict is recorded.
- quarantine: a `quarantined` verdict goes through the existing append-only review (`seeding._record_verdict`,
  which also deactivates the batch link and reopens the cell); the reports close as `quarantined`.

Existing practices keep their items, answers and scores; nothing here rewrites them. The tutor sees how many
practices used the question so they can be investigated.

There is no student authentication yet (one anonymous student, PO 2026-11-19): a report must name a slot of a real
practice session (the 32-hex session id is the capability). One report per session slot; a global cap bounds abuse.
Resolution is serialized with the tutor's verdicts (`seeding.REVIEW_LOCK`) and re-checks the open reports inside
the transaction, so a repeated or simultaneous resolution changes nothing the second time.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.practice import seeding
from app.practice.bank import QuestionBank

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()


def _ensure_schema(url: str) -> None:
    """Create the Question Bank tables once per database URL and process.

    The schema SQL takes an ACCESS EXCLUSIVE lock (ALTER TABLE ... ADD COLUMN IF NOT EXISTS) even when nothing
    changes; running it on every request deadlocked against a concurrent resolution's verdict insert."""
    if url in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if url not in _SCHEMA_READY:
            QuestionBank(url)
            _SCHEMA_READY.add(url)

REASONS = ("wrong_answer", "confusing", "missing_info", "display", "other")
COMMENT_MAX = 300
DAILY_CAP = 30  # reports accepted in any 24 hours (one student; bounds a stuck or abused client)
REPORT_LOCK = (seeding.LOCK_NAMESPACE, 2)  # serializes report creation for the cap ((4047, 1) is the review lock)
ACTIONS = ("retain", "quarantine")


class ReportError(RuntimeError):
    """A refused report operation; nothing was changed."""


class NotFound(ReportError):
    pass


class NotReportable(ReportError):
    pass


class CapReached(ReportError):
    pass


class NotOpen(ReportError):
    """No open report for the question (already resolved, possibly by a simultaneous request)."""


def content_sha256(item: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, row_factory=dict_row)


def create(url: str, session_id: str, slot: int, reason: str, comment: str | None) -> dict[str, Any]:
    """Record a student report for one slot of a session. Idempotent per slot: a repeat returns the first report."""
    if reason not in REASONS:
        raise ReportError(f"invalid reason {reason!r}")
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > COMMENT_MAX:
        raise ReportError("comment too long")
    _ensure_schema(url)  # the report table (fresh databases)
    with _connect(url) as conn, conn.transaction():
        row = conn.execute("SELECT i.item, i.source_request_id FROM practice.item i "
                           "WHERE i.session_id = %s AND i.slot = %s", (session_id, slot)).fetchone()
        if row is None:
            raise NotFound(f"{session_id}/{slot}")
        rid = row["source_request_id"]
        if not rid or conn.execute("SELECT 1 FROM generation.question_attempt WHERE request_id = %s",
                                   (rid,)).fetchone() is None:
            raise NotReportable(f"{session_id}/{slot} has no bank question")
        existing = conn.execute("SELECT report_id, status FROM generation.question_report "
                                "WHERE session_id = %s AND slot = %s", (session_id, slot)).fetchone()
        if existing:
            return {"report_id": existing["report_id"], "status": existing["status"], "already_reported": True}
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", REPORT_LOCK)
        recent = conn.execute("SELECT count(*) AS n FROM generation.question_report "
                              "WHERE created_at > now() - interval '24 hours'").fetchone()["n"]
        if recent >= DAILY_CAP:
            raise CapReached("daily report cap reached")
        item = row["item"]
        out = conn.execute(
            """INSERT INTO generation.question_report (request_id, item_id, content_sha256, session_id, slot, reason,
                                                       comment)
               VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (session_id, slot) DO NOTHING
               RETURNING report_id, status""",
            (rid, str(item.get("item_id", "")), content_sha256(item), session_id, slot, reason, comment)).fetchone()
        if out is None:  # a simultaneous identical report won
            out = conn.execute("SELECT report_id, status FROM generation.question_report "
                               "WHERE session_id = %s AND slot = %s", (session_id, slot)).fetchone()
            return {**out, "already_reported": True}
    return {**out, "already_reported": False}


def open_count(url: str) -> int:
    _ensure_schema(url)
    with _connect(url) as conn:
        return conn.execute("SELECT count(DISTINCT request_id) AS n FROM generation.question_report "
                            "WHERE status = 'open'").fetchone()["n"]


def open_reports(url: str) -> list[dict[str, Any]]:
    """Open reports grouped by question, oldest first, with what the tutor needs to decide. No student identity."""
    _ensure_schema(url)
    with _connect(url) as conn:
        reports = conn.execute(
            """SELECT r.report_id, r.request_id, r.reason, r.comment, r.created_at, r.content_sha256
               FROM generation.question_report r WHERE r.status = 'open' ORDER BY r.created_at, r.report_id"""
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        current: dict[str, str] = {}
        for r in reports:
            rid = r["request_id"]
            if rid not in out:
                q = conn.execute(
                    """SELECT q.item, q.objective_code, q.difficulty, q.verdict AS checker_verdict, q.checker_version,
                              q.validation,
                              (SELECT v.verdict FROM generation.bank_item_review v WHERE v.request_id = q.request_id
                               ORDER BY v.review_id DESC LIMIT 1) AS tutor_verdict,
                              (SELECT bi.batch_id FROM generation.bank_batch_item bi
                               WHERE bi.request_id = q.request_id AND bi.active) AS batch_id
                       FROM generation.question_attempt q WHERE q.request_id = %s""", (rid,)).fetchone()
                use = conn.execute(
                    """SELECT count(DISTINCT i.session_id) AS sessions, count(a.slot) AS answered,
                              count(a.slot) FILTER (WHERE a.is_correct) AS correct
                       FROM practice.item i LEFT JOIN practice.answer a USING (session_id, slot)
                       WHERE i.source_request_id = %s""", (rid,)).fetchone()
                item, validation = q["item"], q["validation"] or {}
                out[rid] = {
                    "request_id": rid, "subject": item.get("subject"), "objective_code": q["objective_code"],
                    "difficulty": q["difficulty"], "stimulus": item.get("stimulus"), "stem": item.get("stem"),
                    "options": item.get("options", []), "answer_key": item.get("answer_key"),
                    "explanation": item.get("explanation"), "batch_id": q["batch_id"],
                    "tutor_verdict": q["tutor_verdict"],
                    "validation": {"checker_verdict": q["checker_verdict"], "checker_version": q["checker_version"],
                                   "independent_solve_agrees": (validation.get("independent_solve") or {})
                                   .get("agrees_with_key"),
                                   "rubric": validation.get("rubric")},
                    "used_in": use, "reports": []}
                current[rid] = content_sha256(item)
            # same_content: the student saw exactly the bank's current content (served items are copies).
            out[rid]["reports"].append({"report_id": r["report_id"], "reason": r["reason"], "comment": r["comment"],
                                        "created_at": r["created_at"].isoformat(),
                                        "same_content": r["content_sha256"] == current[rid]})
    return list(out.values())


def resolve(url: str, request_id: str, action: str, reason: str = "", comment: str = "",
            resolver: str = "tutor") -> dict[str, Any]:
    """Resolve every open report of one question, exactly once (see module docstring)."""
    if action not in ACTIONS:
        raise ReportError(f"invalid action {action!r}")
    if action == "quarantine" and reason not in seeding.REASONS:
        raise ReportError("quarantine needs a reason")
    comment = (comment or "").strip() or None
    if comment is not None and len(comment) > seeding.COMMENT_MAX:
        raise ReportError("comment too long")
    _ensure_schema(url)
    with _connect(url) as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s, %s)", seeding.REVIEW_LOCK)
        ids = [r["report_id"] for r in conn.execute(
            "SELECT report_id FROM generation.question_report WHERE request_id = %s AND status = 'open' FOR UPDATE",
            (request_id,))]
        if not ids:
            raise NotOpen(request_id)
        verdict_recorded = False
        if action == "quarantine":
            latest = conn.execute("SELECT verdict FROM generation.bank_item_review WHERE request_id = %s "
                                  "ORDER BY review_id DESC LIMIT 1", (request_id,)).fetchone()
            if latest is None or latest["verdict"] != "quarantined":  # never a second quarantine row
                batch = conn.execute("SELECT batch_id FROM generation.bank_batch_item WHERE request_id = %s",
                                     (request_id,)).fetchone()
                seeding._record_verdict(conn, request_id, batch["batch_id"] if batch else None, "quarantined",
                                        reason, resolver, comment)
                verdict_recorded = True
        status = "retained" if action == "retain" else "quarantined"
        conn.execute("""UPDATE generation.question_report SET status = %s, resolved_at = now(), resolver = %s,
                               resolution_comment = %s WHERE report_id = ANY(%s)""",
                     (status, resolver, comment, ids))
    return {"request_id": request_id, "status": status, "reports": len(ids), "verdict_recorded": verdict_recorded}
