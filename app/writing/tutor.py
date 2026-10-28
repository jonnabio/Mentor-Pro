"""Tutor review of Producción escrita submissions (T026, ADR-024). Human evaluation only; no AI grading.

Local tutor boundary (not authentication): the router exists only when a tutor token is configured
(MENTOR_PRO_TUTOR_TOKEN, at least 16 characters), and every request must come from a loopback address and
carry that token in the X-Tutor-Token header. Student endpoints never read tutor data. See ADR-024 for the
limitations of this boundary.

Scores use the official 0-4 descriptors of curriculum/writing/MEP-RUBRICA-PE-2026.json, referenced as
`<rubric>#<criterion>@<points>`. EE19 and EE20 are recorded as not evaluable for typed submissions. A
partial evaluation can be saved and resumed; completion needs every evaluable criterion scored and locks
the evaluation. No examination grade is computed. T028 (ADR-026): guided compositions also show the
planning notes and each paragraph; their optional EE07-EE18 may be scored and are never required.
T038 (ADR-032): a revision submission ("Mejora") shows the previous attempt's response and its completed
evaluation; the new evaluation attaches to the revision only and the earlier one stays locked.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from app.writing import contracts
from app.writing.routes import SECTION_LABEL_ES, WritingService
from app.writing.store import GUIDED_SECTIONS
from app.writing.store import EvaluationLocked, InvalidRecord

LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
MIN_TOKEN = 16


class EvaluationRequest(BaseModel):
    scores: dict[str, int | None] = Field(default_factory=dict)
    strengths: list[str] = Field(default_factory=list, max_length=10)
    improvements: list[str] = Field(default_factory=list, max_length=10)
    next_step: str | None = Field(default=None, max_length=500)
    complete: bool = False


def _level_label(record: dict[str, Any]) -> str:
    level = contracts.level(record["level"])
    return f"Nivel {level['ordinal']}: {level['name_es']}"


def build_tutor_router(service: WritingService, api_error: type[Exception], token: str,
                       allowed_hosts: frozenset[str] = LOOPBACK) -> APIRouter:
    if len(token) < MIN_TOKEN:
        raise ValueError(f"tutor token must have at least {MIN_TOKEN} characters")

    def tutor_only(request: Request, x_tutor_token: str = Header(default="")) -> None:
        host = request.client.host if request.client else ""
        if host not in allowed_hosts or not hmac.compare_digest(x_tutor_token.encode(), token.encode()):
            raise api_error(403, "tutor_only", "Acceso solo para el tutor.")

    router = APIRouter(prefix="/api/tutor", tags=["tutor"], dependencies=[Depends(tutor_only)])

    def load(submission_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        store = service.get()
        submission = store.submission_by_id(submission_id)
        if submission is None:
            raise api_error(404, "submission_not_found", "No encontramos esta entrega.")
        record = store.record(submission["exercise_id"], submission["exercise_revision"])
        return store, submission, record

    def applicability(record: dict[str, Any], submission: dict[str, Any]) -> dict[str, str]:
        typed = submission["evidence_mode"] == "typed"
        return {c: ("not_evaluable" if c in contracts.handwritten_criteria() and typed else "scored")
                for c in record["target_criteria"]}

    def optional(record: dict[str, Any]) -> set[str]:
        return contracts.optional_criteria(record)

    def sections_view(sub: dict[str, Any]) -> list[dict[str, str]] | None:
        if not sub.get("sections"):
            return None
        return [{"key": k, "label_es": SECTION_LABEL_ES[k], "text_es": sub["sections"].get(k, "")}
                for k in GUIDED_SECTIONS]

    def previous_view(store: Any, attempt: dict[str, Any]) -> dict[str, Any] | None:
        """T038: the response this revision improves and its completed evaluation (read-only)."""
        if not attempt["previous_attempt_id"]:
            return None
        sub = store.attempt_submission(attempt["previous_attempt_id"])
        evaluation = store.evaluation_for(sub["submission_id"])
        criteria = contracts.criteria()
        scores = [{"criterion": s["criterion"], "statement_es": criteria[s["criterion"]]["statement_es"],
                   "status": s["status"], "points": s.get("points"),
                   "descriptor_es": criteria[s["criterion"]]["descriptors_es"][s["points"]]
                   if s["status"] == "scored" else None}
                  for s in evaluation["record"]["criterion_scores"]] if evaluation else []
        return {"submission_id": sub["submission_id"], "submitted_at": sub["submitted_at"].isoformat(),
                "student_text": sub["text_es"], "sections": sections_view(sub),
                "evaluation": None if evaluation is None else {
                    "status": evaluation["status"], "evaluated_at": evaluation["record"].get("evaluated_at"),
                    "scores": scores, "feedback_es": evaluation["record"]["feedback_es"]}}

    @router.get("/queue")
    def queue() -> dict[str, Any]:
        store = service.get()
        items = []
        for row in store.tutor_queue():
            record = store.record(row["exercise_id"], row["exercise_revision"])
            items.append({"submission_id": row["submission_id"], "exercise_id": row["exercise_id"],
                          "title_es": record.get("title_es") or record["topic_es"], "level_es": _level_label(record),
                          "submitted_at": row["submitted_at"].isoformat(), "status": row["status"],
                          "target_criteria": record["target_criteria"], "evidence_mode": row["evidence_mode"],
                          "attempt_number": row["attempt_number"]})
        return {"submissions": items}

    @router.get("/submissions/{submission_id}")
    def submission(submission_id: str) -> dict[str, Any]:
        store, sub, record = load(submission_id)
        criteria = contracts.criteria()
        kinds = applicability(record, sub)
        reference = store.reference_correction(sub["exercise_id"], sub["exercise_revision"])
        evaluation = store.evaluation_for(submission_id)
        attempt = store.attempt(sub["attempt_id"])
        return {
            "submission_id": submission_id, "exercise_id": sub["exercise_id"],
            "exercise_revision": sub["exercise_revision"], "submitted_at": sub["submitted_at"].isoformat(),
            "evidence_mode": sub["evidence_mode"], "student_text": sub["text_es"],
            "sections": sections_view(sub),
            "attempt_number": attempt["attempt_number"], "previous": previous_view(store, attempt),
            "exercise": {"title_es": record.get("title_es"), "topic_es": record["topic_es"],
                         "level_es": _level_label(record), "exercise_type": record["exercise_type"],
                         "communicative_situation_es": record["communicative_situation_es"],
                         "instructions_es": record["instructions_es"],
                         "deliverable_es": record["deliverable"]["description_es"],
                         "source_text_es": record.get("source_text_es"),
                         "scaffolding_es": record.get("scaffolding_es", [])},
            "reference": None if reference is None else {
                "corrected_text_es": reference["corrected_text_es"], "corrections": reference["corrections"],
                "ambiguities_es": reference["ambiguities_es"], "revision": reference["revision"]},
            "rubric": {"rubric_id": contracts.rubric()["rubric_id"],
                       "rubric_sha256": contracts.rubric()["source"]["file_sha256"],
                       "counting_note_es": contracts.rubric()["counting_note_es"]},
            "criteria": [{"code": code, "statement_es": criteria[code]["statement_es"],
                          "descriptors_es": criteria[code]["descriptors_es"], "applicability": kinds[code],
                          "optional": code in optional(record)}
                         for code in record["target_criteria"]],
            "evaluation": None if evaluation is None else {
                "status": evaluation["status"], "record": evaluation["record"],
                "updated_at": evaluation["updated_at"].isoformat()},
        }

    @router.put("/submissions/{submission_id}/evaluation")
    def save(submission_id: str, request: EvaluationRequest) -> dict[str, Any]:
        store, sub, record = load(submission_id)
        kinds = applicability(record, sub)
        optional_codes = optional(record)
        unknown = sorted(set(request.scores) - set(kinds))
        if unknown:
            raise api_error(422, "unknown_criteria", f"Criterios que no corresponden al ejercicio: {unknown}.")
        scores = []
        for code, kind in kinds.items():
            points = request.scores.get(code)
            if kind == "not_evaluable":
                if points is not None:
                    raise api_error(422, "handwriting_not_evaluable",
                                    f"{code} requiere evidencia manuscrita; en un texto digitado es «No evaluable».")
                scores.append({"criterion": code, "status": "not_evaluable",
                               "not_evaluable_reason": "handwritten_evidence_required"})
            elif points is None and code in optional_codes:
                continue  # T028: an optional criterion left unscored is not part of the evaluation
            elif points is None:
                scores.append({"criterion": code, "status": "pending"})
            elif 0 <= points <= 4:
                scores.append({"criterion": code, "status": "scored", "points": points})
            else:
                raise api_error(422, "invalid_points", "Cada criterio se califica de 0 a 4.")
        if request.complete and any(s["status"] == "pending" for s in scores):
            raise api_error(422, "incomplete", "Calificá todos los criterios evaluables antes de completar.")
        clean = lambda items: [x.strip() for x in items if x and x.strip()]  # noqa: E731
        existing = store.evaluation_for(submission_id)
        now = datetime.now(timezone.utc).isoformat()
        evaluation = {
            "schema_version": "1.0",
            "evaluation_id": existing["evaluation_id"] if existing else f"EV-{secrets.token_hex(8)}",
            "exercise_id": sub["exercise_id"],
            "submission": {"submission_id": submission_id, "evidence_mode": sub["evidence_mode"],
                           "word_count": sub["word_count"] or 0, "paragraph_count": sub["paragraph_count"] or 0,
                           "submitted_at": sub["submitted_at"].isoformat()},
            "evaluator": {"kind": "human", "role": "tutor"},
            "status": "completed" if request.complete else "in_progress",
            "rubric_id": record["evaluation"]["rubric_id"], "rubric_sha256": record["evaluation"]["rubric_sha256"],
            "criterion_scores": scores,
            "feedback_es": {"strengths": clean(request.strengths), "improvements": clean(request.improvements),
                            **({"next_step": request.next_step.strip()} if request.next_step and
                               request.next_step.strip() else {})},
        }
        if request.complete:
            evaluation["evaluated_at"] = now
        try:
            store.save_evaluation(evaluation, record, sub["exercise_revision"])
        except EvaluationLocked:
            raise api_error(409, "evaluation_completed", "Esta evaluación ya fue completada y no se puede cambiar.") \
                from None
        except InvalidRecord as exc:
            raise api_error(422, "invalid_evaluation", "; ".join(exc.problems)) from None
        return {"status": evaluation["status"], "evaluated_at": evaluation.get("evaluated_at")}

    return router
