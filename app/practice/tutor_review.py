"""Tutor question review in the browser (T068, ADR-036). Replaces the JSON export/record round trip.

The queue and the verdicts are the existing individual review (T051): `seeding.item_review_export` lists every
active generated question of a subject's current batch that has no verdict, and `seeding.item_review_record`
records a verdict append-only in `generation.bank_item_review`. There is no second approval path: an approved
question becomes servable by the existing `QuestionBank` rule, a quarantined one is excluded and its cell
reopens. Pending questions stay ineligible until a verdict exists; nothing here approves anything by itself.

Served only by the tutor service under /api/tutor/review with the shared tutor check (allowed client address
and the tutor token). The reviewer recorded is `tutor`, the identity that token authenticates (the same value
the CLI records). A verdict is recorded exactly once: a repeated or simultaneous submission is refused (409).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from app.practice import seeding
from app.writing.tutor import LOOPBACK, tutor_guard

REVIEWER = "tutor"
LEVELS = ("easy", "medium", "hard")
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


class ReviewQueue:
    def __init__(self, url: Callable[[], str], baseline: str, subjects: tuple[tuple[str, str], ...],
                 open_catalog: Callable[[str], psycopg.Connection]):
        self.url, self.baseline, self.subjects, self.open_catalog = url, baseline, subjects, open_catalog

    def _batches(self) -> dict[str, dict[str, Any]]:
        out = {}
        for code, _ in self.subjects:
            batch = seeding.current_batch(self.url(), self.baseline, code)
            if batch is not None:
                out[code] = batch
        return out

    def pending(self, subject: str | None = None, objective: str | None = None, difficulty: str | None = None,
                batch: str | None = None) -> list[dict[str, Any]]:
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
        batch_id = next((b["batch_id"] for b in self._batches().values()
                         if any(r["request_id"] == d.request_id for r in seeding.links(self.url(), b["batch_id"]))),
                        None)
        if batch_id is None:
            raise seeding.NotAwaiting(f"{d.request_id} is not awaiting individual review")
        return seeding.item_review_record(self.url(), batch_id, [{
            "request_id": d.request_id, "verdict": d.verdict, "reason": d.reason, "comment": d.comment}], REVIEWER)


def build_review_router(queue: ReviewQueue, api_error: type[Exception], token: str,
                        allowed_hosts: frozenset[str] = LOOPBACK) -> APIRouter:
    router = APIRouter(prefix="/api/tutor/review", tags=["tutor"],
                       dependencies=[Depends(tutor_guard(api_error, token, allowed_hosts))])
    codes = {code for code, _ in queue.subjects}

    @router.get("/queue")
    def pending(subject: str | None = Query(default=None, max_length=40),
                objective: str | None = Query(default=None, max_length=20),
                difficulty: str | None = Query(default=None, max_length=10),
                batch: str | None = Query(default=None, max_length=64)) -> dict[str, Any]:
        if subject and subject not in codes:
            raise api_error(422, "unknown_subject", "La materia seleccionada no existe.")
        if difficulty and difficulty not in LEVELS:
            raise api_error(422, "unknown_difficulty", "La dificultad debe ser fácil, media o difícil.")
        questions = queue.pending(subject or None, (objective or "").strip().upper() or None,
                                  difficulty or None, batch or None)
        return {"questions": questions, "counts": queue.counts(), "reasons": list(seeding.REASONS)}

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
