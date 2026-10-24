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
