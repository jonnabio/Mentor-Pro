"""Tutor question review in the browser (T068, ADR-036). Replaces the JSON export/record round trip.

The queue and the verdicts are the existing individual review (T051): `seeding.item_review_export` lists every
active generated question of a subject's current batch that has no verdict, and `seeding.item_review_record`
records a verdict append-only in `generation.bank_item_review`. There is no second approval path: an approved
question becomes servable by the existing `QuestionBank` rule, a quarantined one is excluded and its cell
reopens. Pending questions stay ineligible until a verdict exists; nothing here approves anything by itself.

Served only by the tutor service under /api/tutor/review with the shared tutor check (allowed client address
and the tutor token). The reviewer recorded is `tutor`, the identity that token authenticates (the same value
the CLI records). A verdict is recorded exactly once: a repeated or simultaneous submission is refused (409).

T071 bulk approval: the tutor selects explicit question IDs on the page and confirms. Each ID goes through the same
`item_review_record` call in its own transaction (same lock, re-check and audit row), so one refused ID never
undoes or blocks the others and the database never holds a half-recorded verdict. Bulk approval only approves;
quarantine stays individual because it needs a reason per question.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi import Path as PathParam
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app.practice import question_reports, seeding
from app.practice.bank import QuestionBank, auto_eligibility
from app.writing.tutor import LOOPBACK, tutor_guard

REVIEWER = "tutor"
LEVELS = ("easy", "medium", "hard")
BULK_MAX = 50  # T071: the most question IDs one bulk approval accepts
PAGE_SIZE_MAX = 50
COUNTS_SQL = """
SELECT b.subject,
       COUNT(*) FILTER (WHERE v.verdict = 'approved') AS approved,
       COUNT(*) FILTER (WHERE v.verdict = 'quarantined') AS quarantined
FROM (SELECT DISTINCT ON (request_id) request_id, batch_id, verdict FROM generation.bank_item_review
      ORDER BY request_id, recorded_at DESC, review_id DESC) v
