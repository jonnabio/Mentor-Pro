"""Producción escrita progress per EE criterion and dimension (T020, ADR-019).

Independent of the multiple-choice mastery (app/practice/mastery.py): it reads only completed human
evaluations. Per criterion it keeps the latest scored result, the best result and the history count;
`not_evaluable` (EE19/EE20 on typed work) and pending criteria never count as scores. Dimension
indicators average the latest points of the criteria with evidence, and say how much of the dimension is
covered. These are Mentor Pro indicators, not an official MEP grade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.writing import contracts

NOTICE_ES = ("Estos indicadores de producción escrita resumen evaluaciones de Mentor Pro con la rúbrica MEP 2026; "
             "no son una calificación oficial del MEP.")


def criterion_progress(evaluations: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """EE code -> latest/best points, history; every rubric criterion is present."""
    out = {code: {"code": code, "statement_es": c["statement_es"], "dimension": c["dimension"],
                  "evaluations": 0, "latest_points": None, "best_points": None, "latest_at": None,
                  "not_evaluable": 0}
           for code, c in contracts.criteria().items()}
    completed = sorted((e for e in evaluations if e["status"] == "completed"),
                       key=lambda e: datetime.fromisoformat(e["evaluated_at"]))
    for evaluation in completed:
        for score in evaluation["criterion_scores"]:
            row = out[score["criterion"]]
            if score["status"] == "not_evaluable":
                row["not_evaluable"] += 1
                continue
            if score["status"] != "scored":
                continue
            row["evaluations"] += 1
            row["latest_points"], row["latest_at"] = score["points"], evaluation["evaluated_at"]
            row["best_points"] = max(score["points"], row["best_points"] if row["best_points"] is not None else 0)
    return out


def dimension_progress(per_criterion: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for dim in contracts.rubric()["dimensions"]:
        rows = [r for r in per_criterion.values() if r["dimension"] == dim["ordinal"]]
        scored = [r["latest_points"] for r in rows if r["latest_points"] is not None]
        result.append({
            "ordinal": dim["ordinal"], "name_es": dim["name_es"], "weight_pct": dim["weight_pct"],
            "criteria": len(rows), "criteria_with_evidence": len(scored),
            "latest_points_ratio": sum(scored) / (4 * len(scored)) if scored else None,
        })
    return result


def summary(evaluations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    per_criterion = criterion_progress(list(evaluations))
    return {"notice_es": NOTICE_ES, "criteria": list(per_criterion.values()),
            "dimensions": dimension_progress(per_criterion)}
