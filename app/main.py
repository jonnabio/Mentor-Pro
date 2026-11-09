"""Mentor Pro practice API and static UI (T003 configuration, T010 student practice).

Reads the PostgreSQL curriculum catalog through `curriculum.catalog`
(read-only). Only multiple-choice objectives are offered; the Español `EE`
written-production criteria are never selectable.

Run:
    .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.allocation import QUESTION_COUNTS, QuestionCount, allocate
from app.dev_routes import LlmFactory, build_dev_router
from app.practice.jobs import SetRunner, live_set_runner
from app.practice.mastery import NOTICE_ES, STATUS_LABELS_ES, STATUSES, Thresholds, subject_dashboard
from app.practice.routes import PracticeService, build_practice_router
from app.practice.tutor_results import PracticeResults, build_practice_results_router
from app.writing.migrations import SchemaMigrationRequired
from app.writing.routes import WritingService, build_writing_router
from app.writing.tutor import LOOPBACK, build_tutor_router
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

    def __init__(self, status: int, code: str, message_es: str, details: dict | None = None):
        super().__init__(code)
        self.status, self.code, self.message_es, self.details = status, code, message_es, details or {}


class PracticeConfig(BaseModel):
    subject: str
    scope: PracticeScope
    objective_codes: list[str] = Field(default_factory=list, max_length=100)
    difficulty: Literal["easy", "medium", "hard", "mixed"]
    question_count: QuestionCount


def bank_only_config(value: bool | dict[str, tuple[int, ...]] | None) -> dict[str, tuple[int, ...]]:
    """Subject -> permitted bank-only sizes (T057). Empty means bank-only is off everywhere.

    From the environment (value None): MENTOR_PRO_BANK_ONLY_SUBJECTS, e.g. "matematicas" or "matematicas:5,10"
    (size 5 when none is given), takes precedence; otherwise the T049 MENTOR_PRO_BANK_ONLY_ENABLED=true turns on
    every subject and size. An unknown subject or size refuses to start instead of being ignored.
    """
    if isinstance(value, bool):
        return {code: QUESTION_COUNTS for code in SUBJECT_CODES} if value else {}
    if value is not None:
        return dict(value)
    spec = os.environ.get("MENTOR_PRO_BANK_ONLY_SUBJECTS", "").strip()
    if not spec:
        enabled = os.environ.get("MENTOR_PRO_BANK_ONLY_ENABLED", "").lower() in ("1", "true", "yes")
        return {code: QUESTION_COUNTS for code in SUBJECT_CODES} if enabled else {}
    out: dict[str, tuple[int, ...]] = {}
    for entry in filter(None, (e.strip() for e in spec.split(";"))):
        code, colon, sizes = entry.partition(":")
        code = code.strip()
        try:
            counts = tuple(sorted({int(n) for n in sizes.split(",")})) if colon else (5,)
        except ValueError:
            counts = ()
        if code not in SUBJECT_CODES or code in out or not counts or not set(counts) <= set(QUESTION_COUNTS):
            raise ValueError(f"MENTOR_PRO_BANK_ONLY_SUBJECTS: invalid entry {entry!r}")
        out[code] = counts
    return out


def create_app(database_url: str | None = None, schema: str = db.DEFAULT_SCHEMA,
               baseline: str = BASELINE_VERSION, dev_endpoints: bool | None = None,
               llm_factory: LlmFactory | None = None, practice_runner: SetRunner | None = None,
               tutor_token: str | None = None, tutor_hosts: frozenset[str] = LOOPBACK,
               bank_only: bool | dict[str, tuple[int, ...]] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.writing.check_schema()  # T036: refuse to start on an unmigrated writing schema
        yield

    app = FastAPI(title="Mentor Pro", version="0.4.0", docs_url="/api/docs", openapi_url="/api/openapi.json",
                  lifespan=lifespan)
    app.state.catalog_target = (database_url, schema)
    # T049/T057: bank-only practice (ADR-035) per subject, off unless explicitly configured.
    bank_only_sizes = bank_only_config(bank_only)
    every_subject = all(bank_only_sizes.get(code) == QUESTION_COUNTS for code in SUBJECT_CODES)

    def catalog() -> Iterator[psycopg.Connection]:
        conn = open_catalog(database_url or db.database_url(), schema)
        try:
            yield conn
        finally:
            conn.close()

    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status, content={**exc.details, "error": exc.code, "message_es": exc.message_es})

    @app.exception_handler(SchemaMigrationRequired)
    async def schema_migration_required(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={
            "error": "schema_migration_required", "message_es": "La aplicación está en mantenimiento."})

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
                     "objective_count": len(list_objectives(conn, baseline, code)),
                     "practice": {"bank_only": code in bank_only_sizes,
                                  "question_counts": list(bank_only_sizes.get(code, (5,)))}}
                    for code, name in SUBJECTS]
        # Top-level `practice` keeps the T049 meaning: on only when every subject is bank-only with every size.
        return {"baseline_version": baseline, "notice_es": GROUNDING_NOTICE_ES, "subjects": subjects,
                "practice": {"bank_only": every_subject,
                             "question_counts": list(QUESTION_COUNTS) if every_subject else [5]}}

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

    @app.get("/api/dashboard")
    def dashboard(conn: psycopg.Connection = Depends(catalog)) -> dict:
        """Learning status for every selectable objective, from recorded answers (T014)."""
        thresholds = Thresholds.from_env()
        app.state.practice.get()  # practice tables, including session_classification (ADR-017), exist
        subjects = []
        for code, name in SUBJECTS:
            summary = subject_dashboard(conn, baseline, code, list_objectives(conn, baseline, code), thresholds)
            subjects.append({"name_es": name, **summary})
        return {"baseline_version": baseline, "notice_es": NOTICE_ES,
                "statuses": [{"code": s, "label_es": STATUS_LABELS_ES[s]} for s in STATUSES],
                "min_distinct_questions": thresholds.min_distinct, "subjects": subjects}

    def runner_factory() -> SetRunner:
        if practice_runner is not None:
            return practice_runner
        return live_set_runner(llm_factory or _default_llm_factory(database_url),
                               lambda: open_catalog(database_url or db.database_url(), schema))

    app.state.practice = PracticeService(lambda: database_url or db.database_url(), runner_factory)
    app.include_router(build_practice_router(catalog, baseline, app.state.practice, ApiError, _selection_message,
                                             bank_only_sizes))
    # T022: Producción escrita (Español) reads stored exercises only; it never generates.
    app.state.writing = WritingService(lambda: database_url or db.database_url())
    app.include_router(build_writing_router(app.state.writing, ApiError))
    # T026: tutor review exists only with a configured token (ADR-024); it is never linked from the student UI.
    tutor_token = tutor_token if tutor_token is not None else (db.setting("MENTOR_PRO_TUTOR_TOKEN") or "")
    if tutor_token:
        app.include_router(build_tutor_router(app.state.writing, ApiError, tutor_token, tutor_hosts))
        # T060: read-only practice results and Question Bank analytics behind the same tutor check.
        app.include_router(build_practice_results_router(
            PracticeResults(lambda: database_url or db.database_url()), ApiError, tutor_token, tutor_hosts,
            SUBJECTS))

        @app.get("/tutor", include_in_schema=False)
        def tutor_page() -> FileResponse:
            return FileResponse(STATIC_DIR / "tutor.html")

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
