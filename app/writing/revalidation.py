"""Independent-review remediation of writing exercises (T029, ADR-027, RCA-004).

Identify exercises whose accepted W08 review came from their own generator, quarantine them (append-only
eligibility events), and revalidate the revision students see: the current contract and deterministic
checks, then the review rubric the exercise was generated with, routed with the generator excluded. Only a
passed independent review reinstates an exercise. Every revalidation is stored with its models, results and
costs; exercise records, revisions, references, attempts, drafts and submissions are never changed.
"""

from __future__ import annotations

import secrets
from typing import Any

import psycopg

from app.generation.parsing import OutputError
from app.generation.pipeline import RUBRIC_MAX_TOKENS
from app.llm.budget import BudgetGate
from app.llm.client import OpenRouterClient
from app.llm.router import Store, same_model
from app.writing import contracts, editing, generation, revisions
from app.writing.store import WritingStore

VERSION = "independent-review-1.1"  # 1.0: first T029 runs; 1.1: L1 reviews get EDIT_REVIEW_MAX_TOKENS
SOURCE = "RCA-004"
MAX_CALLS = 6  # review calls per exercise, including route() retries; T031: 3 per reviewer, primary and fallback
# Approved eligible inventory (T029): level code -> minimum eligible exercises.
REQUIRED_INVENTORY = {"writing_conventions": 3, "idea_development": 3, "paragraph_writing": 3,
                      "guided_composition": 1}

SELF_REVIEWED_SQL = """
SELECT a.exercise_id, a.request_id,
       (SELECT u.model_used FROM llm.usage_record u WHERE u.request_id = a.request_id AND u.purpose = 'generation'
        AND u.status = 'ok' ORDER BY u.started_at DESC LIMIT 1) AS generator_model,
       (SELECT u.model_used FROM llm.usage_record u WHERE u.request_id = a.request_id AND u.purpose = 'review'
        AND u.status = 'ok' ORDER BY u.started_at DESC LIMIT 1) AS reviewer_model
FROM writing.generation_attempt a
WHERE a.status = 'accepted' AND a.exercise_id IS NOT NULL
ORDER BY a.created_at"""


def accepted_reviews(url: str) -> list[dict[str, Any]]:
    """Every accepted generation with the models that generated and reviewed it (from llm.usage_record)."""
    with psycopg.connect(url, row_factory=psycopg.rows.dict_row) as conn:
        return conn.execute(SELF_REVIEWED_SQL).fetchall()


def self_reviewed(url: str) -> list[dict[str, Any]]:
    """RCA-004: accepted exercises whose review came from the generating model (or from no recorded model)."""
    return [r for r in accepted_reviews(url)
            if not r["reviewer_model"] or same_model(r["reviewer_model"], r["generator_model"])]


