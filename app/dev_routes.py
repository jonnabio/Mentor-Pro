"""Development-only endpoints (T006). Mounted only when MENTOR_PRO_DEV_ENDPOINTS=true.

`POST /api/dev/questions/generate` generates and validates one question and
returns everything for inspection, including the key. Student-facing routes
never return keys; `student_view` shows what a student would see.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.generation import prompts
from app.generation.grounding import GroundingError, build_grounding
from app.generation.pipeline import generate_one, student_view
from app.llm.settings import LlmConfigurationError

# factory() -> (OpenRouterClient, usage store, generation store); injected for tests.
LlmFactory = Callable[[], tuple[Any, Any, Any]]


class GenerateRequest(BaseModel):
    subject: Literal["espanol", "matematicas", "ciencias", "estudios_sociales"]
    objective_code: str = Field(pattern=r"^(EL|M|C|ES)[0-9]{2}$")
    difficulty: Literal["easy", "medium", "hard"]
    evidence_ordinal: int | None = Field(default=None, ge=1, le=30)


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

    return router
