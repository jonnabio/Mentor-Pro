"""Tutor practice results and Question Bank analytics (T060). Read-only.

Served only under /api/tutor with the shared tutor check (`tutor_guard`: allowed client address and the
tutor token). Every query runs in a read-only transaction against the existing practice tables; nothing
is written, generated or scored here. Sessions classified `automated_test` or `quarantined` (ADR-017) are
left out, like the learning dashboard. No student name or identifier exists in these tables or responses.

A question is identified by its bank request (`practice.item.source_request_id`); an item without one is
its own question. "Unanswered" (served, no answer) is counted apart from "incorrect".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from app.writing.tutor import LOOPBACK, tutor_guard

HISTORY_LIMIT = 200
LOCAL_TZ = "America/Costa_Rica"
SOURCES = ("bank", "generated")
STUDENT_ONLY = """NOT EXISTS (SELECT 1 FROM practice.session_classification c
                   WHERE c.session_id = s.session_id AND c.classification <> 'student')"""
SESSION_SQL = """SELECT s.session_id, s.created_at, s.subject, s.config, s.allocation, s.status,
       s.cancelled_at IS NOT NULL AS cancelled, COUNT(i.slot) AS items,
       COUNT(i.slot) FILTER (WHERE i.source = 'bank') AS bank,
       COUNT(i.slot) FILTER (WHERE i.source = 'generated') AS generated,
       COUNT(a.slot) AS answered, COUNT(a.slot) FILTER (WHERE a.is_correct) AS correct