def quarantine(store: WritingStore, affected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quarantine each affected exercise once; a rerun never undoes a reinstatement."""
    out = []
    for row in affected:
        if any(e["status"] == "quarantined" and e["source"] == SOURCE
               for e in store.eligibility_events(row["exercise_id"])):
            out.append({"exercise_id": row["exercise_id"], "quarantined": False, "new_event": False,
                        "status": store.eligibility(row["exercise_id"])})
            continue
        added = store.set_eligibility(row["exercise_id"], "quarantined",
                                      f"accepted review not independent: generator {row['generator_model']}, "
                                      f"reviewer {row['reviewer_model']}", SOURCE)
        out.append({"exercise_id": row["exercise_id"], "quarantined": True, "new_event": added})
    return out


def _review(g: generation.Grounding, record: dict[str, Any], reference: dict[str, Any] | None):
    """Messages, parser, prompt version and output limit of the review the exercise type is generated with."""
    if record["exercise_type"] == "conventions_editing":
        return (editing.review_messages(g, record, reference), editing.parse_review, editing.PROMPT_VERSION,
                editing.EDIT_REVIEW_MAX_TOKENS)
    return (generation.review_messages(g, record),
            lambda text: generation.parse_review(text, generation.COMPOSE_REVIEW_KEYS), generation.PROMPT_VERSION,
            RUBRIC_MAX_TOKENS)


def revalidate(client: OpenRouterClient, usage_store: Store, catalog: psycopg.Connection, store: WritingStore,
               exercise_id: str, generator_model: str | None, baseline: str = "PNE2026-SUM-v1.0") -> dict[str, Any]:
    """Check and independently review the current revision; reinstate only on a passed review."""
    current = next(r for r in store.exercises(eligible_only=False) if r["exercise_id"] == exercise_id)
    record, revision = current["record"], current["revision"]
    reference = None
    if record["exercise_type"] == "conventions_editing":
        ref = store.reference_correction(exercise_id, revision)
        reference = {k: ref[k] for k in ("corrected_text_es", "corrections", "ambiguities_es")} | \
            {"exercise_id": exercise_id} if ref else None
    request_id = f"wval-{secrets.token_hex(8)}"
    row: dict[str, Any] = {"validation_id": f"VAL-{secrets.token_hex(8)}", "exercise_id": exercise_id,
                           "exercise_revision": revision, "generator_model": generator_model, "reviewer_model": None,
                           "review": None, "reasons": [], "request_id": request_id}
    checks = [{"id": "W02", "status": "fail", "message": "; ".join(p)}
              for p in [contracts.validate_exercise(record)] if p]
    if not checks:
        checks = revisions.checks_for(catalog, store, record, reference, baseline)
    failed = [c for c in checks if c["status"] == "fail"]
    usage: list[dict[str, Any]] = []
    if failed:
        row.update(status="failed", reasons=[f"{c['id']}: {c['message']}" for c in failed])
    elif not generator_model:
        row.update(status="unavailable", reasons=["generator model unknown: independence cannot be shown"])
    else:
        level = contracts.level(record["level"])
        g = generation.build_grounding(catalog, baseline, f"L{level['ordinal']}", record["difficulty"],
                                       record["target_criteria"], exercise_type=record["exercise_type"])
        messages, parse, prompt_version, max_tokens = _review(g, record, reference)
        gate = BudgetGate(usage_store, client.settings, max_calls=MAX_CALLS)
        reviewed = generation.review_route(client, usage_store, messages, max_tokens, request_id, generator_model,
                                           gate)
        usage = reviewed.records
        row["version"] = f"{VERSION}+{prompt_version}"
        reviewer = reviewed.final.model_used if reviewed.final else None
        if reviewed.status != "ok":
            row.update(status="unavailable", reasons=[f"review {reviewed.status}: {reviewed.message}"])
        elif generation.same_model_review(generator_model, reviewed):
            row.update(status="failed", reviewer_model=reviewer,
                       reasons=[f"W08: {generation.same_model_review(generator_model, reviewed)}"])
        else:
            row["reviewer_model"] = reviewer
            try:
                review = parse(reviewed.content or "")
            except OutputError as exc:
                row.update(status="failed", reasons=[f"W08: review output: {exc}"])
            else:
                low = {k: v for k, v in review.items() if k != "notes" and v < 2}
                row.update(review=review, status="failed" if low else "passed",
                           reasons=[f"W08: review below 2: {low}"] if low else [])
        checks = checks + [{"id": "W08", "status": "pass" if row["status"] == "passed" else "fail",
                            "message": "ok" if row["status"] == "passed" else "; ".join(row["reasons"])}]
    row.setdefault("version", VERSION)
    sent = [u for u in usage if u["status"] != "budget_blocked"]
    row.update(checks=checks, calls=len(sent), tokens_in=sum(u["tokens_in"] or 0 for u in sent),
               tokens_out=sum(u["tokens_out"] or 0 for u in sent),
               cost_usd=round(sum(u["cost_usd"] or 0 for u in sent), 8),
               cost_complete=all(u["cost_usd"] is not None for u in sent if u["status"] == "ok"))
    store.add_validation(row)
    if row["status"] == "passed":
        store.set_eligibility(exercise_id, "eligible", f"independent review passed ({row['reviewer_model']})",
                              VERSION, row["validation_id"])
    return {**row, "models_called": sorted({u["model_requested"] for u in usage})}


def inventory(store: WritingStore) -> dict[str, Any]:
    """Eligible exercises per level against the required minimum."""
    counts = {code: 0 for code in REQUIRED_INVENTORY}
    for row in store.exercises():
        counts[row["level"]] = counts.get(row["level"], 0) + 1
    return {"eligible": counts, "required": REQUIRED_INVENTORY,
            "gap": {k: v - counts.get(k, 0) for k, v in REQUIRED_INVENTORY.items() if counts.get(k, 0) < v}}
