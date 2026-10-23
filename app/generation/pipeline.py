"""Generate and validate exactly one question (T006, ADR-010).

Flow: grounding → generation (≤ 2 attempts) → deterministic checker →
blind independent solve (unless math proven) → rubric → verdict.
Only verdict `accept` yields a valid item; everything else is returned as
rejected with reasons, never presented as valid.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.generation import prompts
from app.generation.grounding import GroundingBundle
from app.generation.parsing import OutputError, extract_json, model_fields, parse_rubric, parse_solve
from app.generation.validation import CHECKER_VERSION, deterministic_check
from app.llm.budget import BudgetGate
from app.llm.client import OpenRouterClient
from app.llm.router import Store, route

MAX_GENERATION_ATTEMPTS = 2
# Generous limits: free reasoning models spend many tokens before answering.
GENERATION_MAX_TOKENS = 4000
SOLVE_MAX_TOKENS = 2000
RUBRIC_MAX_TOKENS = 3000
SUBJECT_ID = {"espanol": "ESP", "matematicas": "MAT", "ciencias": "CIE", "estudios_sociales": "EST"}


@dataclass
class GenerationOutcome:
    status: str                                # accepted | rejected | unavailable
    request_id: str
    objective_code: str
    evidence_id: str
    item: dict[str, Any] | None = None
    validation: dict[str, Any] | None = None
    reasons: list[str] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        sent = [u for u in self.usage if u["status"] != "budget_blocked"]
        ok = [u for u in sent if u["status"] == "ok"]
        return {
            "calls": len(sent),
            "tokens_in": sum(u["tokens_in"] or 0 for u in sent),
            "tokens_out": sum(u["tokens_out"] or 0 for u in sent),
            # Sum of known costs; cost_complete is False if any successful call has unknown cost.
            "cost_usd": round(sum(u["cost_usd"] or 0 for u in sent), 8),
            "cost_complete": all(u["cost_usd"] is not None for u in ok),
            "models_used": sorted({u["model_used"] for u in sent if u["model_used"]}),
            "latency_ms": sum(u["latency_ms"] for u in sent),
        }


def student_view(item: dict[str, Any]) -> dict[str, Any]:
    """What a student may see before answering: no key, explanation or rationales."""
    return {
        "item_id": item["item_id"],
        "stimulus": item["stimulus"],
        "stem": item["stem"],
        "options": item["options"],
    }


def _item_id(bundle: GroundingBundle, fields: dict[str, Any], request_id: str) -> str:
    # The request ID is part of the digest: D01 skips bank items with the same item_id, so identical
    # content from another request must get a different ID to be caught as a duplicate.
    digest = hashlib.sha256((request_id + repr(sorted(fields.items()))).encode("utf-8")).hexdigest()[:8]
    return f"Q-{bundle.evidence['id']}-{digest}"


def assemble_item(bundle: GroundingBundle, fields: dict[str, Any], difficulty: str, model_requested: str,
                  model_used: str | None, provider: str | None, request_id: str) -> dict[str, Any]:
    """Model-authored fields plus code-owned metadata (IDs, provenance, excerpt, generation)."""
    objective = bundle.objective
    return {
        "schema_version": "1.0",
        "item_id": _item_id(bundle, fields, request_id),
        "subject": bundle.subject,
        "curriculum_ref": {
            "spec_version": "PNE2026",
            "application": "sumativa",
            "bloque_id": objective["block_id"],
            "afirmacion_id": objective["id"],
            "evidencia_id": bundle.evidence["id"],
        },
        "source_refs": [{"record_id": bundle.evidence["id"], "excerpt": bundle.evidence["text_es"]}],
        "grounding_basis": "official" if objective["provenance"] == "official" else "approved_baseline",
        "difficulty": difficulty,
        "language": "es-CR",
        **fields,
        "generation": {
            "model_requested": model_requested,
            "model_used": model_used or model_requested,
            "provider": provider or "unknown",
            "prompt_id": prompts.GENERATION_PROMPT_ID,
            "prompt_version": prompts.GENERATION_PROMPT_VERSION,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "request_id": request_id,
        },
    }


def verdict(det: dict[str, Any], solve: dict[str, Any], rubric: dict[str, int] | None) -> tuple[str, list[str]]:
    """question-quality-review verdict table."""
    reasons = list(det["reasons"])
    if det["deterministic_status"] == "fail":
        return det["verdict"], reasons
    if det["requires_independent_solve"]:
        if not solve.get("performed"):
            return "pending", reasons + ["independent solve unavailable"]
        if not solve.get("agrees_with_key"):
            return "regenerate", reasons + [f"independent solve chose {solve.get('chosen_label') or 'AMBIGUA'}"]
    if rubric is None:
        return "pending", reasons + ["rubric unavailable"]
    low = [k for k, v in rubric.items() if v == 0]
    if low:
        return "regenerate", reasons + [f"rubric 0 for {low}"]
    weak = [k for k, v in rubric.items() if v == 1]
    if weak:
        return "revise", reasons + [f"rubric 1 for {weak}"]
    return "accept", reasons


def generate_one(client: OpenRouterClient, store: Store, bundle: GroundingBundle, difficulty: str,
                 bank: list[dict[str, Any]] | None = None, practice_set_id: str | None = None,
                 gate: BudgetGate | None = None) -> GenerationOutcome:
    request_id = f"req-{uuid.uuid4().hex[:16]}"
    outcome = GenerationOutcome("rejected", request_id, bundle.objective_code, bundle.evidence["id"])
    notes: list[str] = []
    facts = bundle.concept_lines
    avoid_stems = [i["stem"] for i in bank or [] if i and i.get("stem")]
    attempts: list[dict[str, Any]] = []  # every attempt's verdict and reasons, kept in validation

    for number in range(1, MAX_GENERATION_ATTEMPTS + 1):
        messages = prompts.generation_messages(bundle, difficulty, revision_notes=notes, avoid_stems=avoid_stems)
        gen = route(client, store, messages, purpose="generation", max_tokens=GENERATION_MAX_TOKENS,
                    request_id=request_id, practice_set_id=practice_set_id, gate=gate)
        outcome.usage += gen.records
        if gen.status != "ok":
            outcome.status = "unavailable"
            outcome.reasons = [f"generation {gen.status}: {gen.message}"]
            return outcome
        try:
            fields = model_fields(extract_json(gen.content))
        except OutputError as exc:
            notes = [str(exc)]
            outcome.reasons = [f"invalid output: {exc}"]
            attempts.append({"attempt": number, "verdict": "invalid_output", "reasons": outcome.reasons})
            continue

        item = assemble_item(bundle, fields, difficulty, gen.final.model_requested, gen.final.model_used,
                             gen.final.provider, request_id)
        det = deterministic_check(item, bundle.records(), facts, bank)

        solve: dict[str, Any] = {"performed": False}
        rubric: dict[str, int] | None = None
        if det["deterministic_status"] == "pass":
            if det["requires_independent_solve"]:
                solved = route(client, store, prompts.solve_messages(item), purpose="independent_solve",
                               max_tokens=SOLVE_MAX_TOKENS, request_id=request_id,
                               practice_set_id=practice_set_id, gate=gate,
                               avoid=frozenset({gen.final.model_requested}))
                outcome.usage += solved.records
                if solved.status == "ok":
                    chosen = parse_solve(solved.content)
                    solve = {"performed": True, "model_used": solved.final.model_used or solved.final.model_requested,
                             "chosen_label": chosen, "agrees_with_key": chosen == item["answer_key"]}
            reviewed = route(client, store, prompts.rubric_messages(bundle, item, difficulty), purpose="review",
                             max_tokens=RUBRIC_MAX_TOKENS, request_id=request_id,
                             practice_set_id=practice_set_id, gate=gate,
                             avoid=frozenset({gen.final.model_requested}))
            outcome.usage += reviewed.records
            if reviewed.status == "ok":
                try:
                    rubric = parse_rubric(reviewed.content)
                except OutputError:
                    rubric = None

        decision, reasons = verdict(det, solve, rubric)
        attempts.append({"attempt": number, "item_id": item["item_id"], "verdict": decision, "reasons": reasons})
        validation = {**det, "independent_solve": solve, "verdict": decision, "reasons": reasons,
                      "checker_version": CHECKER_VERSION, "attempts": attempts}
        if rubric is not None:
            validation["rubric"] = rubric
        outcome.item, outcome.validation, outcome.reasons = item, validation, reasons
        if decision == "accept":
            outcome.status = "accepted"
            return outcome
        if decision in ("reject", "pending"):
            break  # grounding failures and missing verification are not fixed by regenerating
        notes = reasons
    return outcome
