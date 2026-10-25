"""Repeatable seeding of the Nivel 1 inventory (T023, ADR-022).

One approved correction exercise per category of editing.CATEGORIES. Seeding reads the stored inventory,
generates only missing categories, never overwrites or deletes exercises, and never touches drafts or
submissions. Budget stops are reported as an inventory gap; validation is never relaxed.
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.llm.client import OpenRouterClient
from app.llm.router import Store
from app.writing import editing


def inventory(writing_store: Any) -> dict[str, list[str]]:
    """Category -> approved exercise IDs (exercise type conventions_editing, exact criteria set)."""
    found: dict[str, list[str]] = {name: [] for name in editing.CATEGORIES}
    for row in writing_store.exercises("writing_conventions"):
        record = row["record"]
        if record["exercise_type"] != "conventions_editing":
            continue
        for name, plan in editing.CATEGORIES.items():
            if sorted(record["target_criteria"]) == sorted(plan["criteria"]):
                found[name].append(row["exercise_id"])
    return found


def seed(client: OpenRouterClient, usage_store: Store, catalog: psycopg.Connection, writing_store: Any,
         difficulty: str = "medium") -> dict[str, Any]:
    before = inventory(writing_store)
    results = []
    for name in editing.CATEGORIES:
        if before[name]:
            results.append({"category": name, "status": "present", "exercise_id": before[name][0], "attempts": []})
            continue
        outcome = editing.generate_editing_exercise(client, usage_store, catalog, writing_store, name, difficulty)
        results.append({
            "category": name, "status": outcome.status, "stop_reason": outcome.stop_reason,
            "exercise_id": outcome.exercise["exercise_id"] if outcome.exercise else None,
            "attempts": [{"request_id": a.request_id, "status": a.status, "reasons": a.reasons, "review": a.review,
                          "checks": a.checks, **a.summary()} for a in outcome.attempts]})
        if outcome.status == "unavailable":
            break  # budget or provider stop: report the gap instead of retrying
    after = inventory(writing_store)
    attempts = [a for r in results for a in r["attempts"]]
    return {
        "results": results,
        "inventory": after,
        "gap": [name for name, ids in after.items() if not ids],
        "totals": {"attempts": len(attempts),
                   "accepted": sum(a["status"] == "accepted" for a in attempts),
                   "rejected": sum(a["status"] == "rejected" for a in attempts),
                   "calls": sum(a["calls"] for a in attempts),
                   "tokens_in": sum(a["tokens_in"] for a in attempts),
                   "tokens_out": sum(a["tokens_out"] for a in attempts),
                   "cost_usd": round(sum(a["cost_usd"] for a in attempts), 8),
                   "cost_complete": all(a["cost_complete"] for a in attempts)},
    }


# ---------------------------------------------------------------- T025: composed paragraphs (L2, L3)

COMPOSE_PLAN = (  # (level, exercise type, criteria, approved exercises wanted)
    ("L2", "introduction_paragraph", ["EE03", "EE04"], 3),
    ("L3", "development_paragraphs", ["EE03", "EE05"], 2),
    ("L3", "conclusion_paragraph", ["EE03", "EE06"], 1),
)


def compose_inventory(writing_store: Any) -> dict[str, list[str]]:
    """Exercise type -> approved exercise IDs (latest revision), for the types in COMPOSE_PLAN."""
    found: dict[str, list[str]] = {kind: [] for _, kind, _, _ in COMPOSE_PLAN}
    for row in writing_store.exercises():
        kind = row["record"]["exercise_type"]
        if kind in found:
            found[kind].append(row["exercise_id"])
    return found


def seed_compose(client: OpenRouterClient, usage_store: Store, catalog: psycopg.Connection, writing_store: Any,
                 difficulty: str = "medium") -> dict[str, Any]:
    """Generate only the missing L2/L3 exercises; stop at a budget or provider stop and report the gap."""
    from app.writing import generation

    before = compose_inventory(writing_store)
    results, stopped = [], False
    for level, kind, criteria, wanted in COMPOSE_PLAN:
        missing = max(0, wanted - len(before[kind]))
        for _ in range(missing):
            if stopped:
                break
            outcome = generation.generate_exercise(client, usage_store, catalog, writing_store, level, difficulty,
                                                   criteria)
            results.append({
                "level": level, "exercise_type": kind, "status": outcome.status, "stop_reason": outcome.stop_reason,
                "exercise_id": outcome.exercise["exercise_id"] if outcome.exercise else None,
                "topic_es": outcome.exercise["topic_es"] if outcome.exercise else None,
                "attempts": [{"request_id": a.request_id, "status": a.status, "reasons": a.reasons,
                              "review": a.review, **a.summary()} for a in outcome.attempts]})
            stopped = outcome.status == "unavailable"
    after = compose_inventory(writing_store)
    attempts = [a for r in results for a in r["attempts"]]
    return {
        "results": results, "inventory": after,
        "gap": {kind: wanted - len(after[kind]) for _, kind, _, wanted in COMPOSE_PLAN if len(after[kind]) < wanted},
        "totals": {"attempts": len(attempts), "accepted": sum(a["status"] == "accepted" for a in attempts),
                   "rejected": sum(a["status"] == "rejected" for a in attempts),
                   "calls": sum(a["calls"] for a in attempts), "tokens_in": sum(a["tokens_in"] for a in attempts),
                   "tokens_out": sum(a["tokens_out"] for a in attempts),
                   "cost_usd": round(sum(a["cost_usd"] for a in attempts), 8),
                   "cost_complete": all(a["cost_complete"] for a in attempts)},
    }
