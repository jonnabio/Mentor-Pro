"""Producción escrita progress per EE criterion and dimension (T020, ADR-019; dashboard T027, ADR-025).

Independent of the multiple-choice mastery (app/practice/mastery.py): scores come only from completed human
evaluations. Per criterion it keeps the latest scored result, the best result and the history count;
`not_evaluable` (EE19/EE20 on typed work) and pending criteria never count as scores. Dimension
indicators average the latest points of the criteria with evidence, and say how much of the dimension is
covered. Submissions still waiting for the tutor only mark their criteria "Evaluación pendiente".
These are Mentor Pro indicators, not an official MEP grade.

T039 (ADR-032): a revision ("Mejora", attempt 2) is a second submission of the same exercise. Existing fields keep
their meaning (they count submissions and evaluations); new fields count distinct exercises, first attempts and
improvements, and `revisions` compares the first and the improved version per criterion. A criterion is compared
only when it is scored in both completed evaluations with the same rubric and the same pinned exercise revision; no
total, average or grade is computed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from app.writing import contracts

NOTICE_ES = ("Estos indicadores de producción escrita resumen evaluaciones de Mentor Pro con la rúbrica MEP 2026; "
             "no son una calificación oficial del MEP.")
CRITERION_STATUS_ES = {"evaluated": "Evaluado", "pending": "Evaluación pendiente", "unassessed": "Sin evaluar"}
WAITING = (None, "pending", "in_progress")  # evaluation status of a submission still waiting for the tutor
PENDING_IMPROVEMENT_ES = "Tu mejora está pendiente de revisión."
NOT_COMPARABLE_ES = "No comparable"


def criterion_progress(evaluations: Iterable[dict[str, Any]],
                       submissions: Iterable[dict[str, Any]] = ()) -> dict[str, dict[str, Any]]:
    """EE code -> latest/best points, history, status; every rubric criterion is present."""
    out = {code: {"code": code, "statement_es": c["statement_es"], "dimension": c["dimension"],
                  "evaluations": 0, "latest_points": None, "best_points": None, "latest_at": None,
                  "not_evaluable": 0, "pending": 0, "exercises": 0, "improvements_pending": 0}
           for code, c in contracts.criteria().items()}
    scored_in: dict[str, set] = {code: set() for code in out}
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
            scored_in[score["criterion"]].add(evaluation.get("exercise_id") or evaluation.get("evaluation_id"))
            row["latest_points"], row["latest_at"] = score["points"], evaluation["evaluated_at"]
            row["best_points"] = max(score["points"], row["best_points"] if row["best_points"] is not None else 0)
    for submission in submissions:
        if submission["evaluation_status"] in WAITING:
            for code in submission["scorable_criteria"]:
                out[code]["pending"] += 1
                if submission.get("attempt_number", 1) > 1:
                    out[code]["improvements_pending"] += 1
    for code, row in out.items():
        row["exercises"] = len(scored_in[code])
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

    def exercises(items: Iterable[dict[str, Any]]) -> int:
        return len({s.get("exercise_id") or s["submission_id"] for s in items})

    improvements = [s for s in submissions if s.get("attempt_number", 1) > 1]
    dates = [s["submitted_at"] for s in submissions] + ([last_draft_at] if last_draft_at else [])
    return {
        "submitted": len(submissions),
        "evaluations_completed": len(completed),
        "evaluations_pending": sum(1 for s in submissions if s["evaluation_status"] in WAITING),
        # T039: by exercise identity, and first attempts apart from improvements.
        "exercises_submitted": exercises(submissions),
        "exercises_evaluated": exercises(completed),
        "first_attempts": len(submissions) - len(improvements),
        "improvements": len(improvements),
        "improvements_pending": sum(1 for s in improvements if s["evaluation_status"] in WAITING),
        "levels": [{"code": lv["code"], "ordinal": lv["ordinal"], "label_es": f"Nivel {lv['ordinal']}: {lv['name_es']}",
                    "submitted": sum(1 for s in submissions if s["level"] == lv["code"]),
                    "evaluated": sum(1 for s in completed if s["level"] == lv["code"]),
                    "exercises_submitted": exercises(s for s in submissions if s["level"] == lv["code"]),
                    "exercises_evaluated": exercises(s for s in completed if s["level"] == lv["code"])}
                   for lv in contracts.levels()["levels"]],
        "last_practice_at": max(dates, key=datetime.fromisoformat) if dates else None,
    }


def _completed(version: dict[str, Any] | None) -> dict[str, Any] | None:
    evaluation = (version or {}).get("evaluation")
    return evaluation if evaluation and evaluation.get("status") == "completed" else None


def compare(first: dict[str, Any], improved: dict[str, Any]) -> dict[str, Any]:
    """First versus improved version of one exercise. Each version is {"exercise_revision", "evaluation"} with the
    evaluation record or None. Per criterion a change only when both completed evaluations score it, with the same
    rubric (id and checksum) and the same pinned exercise revision; otherwise "No comparable" without a number."""
    criteria = contracts.criteria()
    a, b = _completed(first), _completed(improved)
    pending = b is None
    same = a is not None and b is not None \
        and (a.get("rubric_id"), a.get("rubric_sha256")) == (b.get("rubric_id"), b.get("rubric_sha256")) \
        and first.get("exercise_revision") == improved.get("exercise_revision")
    scores = [{s["criterion"]: s for s in e["criterion_scores"]} if e else {} for e in (a, b)]
    rows = []
    for code in (c for c in criteria if c in scores[0] or c in scores[1]):
        sa, sb = scores[0].get(code), scores[1].get(code)
        row = {"code": code, "statement_es": criteria[code]["statement_es"],
               "first_points": sa["points"] if sa and sa["status"] == "scored" else None,
               "improved_points": sb["points"] if sb and sb["status"] == "scored" else None,
               "change": None, "change_es": None}
        if not pending:
            if same and row["first_points"] is not None and row["improved_points"] is not None:
                change = row["improved_points"] - row["first_points"]
                unit = "punto" if abs(change) == 1 else "puntos"
                row.update(change=change, change_es=f"{change:+d} {unit} en {code}" if change else f"Igual en {code}")
            else:
                row["change_es"] = NOT_COMPARABLE_ES
        rows.append(row)
    changes = [r["change"] for r in rows if r["change"] is not None]
    if pending:
        summary_es = PENDING_IMPROVEMENT_ES
    elif not changes:
        summary_es = "No hay criterios comparables entre las dos versiones."
    else:
        summary_es = (f"Mejoraste en {sum(1 for c in changes if c > 0)}, igual en {sum(1 for c in changes if c == 0)}"
                      f" y bajaste en {sum(1 for c in changes if c < 0)} de {len(changes)} criterios comparables.")
    return {"status": "pending" if pending else "completed", "comparable": bool(changes),
            "first_evaluated_at": a["evaluated_at"] if a else None,
            "improved_evaluated_at": b["evaluated_at"] if b else None,
            "criteria": rows, "summary_es": summary_es}


def revisions(submissions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One comparison per exercise with an improvement (first attempt against the latest), newest first."""
    by_exercise: dict[str, list[dict[str, Any]]] = {}
    for s in submissions:
        if s.get("exercise_id"):
            by_exercise.setdefault(s["exercise_id"], []).append(s)
    out = []
    for exercise_id, subs in by_exercise.items():
        subs.sort(key=lambda s: s["attempt_number"])
        if len(subs) < 2 or subs[0]["attempt_number"] != 1:
            continue
        first, improved = subs[0], subs[-1]
        out.append({"exercise_id": exercise_id, "title_es": improved.get("title_es"), "level": improved["level"],
                    "first_submitted_at": first["submitted_at"], "improved_submitted_at": improved["submitted_at"],
                    "attempt_number": improved["attempt_number"], **compare(first, improved)})
    return sorted(out, key=lambda r: datetime.fromisoformat(r["improved_submitted_at"]), reverse=True)


def summary(evaluations: Iterable[dict[str, Any]], submissions: Iterable[dict[str, Any]] = (),
            last_draft_at: str | None = None) -> dict[str, Any]:
    submissions = list(submissions)
    per_criterion = criterion_progress(list(evaluations), submissions)
    rows = per_criterion.values()
    return {"notice_es": NOTICE_ES, "criteria": list(rows),
            "dimensions": dimension_progress(per_criterion),
            "coverage": {"total": len(per_criterion),
                         **{status: sum(1 for r in rows if r["status"] == status) for status in CRITERION_STATUS_ES}},
            "activity": activity(submissions, last_draft_at),
            "revisions": revisions(submissions)}
