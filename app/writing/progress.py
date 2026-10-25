"""Producción escrita progress per EE criterion and dimension (T020, ADR-019; dashboard T027, ADR-025).

Independent of the multiple-choice mastery (app/practice/mastery.py): scores come only from completed human
evaluations. Per criterion it keeps the latest scored result, the best result and the history count;
`not_evaluable` (EE19/EE20 on typed work) and pending criteria never count as scores. Dimension
indicators average the latest points of the criteria with evidence, and say how much of the dimension is
covered. Submissions still waiting for the tutor only mark their criteria "Evaluación pendiente".
These are Mentor Pro indicators, not an official MEP grade.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.writing import contracts

NOTICE_ES = ("Estos indicadores de producción escrita resumen evaluaciones de Mentor Pro con la rúbrica MEP 2026; "
             "no son una calificación oficial del MEP.")
CRITERION_STATUS_ES = {"evaluated": "Evaluado", "pending": "Evaluación pendiente", "unassessed": "Sin evaluar"}
WAITING = (None, "pending", "in_progress")  # evaluation status of a submission still waiting for the tutor


def criterion_progress(evaluations: Iterable[dict[str, Any]],
                       submissions: Iterable[dict[str, Any]] = ()) -> dict[str, dict[str, Any]]:
    """EE code -> latest/best points, history, status; every rubric criterion is present."""
    out = {code: {"code": code, "statement_es": c["statement_es"], "dimension": c["dimension"],
                  "evaluations": 0, "latest_points": None, "best_points": None, "latest_at": None,
                  "not_evaluable": 0, "pending": 0}
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
    for submission in submissions:
        if submission["evaluation_status"] in WAITING:
            for code in submission["scorable_criteria"]:
                out[code]["pending"] += 1
    for row in out.values():
        row["status"] = "evaluated" if row["evaluations"] else "pending" if row["pending"] else "unassessed"
        row["status_es"] = CRITERION_STATUS_ES[row["status"]]
    return out


def dimension_progress(per_criterion: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Averages use only criteria with a score; unassessed and not-evaluable criteria are not in the denominator."""
    result = []
    for dim in contracts.rubric()["dimensions"]:
        rows = [r for r in per_criterion.values() if r["dimension"] == dim["ordinal"]]
        scored = [r["latest_points"] for r in rows if r["latest_points"] is not None]
        result.append({
            "ordinal": dim["ordinal"], "name_es": dim["name_es"], "weight_pct": dim["weight_pct"],
            "criteria": len(rows), "criteria_with_evidence": len(scored),
            "criteria_codes": [r["code"] for r in rows],
            "average_latest_points": sum(scored) / len(scored) if scored else None,
            "latest_points_ratio": sum(scored) / (4 * len(scored)) if scored else None,
        })
    return result


def activity(submissions: list[dict[str, Any]], last_draft_at: str | None = None) -> dict[str, Any]:
    """Counts of submissions and evaluations, per level L1-L5, and the last practice date."""
    completed = [s for s in submissions if s["evaluation_status"] == "completed"]
    dates = [s["submitted_at"] for s in submissions] + ([last_draft_at] if last_draft_at else [])
    return {
        "submitted": len(submissions),
        "evaluations_completed": len(completed),
        "evaluations_pending": sum(1 for s in submissions if s["evaluation_status"] in WAITING),
        "levels": [{"code": lv["code"], "ordinal": lv["ordinal"], "label_es": f"Nivel {lv['ordinal']}: {lv['name_es']}",
                    "submitted": sum(1 for s in submissions if s["level"] == lv["code"]),
                    "evaluated": sum(1 for s in completed if s["level"] == lv["code"])}
                   for lv in contracts.levels()["levels"]],
        "last_practice_at": max(dates, key=datetime.fromisoformat) if dates else None,
    }


def summary(evaluations: Iterable[dict[str, Any]], submissions: Iterable[dict[str, Any]] = (),
            last_draft_at: str | None = None) -> dict[str, Any]:
    submissions = list(submissions)
    per_criterion = criterion_progress(list(evaluations), submissions)
    rows = per_criterion.values()
    return {"notice_es": NOTICE_ES, "criteria": list(rows),
            "dimensions": dimension_progress(per_criterion),
            "coverage": {"total": len(per_criterion),
                         **{status: sum(1 for r in rows if r["status"] == status) for status in CRITERION_STATUS_ES}},
            "activity": activity(submissions, last_draft_at)}