FROM practice.session s
LEFT JOIN practice.item i ON i.session_id = s.session_id
LEFT JOIN practice.answer a ON a.session_id = i.session_id AND a.slot = i.slot
WHERE {where} GROUP BY s.session_id"""
QUESTION_KEY = "COALESCE(i.source_request_id, i.session_id || ':' || i.slot)"


def _rate(correct: int, answered: int) -> float | None:
    return None if answered == 0 else round(correct / answered, 4)


def practice_state(status: str, cancelled: bool, items: int, answered: int) -> str:
    """preparing, failed, not_started, in_progress, left (cancelled before the end) or completed."""
    if status in ("queued", "running"):
        return "preparing"
    if status == "failed" or items == 0:
        return "failed"
    if answered == items:
        return "completed"
    if cancelled:
        return "left"
    return "not_started" if answered == 0 else "in_progress"


def _difficulties(allocation: list[dict[str, Any]]) -> dict[int, str]:
    return {s["slot"]: s["difficulty"] for row in allocation or [] for s in row.get("slots", [])}


class PracticeResults:
    """Read-only access to practice history, answers and per-question statistics."""

    def __init__(self, url: Callable[[], str]):
        self.url = url

    def _rows(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        with psycopg.connect(self.url(), row_factory=dict_row) as conn:
            conn.read_only = True
            try:
                return conn.execute(sql, params).fetchall()
            except psycopg.errors.UndefinedTable:
                return []  # no practice has ever been created on this database

    @staticmethod
    def _filters(subject: str | None, objective: str | None, date_from: date | None, date_to: date | None,
                 source: str | None, item_level: bool) -> tuple[str, list[Any]]:
        where, params = [STUDENT_ONLY], []
        if subject:
            where.append("s.subject = %s")
            params.append(subject)
        if date_from:
            where.append(f"(s.created_at AT TIME ZONE '{LOCAL_TZ}')::date >= %s")
            params.append(date_from)
        if date_to:
            where.append(f"(s.created_at AT TIME ZONE '{LOCAL_TZ}')::date <= %s")
            params.append(date_to)
        if item_level:
            if objective:
                where.append("i.objective_code = %s")
                params.append(objective)
            if source:
                where.append("i.source = %s")
                params.append(source)
        else:
            for column, value in (("objective_code", objective), ("source", source)):
                if value:
                    where.append(f"EXISTS (SELECT 1 FROM practice.item f WHERE f.session_id = s.session_id "
                                 f"AND f.{column} = %s)")
                    params.append(value)
        return " AND ".join(where), params

    def history(self, subject: str | None = None, objective: str | None = None, date_from: date | None = None,
                date_to: date | None = None, source: str | None = None) -> list[dict[str, Any]]:
        where, params = self._filters(subject, objective, date_from, date_to, source, item_level=False)
        rows = self._rows(
            SESSION_SQL.format(where=where) + f" ORDER BY s.created_at DESC LIMIT {HISTORY_LIMIT}", params)
        return [self._session_view(r) for r in rows]

    @staticmethod
    def _session_view(r: dict[str, Any]) -> dict[str, Any]:
        config = r["config"] or {}
        objectives = sorted({row["workbook_code"] for row in r["allocation"] or [] if row.get("workbook_code")})
        return {
            "session_id": r["session_id"], "created_at": r["created_at"].isoformat(), "subject": r["subject"],
            "scope": config.get("scope"), "objectives": objectives, "difficulty": config.get("difficulty"),
            "question_count": config.get("question_count"), "status": r["status"],
            "state": practice_state(r["status"], r["cancelled"], r["items"], r["answered"]),
            "composition": {"bank": r["bank"], "generated": r["generated"]},
            "questions": r["items"], "answered": r["answered"], "correct": r["correct"],
            "unanswered": r["items"] - r["answered"], "incorrect": r["answered"] - r["correct"],
            "accuracy": _rate(r["correct"], r["answered"])}

    def detail(self, session_id: str) -> dict[str, Any] | None:
        found = self.history_by_id(session_id)
        if not found:
            return None
        session = found[0]
        difficulty = _difficulties(session.pop("_allocation"))
        rows = self._rows(
            """SELECT i.slot, i.objective_code, i.item, i.source, a.chosen_label, a.is_correct, a.answered_at
               FROM practice.item i LEFT JOIN practice.answer a USING (session_id, slot)
               WHERE i.session_id = %s ORDER BY i.slot""", [session_id])
        session["items"] = [{
            "slot": r["slot"], "objective_code": r["objective_code"], "source": r["source"],
            "difficulty": r["item"].get("difficulty") or difficulty.get(r["slot"]),
            "stimulus": r["item"].get("stimulus"), "stem": r["item"]["stem"],
            "options": [{"label": o["label"], "text": o["text"]} for o in r["item"]["options"]],
            "chosen_label": r["chosen_label"], "correct_label": r["item"]["answer_key"],
            "explanation": r["item"].get("explanation", ""),
            "result": "unanswered" if r["chosen_label"] is None else ("correct" if r["is_correct"] else "incorrect"),
            "answered_at": r["answered_at"].isoformat() if r["answered_at"] else None} for r in rows]
        return session

    def history_by_id(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            SESSION_SQL.format(where=f"s.session_id = %s AND {STUDENT_ONLY}"), [session_id])
        return [{**self._session_view(r), "_allocation": r["allocation"]} for r in rows]

    def questions(self, subject: str | None = None, objective: str | None = None, date_from: date | None = None,
                  date_to: date | None = None, source: str | None = None) -> dict[str, Any]:
        """Per question: times served, answered, correct, incorrect, unanswered and success rate."""
        where, params = self._filters(subject, objective, date_from, date_to, source, item_level=True)
        rows = self._rows(
            f"""SELECT {QUESTION_KEY} AS question_key, s.subject, i.objective_code, i.source,
                       s.allocation, i.slot, i.item, s.created_at, a.slot IS NOT NULL AS answered, a.is_correct
                FROM practice.item i
                JOIN practice.session s ON s.session_id = i.session_id
                LEFT JOIN practice.answer a ON a.session_id = i.session_id AND a.slot = i.slot
                WHERE {where} ORDER BY s.created_at""", params)
        questions: dict[str, dict[str, Any]] = {}
        for r in rows:
            q = questions.get(r["question_key"])
            if q is None:
                q = questions[r["question_key"]] = {
                    "subject": r["subject"], "objective_code": r["objective_code"], "source": r["source"],
                    "difficulty": r["item"].get("difficulty") or _difficulties(r["allocation"]).get(r["slot"]),
                    "stem": r["item"]["stem"], "served": 0, "answered": 0, "correct": 0}
            q["served"] += 1
            q["answered"] += int(r["answered"])
            q["correct"] += int(bool(r["is_correct"]))
        groups: dict[tuple[str, str, str], dict[str, Any]] = {}
        out = []
        for q in questions.values():
            q.update(incorrect=q["answered"] - q["correct"], unanswered=q["served"] - q["answered"],
                     success_rate=_rate(q["correct"], q["answered"]))
            out.append(q)
            key = (q["subject"], q["objective_code"], q["difficulty"] or "")
            g = groups.setdefault(key, {"subject": key[0], "objective_code": key[1], "difficulty": q["difficulty"],
                                        "questions": 0, "served": 0, "answered": 0, "correct": 0})
            g["questions"] += 1
            for field in ("served", "answered", "correct"):
                g[field] += q[field]
        for g in groups.values():
            g.update(incorrect=g["answered"] - g["correct"], unanswered=g["served"] - g["answered"],
                     success_rate=_rate(g["correct"], g["answered"]))
        order = lambda x: (x["subject"], x["objective_code"], x["difficulty"] or "")  # noqa: E731
        return {"questions": sorted(out, key=lambda x: (*order(x), x["stem"])),
                "groups": sorted(groups.values(), key=order)}


def build_practice_results_router(results: PracticeResults, api_error: type[Exception], token: str,
                                  allowed_hosts: frozenset[str] = LOOPBACK,
                                  subjects: tuple[tuple[str, str], ...] = ()) -> APIRouter:
    """GET-only tutor routes; the same tutor check as writing review."""
    router = APIRouter(prefix="/api/tutor/practice", tags=["tutor"],
                       dependencies=[Depends(tutor_guard(api_error, token, allowed_hosts))])
    codes = {code for code, _ in subjects}

    def filters(subject: str | None = Query(default=None, max_length=40),
                objective: str | None = Query(default=None, max_length=20),
                date_from: date | None = Query(default=None, alias="from"),
                date_to: date | None = Query(default=None, alias="to"),
                source: str | None = Query(default=None, max_length=20)) -> dict[str, Any]:
        if subject and codes and subject not in codes:
            raise api_error(422, "unknown_subject", "La materia seleccionada no existe.")
        if source and source not in SOURCES:
            raise api_error(422, "unknown_source", "El origen debe ser banco o generada.")
        if date_from and date_to and date_from > date_to:
            raise api_error(422, "invalid_dates", "La fecha inicial es posterior a la final.")
        return {"subject": subject or None, "objective": (objective or "").strip().upper() or None,
                "date_from": date_from, "date_to": date_to, "source": source or None}

    @router.get("/sessions")
    def sessions(f: dict[str, Any] = Depends(filters)) -> dict[str, Any]:
        return {"subjects": [{"code": c, "name_es": n} for c, n in subjects],
                "sessions": results.history(**f), "limit": HISTORY_LIMIT}

    @router.get("/sessions/{session_id}")
    def session(session_id: str) -> dict[str, Any]:
        found = results.detail(session_id) if len(session_id) <= 64 else None
        if found is None:
            raise api_error(404, "session_not_found", "No encontramos esta práctica.")
        return found

    @router.get("/questions")
    def questions(f: dict[str, Any] = Depends(filters)) -> dict[str, Any]:
        return results.questions(**f)

    return router