JOIN generation.bank_batch b ON b.batch_id = v.batch_id
WHERE b.baseline_version = %s GROUP BY b.subject"""


class Decision(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    verdict: str = Field(pattern="^(approved|quarantined)$")
    reason: str = Field(default="", max_length=40)
    comment: str = Field(default="", max_length=seeding.COMMENT_MAX)


class BulkApproval(BaseModel):
    request_ids: list[str] = Field(min_length=1)


class ReviewQueue:
    def __init__(self, url: Callable[[], str], baseline: str, subjects: tuple[tuple[str, str], ...],
                 open_catalog: Callable[[str], psycopg.Connection]):
        self.url, self.baseline, self.subjects, self.open_catalog = url, baseline, subjects, open_catalog
        self._schema_ready = False

    def ensure_schema(self) -> None:
        """Apply the existing Question Bank schema (the idempotent `QuestionBank` initialisation, which adds the
        T068 `comment` column) once per process. The tutor service calls it at startup, so recording a review never
        depends on student practice or scheduled generation having initialised the bank first; every queue
        operation calls it too, covering a database that was unreachable at startup."""
        if not self._schema_ready:
            QuestionBank(self.url())
            self._schema_ready = True

    def _batches(self) -> dict[str, dict[str, Any]]:
        out = {}
        for code, _ in self.subjects:
            batch = seeding.current_batch(self.url(), self.baseline, code)
            if batch is not None:
                out[code] = batch
        return out

    def pending(self, subject: str | None = None, objective: str | None = None, difficulty: str | None = None,
                batch: str | None = None) -> list[dict[str, Any]]:
        self.ensure_schema()
        url, rows = self.url(), []
        catalog = self.open_catalog(url)
        try:
            for code, b in self._batches().items():
                if subject not in (None, code) or batch not in (None, b["batch_id"]):
                    continue
                for q in seeding.item_review_export(url, catalog, b["batch_id"], objective)["questions"]:
                    if difficulty in (None, q["difficulty"]):
                        q.pop("verdict", None), q.pop("reason", None)
                        rows.append({"subject": code, "batch_id": b["batch_id"], **q})
        finally:
            catalog.close()
        return rows

    def counts(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with psycopg.connect(self.url(), row_factory=dict_row) as conn:
            done = {r["subject"]: r for r in conn.execute(COUNTS_SQL, (self.baseline,))}
        waiting: dict[str, int] = {}
        for row in self.pending():
            waiting[row["subject"]] = waiting.get(row["subject"], 0) + 1
        return [{"subject": code, "name_es": name, "pending": waiting.get(code, 0),
                 "approved": done.get(code, {}).get("approved", 0),
                 "quarantined": done.get(code, {}).get("quarantined", 0)} for code, name in self.subjects]

    def decide(self, d: Decision) -> dict[str, Any]:
        """One verdict through the existing individual review; the batch is the current batch holding it."""
        self.ensure_schema()
        batch_id = next((b["batch_id"] for b in self._batches().values()
                         if any(r["request_id"] == d.request_id for r in seeding.links(self.url(), b["batch_id"]))),
                        None)
        if batch_id is None:
            raise seeding.NotAwaiting(f"{d.request_id} is not awaiting individual review")
        return seeding.item_review_record(self.url(), batch_id, [{
            "request_id": d.request_id, "verdict": d.verdict, "reason": d.reason, "comment": d.comment}], REVIEWER)

    def approve_many(self, request_ids: list[str]) -> list[dict[str, str]]:
        """T071: approve explicit IDs, one existing individual verdict (own transaction) per ID. Returns one result
        per ID in request order: approved, already_reviewed (a verdict exists), not_pending (unknown here, not a
        generated question, or no longer actively linked) or error (the database refused; nothing recorded)."""
        self.ensure_schema()
        url = self.url()
        batch_of = {r["request_id"]: b["batch_id"] for b in self._batches().values()
                    for r in seeding.links(url, b["batch_id"])}
        results = []
        for rid in request_ids:
            status = "not_pending"
            if rid in batch_of:
                try:
                    seeding.item_review_record(url, batch_of[rid], [{"request_id": rid, "verdict": "approved"}],
                                               REVIEWER)
                    status = "approved"
                except seeding.NotAwaiting:
                    status = "already_reviewed" if self._has_verdict(rid) else "not_pending"
                except (seeding.SeedError, psycopg.Error):
                    status = "error"
            elif self._has_verdict(rid):
                status = "already_reviewed"
            results.append({"request_id": rid, "status": status})
        return results

    def _has_verdict(self, request_id: str) -> bool:
        with psycopg.connect(self.url()) as conn:
            return conn.execute("SELECT 1 FROM generation.bank_item_review WHERE request_id = %s LIMIT 1",
                                (request_id,)).fetchone() is not None


def build_review_router(queue: ReviewQueue, api_error: type[Exception], token: str,
                        allowed_hosts: frozenset[str] = LOOPBACK) -> APIRouter:
    router = APIRouter(prefix="/api/tutor/review", tags=["tutor"],
                       dependencies=[Depends(tutor_guard(api_error, token, allowed_hosts))])
    codes = {code for code, _ in queue.subjects}

    @router.get("/queue")
    def pending(subject: str | None = Query(default=None, max_length=40),
                objective: str | None = Query(default=None, max_length=20),
                difficulty: str | None = Query(default=None, max_length=10),
                batch: str | None = Query(default=None, max_length=64),
                page: int | None = Query(default=None, ge=1),
                page_size: int | None = Query(default=None, ge=1, le=PAGE_SIZE_MAX)) -> dict[str, Any]:
        if subject and subject not in codes:
            raise api_error(422, "unknown_subject", "La materia seleccionada no existe.")
        if difficulty and difficulty not in LEVELS:
            raise api_error(422, "unknown_difficulty", "La dificultad debe ser fácil, media o difícil.")
        questions = queue.pending(subject or None, (objective or "").strip().upper() or None,
                                  difficulty or None, batch or None)
        out: dict[str, Any] = {"counts": queue.counts(), "reasons": list(seeding.REASONS), "total": len(questions),
                               "auto_eligibility": auto_eligibility()}  # T072: review optional when on
        if page_size is not None or page is not None:  # T071: optional paging; without it the full list (T068)
            size = page_size or 10
            pages = max(1, -(-len(questions) // size))
            current = min(page or 1, pages)
            questions = questions[(current - 1) * size:current * size]
            out["pagination"] = {"page": current, "page_size": size, "pages": pages}
        return {"questions": questions, **out}

    @router.post("/bulk-approve")
    def bulk_approve(body: BulkApproval) -> dict[str, Any]:
        ids = [i.strip() for i in body.request_ids]
        if len(ids) > BULK_MAX:
            raise api_error(422, "too_many", f"Podés aprobar como máximo {BULK_MAX} preguntas a la vez.")
        if any(not i or len(i) > 64 for i in ids):
            raise api_error(422, "invalid_id", "Hay un identificador de pregunta inválido.")
        if len(set(ids)) != len(ids):
            raise api_error(422, "duplicate_ids", "La selección repite una pregunta.")
        results = queue.approve_many(ids)
        approved = sum(1 for r in results if r["status"] == "approved")
        return {"requested": len(ids), "approved": approved, "failed": len(ids) - approved,
                "results": results, "counts": queue.counts()}

    @router.post("/decisions")
    def decide(decision: Decision) -> dict[str, Any]:
        if decision.verdict == "quarantined" and decision.reason not in seeding.REASONS:
            raise api_error(422, "reason_required", "Elegí el motivo de la cuarentena.")
        if decision.verdict == "approved" and decision.reason not in ("", "approved"):
            raise api_error(422, "invalid_reason", "Una aprobación no lleva motivo de cuarentena.")
        try:
            out = queue.decide(decision)
        except seeding.NotAwaiting:
            raise api_error(409, "already_reviewed", "Esta pregunta ya tiene una decisión registrada.") from None
        except seeding.SeedError:
            raise api_error(422, "invalid_decision", "La decisión no es válida.") from None
        return {**out, "counts": queue.counts()}

    return router


class Resolution(BaseModel):
    """T072: the tutor's resolution of every open report of one question (ADR-038 D4)."""
    action: str = Field(pattern="^(retain|quarantine)$")
    reason: str = Field(default="", max_length=40)
    comment: str = Field(default="", max_length=seeding.COMMENT_MAX)


