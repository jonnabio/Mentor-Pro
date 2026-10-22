"""Mentor Pro practice-configuration API and static UI (T003).

Reads the PostgreSQL curriculum catalog through `curriculum.catalog`
(read-only). Only multiple-choice objectives are offered; the Español `EE`
written-production criteria are never selectable.

Run:
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.allocation import allocate
from app.dev_routes import LlmFactory, build_dev_router
from curriculum import db
from curriculum.catalog import PracticeScope, SelectionError, list_objectives, open_catalog, select_objectives

BASELINE_VERSION = os.environ.get("CURRICULUM_BASELINE", "PNE2026-SUM-v1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
SUBJECTS = (
    ("espanol", "Español"),
    ("matematicas", "Matemáticas"),
    ("ciencias", "Ciencias"),
    ("estudios_sociales", "Estudios Sociales"),
)
SUBJECT_CODES = {code for code, _ in SUBJECTS}
GROUNDING_NOTICE_ES = (
    "Contenido basado en el catálogo curricular aprobado para Mentor Pro "
    "(PNE2026-SUM-v1.0). No es material oficial del MEP."
)


class ApiError(Exception):
    """An error with a stable code and a student-facing Spanish message."""

    def __init__(self, status: int, code: str, message_es: str):
        super().__init__(code)
        self.status, self.code, self.message_es = status, code, message_es


class PracticeConfig(BaseModel):
    subject: str
    scope: PracticeScope
    objective_codes: list[str] = Field(default_factory=list, max_length=100)
    difficulty: Literal["easy", "medium", "hard", "mixed"]
    question_count: Literal[5, 10, 20, 30]


def create_app(database_url: str | None = None, schema: str = db.DEFAULT_SCHEMA,
               baseline: str = BASELINE_VERSION, dev_endpoints: bool | None = None,
               llm_factory: LlmFactory | None = None) -> FastAPI:
    app = FastAPI(title="Mentor Pro", version="0.3.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.catalog_target = (database_url, schema)

    def catalog() -> Iterator[psycopg.Connection]:
        conn = open_catalog(database_url or db.database_url(), schema)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message_es": exc.message_es})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = sorted({str(e["loc"][-1]) for e in exc.errors()})
        return JSONResponse(status_code=422, content={
            "error": "invalid_request", "fields": fields,
            "message_es": "La configuración no es válida. Revise las opciones seleccionadas.",
        })

    def require_subject(subject: str) -> str:
        if subject not in SUBJECT_CODES:
            raise ApiError(422, "unknown_subject", "La materia seleccionada no existe.")
        return subject

    @app.get("/api/subjects")
    def get_subjects(conn: psycopg.Connection = Depends(catalog)) -> dict:
        subjects = [{"code": code, "name_es": name,
                     "objective_count": len(list_objectives(conn, baseline, code))}
                    for code, name in SUBJECTS]
        return {"baseline_version": baseline, "notice_es": GROUNDING_NOTICE_ES, "subjects": subjects}

    @app.get("/api/objectives")
    def get_objectives(subject: str = Query(...), conn: psycopg.Connection = Depends(catalog)) -> dict:
        require_subject(subject)
        objectives = [{
            "code": o["workbook_code"],
            "text_es": o["text_es"],
            "block_name_es": o["block_name_es"],
            "numbering_es": o["numbering_es"],
            "evidence_count": len(o["evidences"]),
            "planned_items": o["planned_items"],
        } for o in list_objectives(conn, baseline, subject)]
        return {"baseline_version": baseline, "subject": subject, "objectives": objectives}

    @app.post("/api/practice/configure")
    def configure(config: PracticeConfig, conn: psycopg.Connection = Depends(catalog)) -> dict:
        require_subject(config.subject)
        if config.scope is not PracticeScope.SUBJECT_SIMULATION and not config.objective_codes:
            raise ApiError(422, "no_objectives", "Seleccione al menos un objetivo.")
        try:
            selection = select_objectives(conn, baseline, config.scope, config.subject,
                                          config.objective_codes or None)
        except SelectionError as exc:
            raise ApiError(422, "invalid_selection", _selection_message(config.scope, str(exc))) from exc

        result = allocate(selection.objectives, config.question_count, config.difficulty)
        texts = {o["workbook_code"]: o["text_es"] for o in selection.objectives}
        for row in result["allocation"]:
            row["text_es"] = texts[row["workbook_code"]]
        return {
            "baseline_version": baseline,
            "subject": config.subject,
            "scope": config.scope.value,
            "difficulty": config.difficulty,
            "question_count": config.question_count,
            "objectives_selected": len(selection.objectives),
            "notice_es": GROUNDING_NOTICE_ES,
            **result,
        }

    if dev_endpoints is None:
        dev_endpoints = os.environ.get("MENTOR_PRO_DEV_ENDPOINTS", "").lower() in ("1", "true", "yes")
    if dev_endpoints:
        app.include_router(build_dev_router(catalog, baseline, llm_factory or _default_llm_factory(database_url),
                                            ApiError))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def _default_llm_factory(database_url: str | None) -> LlmFactory:
    """Real OpenRouter client with PostgreSQL usage and generation stores."""
    def factory():
        from app.generation.store import GenerationStore
        from app.llm.client import OpenRouterClient
        from app.llm.settings import LlmSettings
        from app.llm.usage import UsageStore

        url = database_url or db.database_url()
        return OpenRouterClient(LlmSettings.load()), UsageStore(url), GenerationStore(url)
    return factory


def _selection_message(scope: PracticeScope, detail: str) -> str:
    if "exactly one" in detail:
        return "Para practicar un objetivo, seleccione exactamente uno."
    if "two or more" in detail:
        return "Para practicar varios objetivos, seleccione al menos dos."
    if "duplicate" in detail:
        return "Hay objetivos repetidos en la selección."
    if "cannot be practised" in detail:
        return "Los criterios de producción escrita no se practican con preguntas de selección."
    return "Uno o más objetivos no pertenecen a la materia seleccionada."


app = create_app()
