"""Development-only endpoints (T006, T007). Mounted only when MENTOR_PRO_DEV_ENDPOINTS=true.

`POST /api/dev/questions/generate` generates and validates one question and
`POST /api/dev/practice-sets/generate` a practice set (ADR-011); both return
everything for inspection, including keys. Student-facing routes never return
keys; `student_view` shows what a student would see.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.allocation import allocate
from app.generation import prompts
from app.generation.grounding import GroundingError, build_grounding
from app.generation.pipeline import generate_one, student_view
from app.generation.practice_set import SetLimits, coverage, generate_set
from app.llm.settings import LlmConfigurationError
from curriculum.catalog import PracticeScope, SelectionError, select_objectives

# factory() -> (OpenRouterClient, usage store, generation store); injected for tests.
LlmFactory = Callable[[], tuple[Any, Any, Any]]


class GenerateRequest(BaseModel):
    subject: Literal["espanol", "matematicas", "ciencias", "estudios_sociales"]
    objective_code: str = Field(pattern=r"^(EL|M|C|ES)[0-9]{2}$")
    difficulty: Literal["easy", "medium", "hard"]
    evidence_ordinal: int | None = Field(default=None, ge=1, le=30)


class PracticeSetRequest(BaseModel):
    """Same shape as the practice configuration; T007 allows only 5 questions."""
    subject: Literal["espanol", "matematicas", "ciencias", "estudios_sociales"]
    scope: PracticeScope
    objective_codes: list[str] = Field(default_factory=list, max_length=100)
    difficulty: Literal["easy", "medium", "hard", "mixed"]
    question_count: Literal[5]


def build_dev_router(catalog_dependency: Callable, baseline: str, llm_factory: LlmFactory,
                     api_error: type[Exception]) -> APIRouter:
    router = APIRouter(prefix="/api/dev", tags=["development only"])

    @router.post("/questions/generate")
    def generate(request: GenerateRequest, conn: psycopg.Connection = Depends(catalog_dependency)) -> dict:
        try:
            bundle = build_grounding(conn, baseline, request.subject, request.objective_code,
                                     request.evidence_ordinal)
        except GroundingError as exc:
            raise api_error(422, "not_groundable", "El objetivo o la evidencia no se pueden usar.") from exc

        try:
            client, usage_store, generation_store = llm_factory()
        except LlmConfigurationError as exc:
            raise api_error(503, "llm_not_configured", "El servicio de generación no está configurado.") from exc
        try:
            bank = generation_store.recent_stems(bundle.evidence["id"])
            outcome = generate_one(client, usage_store, bundle, request.difficulty, bank=bank)
        finally:
            client.close()
        generation_store.add(outcome, baseline, request.difficulty, prompts.GENERATION_PROMPT_VERSION)

        response: dict[str, Any] = {
            "status": outcome.status,
            "request_id": outcome.request_id,
            "objective_code": outcome.objective_code,
            "evidence_id": outcome.evidence_id,
            "evidence_text_es": bundle.evidence["text_es"],
            "usage": outcome.summary(),
            "reasons": outcome.reasons,
            "validation": outcome.validation,
        }
        if outcome.status == "accepted":
            response["item"] = outcome.item
            response["student_view"] = student_view(outcome.item)
        else:
            # Rejected items are shown only as a labelled rejected draft, never as a valid question.
            response["rejected_draft"] = outcome.item
        return response

    @router.post("/practice-sets/generate")
    def generate_practice_set(request: PracticeSetRequest,
                              conn: psycopg.Connection = Depends(catalog_dependency)) -> dict:
        try:
            selection = select_objectives(conn, baseline, request.scope, request.subject,
                                          request.objective_codes or None)
        except SelectionError as exc:
            raise api_error(422, "invalid_selection", "La selección de objetivos no es válida.") from exc
        plan = allocate(selection.objectives, request.question_count, request.difficulty)
        limits = SetLimits.from_env()

        try:
            client, usage_store, generation_store = llm_factory()
        except LlmConfigurationError as exc:
            raise api_error(503, "llm_not_configured", "El servicio de generación no está configurado.") from exc
        try:
            result = generate_set(conn, client, usage_store, generation_store, baseline, request.subject,
                                  plan["allocation"], limits)
        except GroundingError as exc:
            raise api_error(422, "not_groundable", "El objetivo o la evidencia no se pueden usar.") from exc
        finally:
            client.close()
        generation_store.add_set(result, baseline, request.model_dump(mode="json"), plan["allocation"],
                                 asdict(limits))

        return {
            "practice_set_id": result.practice_set_id,
            "status": result.status,
            "stop_reason": result.stop_reason,
            "limits": asdict(limits),
            "summary": result.summary(),
            "coverage": coverage(plan["allocation"], result),
            "uncovered_codes": plan["uncovered_codes"],
            "rejections": result.rejection_reasons(),
            "slots": [{
                "slot": s.slot, "objective_code": s.objective_code, "evidence_id": s.evidence_id,
                "difficulty": s.difficulty, "status": s.status, "request_id": s.request_id,
                "requests": s.requests, "item": s.item,
                "student_view": student_view(s.item) if s.item else None,
            } for s in result.slots],
        }

    return router