def build_reports_router(url: Callable[[], str], api_error: type[Exception], token: str,
                         allowed_hosts: frozenset[str] = LOOPBACK) -> APIRouter:
    """T072: student reports in the tutor service only (same tutor check as the review). No student identity."""
    router = APIRouter(prefix="/api/tutor/reports", tags=["tutor"],
                       dependencies=[Depends(tutor_guard(api_error, token, allowed_hosts))])

    @router.get("")
    def reports() -> dict[str, Any]:
        questions = question_reports.open_reports(url())
        return {"questions": questions, "open": len(questions), "reasons": list(seeding.REASONS),
                "auto_eligibility": auto_eligibility()}

    @router.post("/{request_id}/resolve")
    def resolve(body: Resolution, request_id: str = PathParam(min_length=1, max_length=64)) -> dict[str, Any]:
        if body.action == "quarantine" and body.reason not in seeding.REASONS:
            raise api_error(422, "reason_required", "Elegí el motivo de la cuarentena.")
        try:
            out = question_reports.resolve(url(), request_id, body.action, body.reason, body.comment, REVIEWER)
        except question_reports.NotOpen:
            raise api_error(409, "not_open", "Este reporte ya fue resuelto.") from None
        except question_reports.ReportError:
            raise api_error(422, "invalid_resolution", "La resolución no es válida.") from None
        return {**out, "open": question_reports.open_count(url())}

    return router
