"""Student practice API (T010 ADR-013; question bank T013 ADR-014).

Answer keys and explanations never leave the server before the student answers
a question; answers are evaluated here. All student-facing text is Spanish
(Costa Rica).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from app.allocation import allocate
from app.practice.bank import QuestionBank
from app.practice.jobs import JobQueue, SetRunner
from app.practice.store import PracticeStore
from curriculum.catalog import PracticeScope, SelectionError, select_objectives

SESSION_ID = Path(pattern=r"^[0-9a-f]{32}$")

STATUS_ES = {
    "queued": "Generando preguntas adicionales. La generación comenzará en un momento.",
    "running": "Generando preguntas adicionales. Esto puede tardar varios minutos.",
    "complete": "Su práctica está lista.",
}
STOP_ES = {
    "daily_budget": "Se alcanzó el límite diario de generación de preguntas.",
    "set_call_limit": "Se alcanzó el límite de solicitudes para esta práctica.",
    "llm_unavailable": "El servicio de generación de preguntas no respondió.",
    "slot_retries_exhausted": "Algunas preguntas no superaron la revisión de calidad.",
    "interrupted": "La generación se interrumpió porque el servidor se reinició.",
    "internal_error": "Ocurrió un error inesperado al generar la práctica.",
}


class SessionRequest(BaseModel):
    subject: Literal["espanol", "matematicas", "ciencias", "estudios_sociales"]
    scope: PracticeScope
    objective_codes: list[str] = Field(default_factory=list, max_length=100)
    difficulty: Literal["easy", "medium", "hard", "mixed"]
    question_count: Literal[5]
    client_request_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")
    # Anonymous per-tab token (sessionStorage); only its hash is stored, to prefer unseen bank questions.
    browser_token: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{16,64}$")


class AnswerRequest(BaseModel):
    slot: int = Field(ge=1, le=30)
    label: Literal["A", "B", "C", "D"]


class PracticeService:
    """Store and job queue, created on first use (the database may be absent when the app is built)."""

    def __init__(self, url_factory: Callable[[], str], runner_factory: Callable[[], SetRunner]):
        self._url_factory, self._runner_factory = url_factory, runner_factory
        self._lock = threading.Lock()
        self._ready: tuple[PracticeStore, JobQueue, QuestionBank] | None = None

    def get(self) -> tuple[PracticeStore, JobQueue, QuestionBank]:
        with self._lock:
            if self._ready is None:
                url = self._url_factory()
                store = PracticeStore(url)
                store.fail_interrupted()  # jobs of a previous process cannot finish
                self._ready = (store, JobQueue(store, self._runner_factory()), QuestionBank(url))
            return self._ready


def message_es(session: dict[str, Any], available: int) -> str:
    status = session["status"]
    if status in ("queued", "running") and session.get("bank_count"):
        return (f"Generando preguntas adicionales. {session['bank_count']} de {session['slots_total']} preguntas "
                "ya están listas del banco de preguntas.")
    if status in STATUS_ES:
        return STATUS_ES[status]
    reason = STOP_ES.get(session["stop_reason"] or "", STOP_ES["internal_error"])
    if status == "partial":
        return f"{reason} Se prepararon {available} de {session['slots_total']} preguntas; puede practicar con ellas."
    return f"{reason} No se pudo preparar ninguna pregunta. Intente de nuevo más tarde."


def question_view(row: dict[str, Any]) -> dict[str, Any]:
    item = row["item"]
    view = {"slot": row["slot"], "objective_code": row["objective_code"], "stimulus": item["stimulus"],
            "stem": item["stem"], "options": [{"label": o["label"], "text": o["text"]} for o in item["options"]],
            "answered": row["chosen_label"] is not None}
    if view["answered"]:
        view.update(feedback(row, row["chosen_label"], row["is_correct"]))
    return view


def feedback(row: dict[str, Any], chosen: str, correct: bool) -> dict[str, Any]:
    return {"chosen_label": chosen, "correct": correct, "correct_label": row["item"]["answer_key"],
            "explanation": row["item"]["explanation"]}


def summary(session: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows or any(r["chosen_label"] is None for r in rows):
        return None
    texts = {row["workbook_code"]: row.get("text_es", "") for row in session["allocation"]}
    objectives: dict[str, dict[str, Any]] = {}
    for r in rows:
        objective = objectives.setdefault(r["objective_code"], {
            "code": r["objective_code"], "text_es": texts.get(r["objective_code"], ""), "evidences": {}})
        evidence = objective["evidences"].setdefault(r["evidence_id"], {
            "id": r["evidence_id"], "text_es": r["item"]["source_refs"][0]["excerpt"], "correct": 0, "total": 0})
        evidence["total"] += 1
        evidence["correct"] += int(r["is_correct"])
    correct = sum(1 for r in rows if r["is_correct"])
    return {
        "answered": len(rows), "correct": correct, "incorrect": len(rows) - correct,
        "percentage": round(100 * correct / len(rows)),
        "objectives": [{**o, "evidences": list(o["evidences"].values())} for o in objectives.values()],
    }


def build_practice_router(catalog_dependency: Callable, baseline: str, service: PracticeService,
                          api_error: type[Exception], selection_message: Callable[[Any, str], str]) -> APIRouter:
    router = APIRouter(prefix="/api/practice", tags=["practice"])

    def load(session_id: str) -> tuple[PracticeStore, dict[str, Any]]:
        store = service.get()[0]
        session = store.get(session_id)
        if session is None:
            raise api_error(404, "session_not_found", "No encontramos esta práctica. Configure una nueva.")
        return store, session

    def view(store: PracticeStore, session: dict[str, Any]) -> dict[str, Any]:
        rows = store.items(session["session_id"]) if session["status"] in ("complete", "partial") else []
        texts = {row["workbook_code"]: row.get("text_es", "") for row in session["allocation"]}
        return {
            "session_id": session["session_id"],
            "status": session["status"],
            "cancelled": session.get("cancelled_at") is not None,
            "stop_reason": session["stop_reason"],
            "message_es": message_es(session, len(rows)),
            "subject": session["subject"],
            "difficulty": session["config"]["difficulty"],
            "slots_total": session["slots_total"],
            "slots_done": session["slots_done"],
            "composition": {"bank": session.get("bank_count", 0),
                            "generated": sum(1 for r in rows if r.get("source") == "generated")},
            "objectives": [{"code": row["workbook_code"], "text_es": texts[row["workbook_code"]],
                            "questions": row["questions"]} for row in session["allocation"]],
            "questions": [question_view(r) for r in rows],
            "summary": summary(session, rows),
        }

    @router.post("/sessions", status_code=202)
    def create_session(request: SessionRequest, conn: psycopg.Connection = Depends(catalog_dependency)) -> dict:
        if request.scope is not PracticeScope.SUBJECT_SIMULATION and not request.objective_codes:
            raise api_error(422, "no_objectives", "Seleccione al menos un objetivo.")
        try:
            selection = select_objectives(conn, baseline, request.scope, request.subject,
                                          request.objective_codes or None)
        except SelectionError as exc:
            raise api_error(422, "invalid_selection", selection_message(request.scope, str(exc))) from exc
        plan = allocate(selection.objectives, request.question_count, request.difficulty)
        texts = {o["workbook_code"]: o["text_es"] for o in selection.objectives}
        for row in plan["allocation"]:
            row["text_es"] = texts[row["workbook_code"]]
        config = request.model_dump(mode="json", exclude={"client_request_id", "browser_token"})
        browser_hash = (hashlib.sha256(request.browser_token.encode("ascii")).hexdigest()
                        if request.browser_token else None)
        store, queue, bank = service.get()
        session, created = store.create_or_get(request.client_request_id, baseline, config, plan["allocation"],
                                               browser_hash)
        if created:
            # Fill slots from the validated bank first; generate only what is missing (ADR-014).
            picks = bank.compose(conn, baseline, request.subject, plan["allocation"], browser_hash)
            complete = len(picks) == session["slots_total"]
            session = store.add_bank_items(session["session_id"], list(picks.values()), complete)
            if not complete:
                queue.submit(session["session_id"])
        return {**view(store, session), "created": created}

    @router.get("/sessions/{session_id}")
    def get_session(session_id: str = SESSION_ID) -> dict:
        store, session = load(session_id)
        return view(store, session)

    @router.post("/sessions/{session_id}/answers")
    def answer(request: AnswerRequest, session_id: str = SESSION_ID) -> dict:
        store, session = load(session_id)
        if session["status"] not in ("complete", "partial"):
            raise api_error(409, "not_ready", "La práctica todavía no está lista.")
        if session.get("cancelled_at") is not None:
            raise api_error(409, "cancelled", "Esta práctica fue cancelada; configure una nueva.")
        rows = store.items(session_id)
        row = next((r for r in rows if r["slot"] == request.slot), None)
        if row is None:
            raise api_error(404, "question_not_found", "Esa pregunta no existe en esta práctica.")
        stored, first = store.answer(session_id, request.slot, request.label,
                                     request.label == row["item"]["answer_key"])
        row = {**row, "chosen_label": stored["chosen_label"], "is_correct": stored["is_correct"]}
        rows = [row if r["slot"] == request.slot else r for r in rows]
        return {"slot": request.slot, **feedback(row, stored["chosen_label"], stored["is_correct"]),
                "already_answered": not first, "summary": summary(session, rows)}

    @router.post("/sessions/{session_id}/cancel")
    def cancel(session_id: str = SESSION_ID) -> dict:
        """Leave a practice early. Idempotent; never starts generation; answers are kept."""
        store, _ = load(session_id)
        outcome = store.cancel(session_id)
        if outcome == "not_ready":
            raise api_error(409, "not_ready", "La práctica todavía no está lista.")
        return {"session_id": session_id, "outcome": outcome,
                "cancelled": outcome in ("cancelled", "already_cancelled")}

    return router
