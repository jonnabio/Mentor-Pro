"""Producción escrita API for the student (T022, ADR-021): levels, stored exercises, drafts, submissions.

Shows only validated exercises already stored in writing.exercise; never generates. The student view
omits evaluation parameters, criteria and rubric descriptors. Typed work is saved as a draft and
submitted once; handwritten (L5) exercises show their official conditions and take no typed answer.
No grading: a submission waits for the tutor.
T028 (ADR-026): guided compositions (L4) are written in five stages; each section is saved in the draft and
the submission keeps the planning notes apart from the four assembled paragraphs.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable

import psycopg
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.writing import contracts, migrations, progress
from app.writing.store import GUIDED_PARAGRAPHS, GUIDED_SECTIONS, WritingStore, assemble_sections, word_count
from curriculum import db

MAX_TEXT = 20000
PENDING_ES = "Pendiente de revisión del tutor"
REVIEWED_ES = "Revisado por el tutor"
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
# T028: code-owned guidance per stage (no model text, criteria or scores); `plan` is the index of the
# exercise's own paragraph-plan items shown with the stage.
GUIDED_STAGES = (
    {"key": "plan", "title_es": "1. Planificá tu texto", "sections": ["plan"], "plan": [],
     "guidance_es": "Antes de escribir, anotá ideas sobre el tema: por qué es importante, sus causas, sus "
                    "consecuencias y qué se puede hacer. Estas notas son para vos; tu tutor también las verá."},
    {"key": "introduction", "title_es": "2. Escribí la introducción", "sections": ["introduction"], "plan": [0],
     "guidance_es": "Presentá el tema y por qué es importante. Escribí una idea principal y al menos dos ideas "
                    "que la apoyen."},
    {"key": "development", "title_es": "3. Escribí los dos párrafos de desarrollo",
     "sections": ["development_1", "development_2"], "plan": [1, 2],
     "guidance_es": "En el primer párrafo explicá las causas; en el segundo, las consecuencias. Cada párrafo "
                    "tiene su idea principal y al menos dos ideas que la apoyen."},
    {"key": "conclusion", "title_es": "4. Escribí la conclusión", "sections": ["conclusion"], "plan": [3],
     "guidance_es": "Proponé acciones o soluciones y cerrá el texto. No agregués causas ni consecuencias nuevas."},
    {"key": "review", "title_es": "5. Revisá y entregá", "sections": [], "plan": [],
     "guidance_es": "Leé tu texto completo. Revisá la ortografía, la puntuación y que tenga al menos 200 "
                    "palabras. Después de entregarlo no podrás cambiarlo."},
)
SECTION_LABEL_ES = {"plan": "Notas de planificación", "introduction": "Introducción",
                    "development_1": "Desarrollo 1 (causas)", "development_2": "Desarrollo 2 (consecuencias)",
                    "conclusion": "Conclusión"}


class Sections(BaseModel):
    """T028: one text per stage section; the plan is optional, the four paragraphs are required to submit."""
    plan: str = Field(default="", max_length=MAX_TEXT)
    introduction: str = Field(default="", max_length=MAX_TEXT)
    development_1: str = Field(default="", max_length=MAX_TEXT)
    development_2: str = Field(default="", max_length=MAX_TEXT)
    conclusion: str = Field(default="", max_length=MAX_TEXT)


class DraftRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_TEXT)
    sections: Sections | None = None
    # T030: increasing per save (the browser uses a millisecond clock); a delayed older save is ignored.
    client_seq: int | None = Field(default=None, ge=0, le=2**62)


class SubmitRequest(BaseModel):
    text: str = Field(default="", max_length=MAX_TEXT)
    sections: Sections | None = None
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

    def check_schema(self) -> None:
        """Startup guard (T036, ADR-032 PO 1): raise SchemaMigrationRequired when the writing tables predate the
        current migration. A database that cannot be reached is left to the first request (503), as before."""
        try:
            conn = psycopg.connect(self._url_factory(), connect_timeout=5)
        except (psycopg.OperationalError, db.ConfigurationError):
            return
        with conn:
            migrations.refuse_unless_current(conn)


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
        return "draft" if row.get("draft_saved_at") else "new"  # "submitted" covers pending and reviewed

    def load(exercise_id: str, writable: bool = False) -> tuple[WritingStore, dict[str, Any]]:
        """T029: a quarantined exercise is not offered; it stays readable only when already submitted, and
        never takes a new draft or submission."""
        if not EXERCISE_ID.match(exercise_id):
            raise api_error(422, "invalid_exercise", "El ejercicio no es válido.")
        store = service.get()
        row = next((r for r in store.exercises(eligible_only=False) if r["exercise_id"] == exercise_id), None)
        if row is None or (not row["eligible"] and not row["submission_id"]):
            raise api_error(404, "exercise_not_found", "No encontramos este ejercicio.")
        if writable and not row["eligible"]:
            raise api_error(409, "exercise_unavailable", "Este ejercicio no está disponible por ahora.")
        return store, row

    def submission_view(sub: dict[str, Any] | None, evaluation: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if sub is None:
            return None
        reviewed = evaluation is not None and evaluation["status"] == "completed"
        return {"submitted_at": sub["submitted_at"].isoformat(), "word_count": sub["word_count"],
                "status": "reviewed" if reviewed else "pending_review", "status_es": REVIEWED_ES if reviewed else PENDING_ES}

    def feedback_view(evaluation: dict[str, Any] | None) -> dict[str, Any] | None:
        """T026: the completed tutor evaluation as the student sees it (never the reference correction)."""
        if evaluation is None or evaluation["status"] != "completed":
            return None
        record, criteria = evaluation["record"], contracts.criteria()
        scores = []
        for s in record["criterion_scores"]:
            item = {"statement_es": criteria[s["criterion"]]["statement_es"], "status": s["status"]}
            if s["status"] == "scored":
                item.update(points=s["points"], max_points=4,
                            descriptor_es=criteria[s["criterion"]]["descriptors_es"][s["points"]])
            else:
                item["note_es"] = "No evaluable en un texto escrito en la computadora (se revisa la letra a mano)."
            scores.append(item)
        feedback = record["feedback_es"]
        return {"evaluated_at": record["evaluated_at"], "scores": scores, "strengths_es": feedback["strengths"],
                "improvements_es": feedback["improvements"], "next_step_es": feedback.get("next_step")}

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

    @router.get("/progress")
    def writing_progress() -> dict[str, Any]:
        """T027 (ADR-025): Producción escrita in "Mi progreso"; scores only from completed tutor evaluations."""
        return progress.summary(*service.get().progress_inputs())

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
        evaluation = store.evaluation_for(submission["submission_id"]) if submission else None
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
                                                                "sections": draft.get("sections"),
                                                                "saved_at": draft["updated_at"].isoformat(),
                                                                "client_seq": draft.get("client_seq")},
            # T028: five-stage guided composition; the plan items are the exercise's own scaffolding.
            "guided": None if record["exercise_type"] != "guided_composition" else {
                "stages": [{**{k: v for k, v in st.items() if k != "plan"},
                            "plan_es": [record.get("scaffolding_es", [])[i] for i in st["plan"]
                                        if i < len(record.get("scaffolding_es", []))]} for st in GUIDED_STAGES],
                "section_labels_es": SECTION_LABEL_ES, "paragraphs": list(GUIDED_PARAGRAPHS),
                "sections": list(GUIDED_SECTIONS)},
            "submission": submission_view(submission, evaluation),
            "feedback": feedback_view(evaluation),
        }

    def guided(row: dict[str, Any]) -> bool:
        return row["record"]["exercise_type"] == "guided_composition"

    def guided_sections(row: dict[str, Any], sections: Sections | None) -> dict[str, str]:
        if sections is None:
            raise api_error(422, "sections_required", "Este ejercicio se escribe por partes.")
        return sections.model_dump()

    def typed_only(row: dict[str, Any]) -> None:
        if row["evidence_mode"] != "typed":
            raise api_error(409, "handwritten_only",
                            "Este ejercicio se escribe a mano; entregá tu hoja al tutor.")

    @router.put("/exercises/{exercise_id}/draft")
    def save_draft(exercise_id: str, request: DraftRequest) -> dict[str, Any]:
        try:
            store, row = load(exercise_id, writable=True)
        except psycopg.Error:
            raise api_error(503, "save_failed", "No se pudo guardar el borrador. Intentá de nuevo.") from None
        typed_only(row)
        try:
            if guided(row):
                parts = guided_sections(row, request.sections)
                saved = store.save_draft(exercise_id, assemble_sections(parts), parts, request.client_seq)
            else:
                saved = store.save_draft(exercise_id, request.text, client_seq=request.client_seq)
        except psycopg.Error:
            # T030: nothing was written; the earlier draft stays as it was and the browser keeps the text.
            raise api_error(503, "save_failed", "No se pudo guardar el borrador. Intentá de nuevo.") from None
        if saved is None:
            raise api_error(409, "already_submitted", "Este ejercicio ya fue entregado; no se puede cambiar.")
        return {"word_count": saved["word_count"], "saved_at": saved["updated_at"].isoformat(),
                "applied": saved["applied"], "client_seq": saved["client_seq"]}

    @router.post("/exercises/{exercise_id}/submit")
    def submit(exercise_id: str, request: SubmitRequest) -> dict[str, Any]:
        store, row = load(exercise_id, writable=True)
        typed_only(row)
        parts = None
        if guided(row):
            parts = guided_sections(row, request.sections)
            existing = store.submission(exercise_id)
            if existing is None:  # a repeated request returns the first submission below
                missing = [SECTION_LABEL_ES[k] for k in GUIDED_PARAGRAPHS if not parts[k].strip()]
                if missing:
                    raise api_error(422, "missing_sections", f"Falta escribir: {', '.join(missing)}.")
                split = [SECTION_LABEL_ES[k] for k in GUIDED_PARAGRAPHS if re.search(r"\n\s*\n", parts[k].strip())]
                if split:
                    raise api_error(422, "blank_line_in_paragraph", "Cada párrafo va en su propio cuadro, sin "
                                    f"líneas en blanco: revisá {', '.join(split)}.")
            text = assemble_sections(parts)
        else:
            text = request.text
        if word_count(text) == 0:
            raise api_error(422, "empty_text", "Escribí tu texto antes de entregarlo.")
        sub, created = store.submit_typed(exercise_id, text, request.client_request_id, parts)
        return {"created": created, **submission_view(sub, store.evaluation_for(sub["submission_id"]))}

    return router
