"""Producción escrita API for the student (T022, ADR-021): levels, stored exercises, drafts, submissions.

Shows only validated exercises already stored in writing.exercise; never generates. The student view
omits evaluation parameters, criteria and rubric descriptors. Typed work is saved as a draft and
submitted once; handwritten (L5) exercises show their official conditions and take no typed answer.
No grading: a submission waits for the tutor.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.writing import contracts
from app.writing.store import WritingStore, word_count

MAX_TEXT = 20000
PENDING_ES = "Pendiente de revisión del tutor"
LEVEL_TEXT_ES = {
    "writing_conventions": "Escribí oraciones cuidando la ortografía, la concordancia y la puntuación.",
    "idea_development": "Escribí un párrafo de introducción con una idea principal y dos ideas que la apoyen.",
    "paragraph_writing": "Escribí párrafos de desarrollo (causas y consecuencias) o un párrafo de conclusión.",
    "guided_composition": "Escribí un texto expositivo de cuatro párrafos con un plan y apoyos.",
    "full_composition": "Escribí a mano un texto expositivo completo, como en la Prueba Nacional.",
}
HANDWRITTEN_ES = ("Este ejercicio se escribe a mano, como en la prueba: en una hoja, con bolígrafo de tinta azul o "
                  "negra (no lápiz) y con un solo tipo de letra. Entregá tu hoja al tutor. No se puede responder "
                  "escribiendo en la computadora, porque la letra también se revisa.")
EXERCISE_ID = re.compile(r"^PE-L[1-5]-[A-Za-z0-9-]{3,60}$")


class DraftRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)


class SubmitRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    client_request_id: str = Field(pattern=r"^[A-Za-z0-9-]{8,64}$")


class WritingService:
    """Store created on first use (the database may be absent when the app is built)."""

    def __init__(self, url_factory: Callable[[], str]):
        self._url_factory = url_factory
        self._lock = threading.Lock()
        self._store: WritingStore | None = None

    def get(self) -> WritingStore:
        with self._lock:
            if self._store is None:
                self._store = WritingStore(self._url_factory())
            return self._store


def _unit_es(unit: str, n: int) -> str:
    return {"sentences": "oración" if n == 1 else "oraciones", "paragraphs": "párrafo" if n == 1 else "párrafos"}[unit]


def requirements_es(deliverable: dict[str, Any], exercise_type: str = "") -> list[str]:
    """Plain Spanish requirements of the deliverable (no rubric content)."""
    if exercise_type == "conventions_editing":
        return ["El texto completo, ya corregido", "Sin cambiar las ideas del texto", "Escrito en la computadora"]
    low, high = deliverable["min"], deliverable["max"]
    amount = f"{low} {_unit_es(deliverable['unit'], low)}" if low == high else \
        f"De {low} a {high} {_unit_es(deliverable['unit'], high)}"
    items = [amount[0].upper() + amount[1:]]
    if "words_target" in deliverable:
        items.append(f"Al menos {deliverable['words_target']} palabras")
    if "time_limit_min" in deliverable:
        items.append(f"Tiempo: {deliverable['time_limit_min']} minutos")
    items.append("Escrito a mano" if deliverable["evidence_mode"] == "handwritten" else "Escrito en la computadora")
    if deliverable.get("materials_es"):
        items.append(deliverable["materials_es"])
    return items


def build_writing_router(service: WritingService, api_error: type[Exception]) -> APIRouter:
    router = APIRouter(prefix="/api/writing", tags=["writing"])

    def state(row: dict[str, Any]) -> str:
        if row.get("submission_id"):
            return "submitted"
        return "draft" if row.get("draft_saved_at") else "new"

    def load(exercise_id: str) -> tuple[WritingStore, dict[str, Any]]:
        if not EXERCISE_ID.match(exercise_id):
            raise api_error(422, "invalid_exercise", "El ejercicio no es válido.")
        store = service.get()
        row = next((r for r in store.exercises() if r["exercise_id"] == exercise_id), None)
        if row is None:
            raise api_error(404, "exercise_not_found", "No encontramos este ejercicio.")
        return store, row

    def submission_view(sub: dict[str, Any] | None) -> dict[str, Any] | None:
        if sub is None:
            return None
        return {"submitted_at": sub["submitted_at"].isoformat(), "word_count": sub["word_count"],
                "status": "pending_review", "status_es": PENDING_ES}

    @router.get("/levels")
    def levels() -> dict[str, Any]:
        counts: dict[str, int] = {}
        for row in service.get().exercises():
            counts[row["level"]] = counts.get(row["level"], 0) + 1
        return {"component_es": "Producción escrita", "subject_es": "Español", "levels": [
            {"code": lv["code"], "ordinal": lv["ordinal"], "label_es": f"Nivel {lv['ordinal']}: {lv['name_es']}",
             "description_es": LEVEL_TEXT_ES[lv["code"]], "exercise_count": counts.get(lv["code"], 0),
             "handwritten": lv["deliverable"]["evidence_modes"][0] == "handwritten"}
            for lv in contracts.levels()["levels"]]}

    @router.get("/levels/{level}/exercises")
    def exercises(level: str) -> dict[str, Any]:
        if level not in {lv["code"] for lv in contracts.levels()["levels"]}:
            raise api_error(404, "level_not_found", "Ese nivel no existe.")
        rows = service.get().exercises(level)
        return {"level": level, "exercises": [
            {"exercise_id": r["exercise_id"], "topic_es": r["record"].get("title_es") or r["record"]["topic_es"],
             "difficulty": r["difficulty"],
             "evidence_mode": r["evidence_mode"], "state": state(r)} for r in rows]}

    @router.get("/exercises/{exercise_id}")
    def exercise(exercise_id: str) -> dict[str, Any]:
        store, row = load(exercise_id)
        submission = store.submission(exercise_id)
        # T024: a submitted answer keeps the exercise revision it answered; otherwise the latest revision.
        revision = submission["exercise_revision"] if submission else row["revision"]
        record = store.record(exercise_id, revision) if submission else row["record"]
        draft = store.draft(exercise_id)
        level = contracts.level(record["level"])
        handwritten = record["deliverable"]["evidence_mode"] == "handwritten"
        return {
            "exercise_id": exercise_id, "level": level["code"],
            "level_label_es": f"Nivel {level['ordinal']}: {level['name_es']}",
            "difficulty": record["difficulty"], "topic_es": record["topic_es"],
            "title_es": record.get("title_es"), "revision": revision,
            # L1 correction exercises start from a copy of the text; L2-L5 start empty (T024).
            "editable_source": record["exercise_type"] == "conventions_editing",
            # T023: the text with deliberate errors; the tutor-only reference correction is never read here.
            "source_text_es": record.get("source_text_es"),
            "communicative_situation_es": record["communicative_situation_es"],
            "suggested_ideas_es": record.get("suggested_ideas_es", []),
            "instructions_es": record["instructions_es"],
            "deliverable": {"description_es": record["deliverable"]["description_es"],
                            "requirements_es": requirements_es(record["deliverable"], record["exercise_type"]),
                            "evidence_mode": record["deliverable"]["evidence_mode"]},
            "handwritten": handwritten, "handwritten_es": HANDWRITTEN_ES if handwritten else None,
            "draft": None if handwritten or draft is None else {"text": draft["text_es"],
                                                                "word_count": draft["word_count"],
                                                                "saved_at": draft["updated_at"].isoformat()},
            "submission": submission_view(submission),
        }

    def typed_only(row: dict[str, Any]) -> None:
        if row["evidence_mode"] != "typed":
            raise api_error(409, "handwritten_only",
                            "Este ejercicio se escribe a mano; entregá tu hoja al tutor.")

    @router.put("/exercises/{exercise_id}/draft")
    def save_draft(exercise_id: str, request: DraftRequest) -> dict[str, Any]:
        store, row = load(exercise_id)
        typed_only(row)
        saved = store.save_draft(exercise_id, request.text)
        if saved is None:
            raise api_error(409, "already_submitted", "Este ejercicio ya fue entregado; no se puede cambiar.")
        return {"word_count": saved["word_count"], "saved_at": saved["updated_at"].isoformat()}

    @router.post("/exercises/{exercise_id}/submit")
    def submit(exercise_id: str, request: SubmitRequest) -> dict[str, Any]:
        store, row = load(exercise_id)
        typed_only(row)
        if word_count(request.text) == 0:
            raise api_error(422, "empty_text", "Escribí tu texto antes de entregarlo.")
        sub, created = store.submit_typed(exercise_id, request.text, request.client_request_id)
        return {"created": created, **submission_view(sub)}

    return router
