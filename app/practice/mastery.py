"""Repeat-aware learning status per objective and subject (T014, ADR-015).

Single anonymous student: every recorded answer in `practice.answer` belongs to
that student, whatever the session or browser tab. A question is identified by
its canonical `item_id`, so a bank question served again in another practice
is a repeat. The first answer to each distinct question is its first attempt;
mastery accuracy uses first attempts only, so repeating a question can never
raise mastery. All answers are kept; nothing is overwritten.

These statuses are Mentor Pro learning indicators, not official MEP
performance levels.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import psycopg
from psycopg.rows import dict_row

STATUS_LABELS_ES = {
    "unpracticed": "Sin practicar",
    "insufficient_evidence": "Evidencia insuficiente",
    "needs_reinforcement": "Necesita refuerzo",
    "in_progress": "En progreso",
    "good_proficiency": "Buen dominio",
    "consolidated_mastery": "Dominio consolidado",
}
STATUSES = tuple(STATUS_LABELS_ES)
RECOMMENDATIONS_ES = {
    "consolidated_mastery": "¡Excelente dominio! Practicá de vez en cuando para mantener lo aprendido.",
}
NOTICE_ES = ("Estos estados son indicadores de aprendizaje de Mentor Pro calculados con sus primeras respuestas; "
             "no son niveles oficiales de desempeño del MEP.")


@dataclass(frozen=True)
class Thresholds:
    """Exact fractions; accuracy is compared unrounded."""
    min_distinct: int = 5
    reinforcement_below: Fraction = Fraction(60, 100)   # < 60 % → needs reinforcement
    progress_below: Fraction = Fraction(80, 100)        # < 80 % → in progress
    good_up_to: Fraction = Fraction(90, 100)            # ≤ 90 % → good proficiency; above → consolidated

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Thresholds:
        def pct(name: str, default: Fraction) -> Fraction:
            raw = env.get(name)
            return Fraction(raw) / 100 if raw else default

        t = cls(
            min_distinct=int(env.get("MENTOR_PRO_MASTERY_MIN_DISTINCT", cls.min_distinct)),
            reinforcement_below=pct("MENTOR_PRO_MASTERY_REINFORCEMENT_BELOW_PCT", cls.reinforcement_below),
            progress_below=pct("MENTOR_PRO_MASTERY_PROGRESS_BELOW_PCT", cls.progress_below),
            good_up_to=pct("MENTOR_PRO_MASTERY_GOOD_UP_TO_PCT", cls.good_up_to),
        )
        if t.min_distinct < 1 or not 0 < t.reinforcement_below <= t.progress_below <= t.good_up_to < 1:
            raise ValueError("mastery thresholds must satisfy 0 < reinforcement ≤ progress ≤ good < 100 %")
        return t


def classify(distinct: int, first_correct: int, thresholds: Thresholds = Thresholds()) -> str:
    """Status from first attempts on distinct questions (exact arithmetic, no rounding)."""
    if distinct == 0:
        return "unpracticed"
    if distinct < thresholds.min_distinct:
        return "insufficient_evidence"
    accuracy = Fraction(first_correct, distinct)
    if accuracy < thresholds.reinforcement_below:
        return "needs_reinforcement"
    if accuracy < thresholds.progress_below:
        return "in_progress"
    if accuracy <= thresholds.good_up_to:
        return "good_proficiency"
    return "consolidated_mastery"


ANSWERS_SQL = """
SELECT i.objective_code, i.evidence_id, i.item->>'item_id' AS question_id, a.is_correct,
       ROW_NUMBER() OVER (PARTITION BY i.item->>'item_id' ORDER BY a.answered_at, a.session_id, a.slot) AS nth
FROM practice.answer a
JOIN practice.item i USING (session_id, slot)
JOIN practice.session s USING (session_id)
WHERE s.subject = %s AND s.baseline_version = %s
"""


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def objective_metrics(rows: list[dict[str, Any]], thresholds: Thresholds) -> dict[str, Any]:
    first = [r for r in rows if r["nth"] == 1]
    repeats = [r for r in rows if r["nth"] > 1]
    first_correct = sum(r["is_correct"] for r in first)
    status = classify(len(first), first_correct, thresholds)
    return {
        "total_answers": len(rows),
        "correct_answers": sum(r["is_correct"] for r in rows),
        "practice_accuracy": ratio(sum(r["is_correct"] for r in rows), len(rows)),
        "distinct_questions": len(first),
        "first_attempt_correct": first_correct,
        "mastery_accuracy": ratio(first_correct, len(first)),
        "repeat_answers": len(repeats),
        "repeat_accuracy": ratio(sum(r["is_correct"] for r in repeats), len(repeats)),
        "repeat_exposure_rate": ratio(len(repeats), len(rows)),
        "distinct_evidences": len({r["evidence_id"] for r in first}),
        "status": status,
        "status_es": STATUS_LABELS_ES[status],
        "recommendation_es": RECOMMENDATIONS_ES.get(status),
    }


def subject_dashboard(conn: psycopg.Connection, baseline: str, subject: str, objectives: list[dict[str, Any]],
                      thresholds: Thresholds) -> dict[str, Any]:
    """Every selectable objective of the subject, with metrics and status, plus a subject summary."""
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(ANSWERS_SQL, (subject, baseline)).fetchall()
    by_objective: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_objective.setdefault(row["objective_code"], []).append(row)
    items = []
    for objective in objectives:
        metrics = objective_metrics(by_objective.get(objective["workbook_code"], []), thresholds)
        items.append({"code": objective["workbook_code"], "text_es": objective["text_es"],
                      "block_name_es": objective["block_name_es"], **metrics})
    counts = {status: sum(1 for o in items if o["status"] == status) for status in STATUSES}
    total = sum(o["total_answers"] for o in items)
    distinct = sum(o["distinct_questions"] for o in items)
    return {
        "subject": subject,
        "objective_count": len(items),
        "status_counts": counts,
        "total_answers": total,
        "practice_accuracy": ratio(sum(o["correct_answers"] for o in items), total),
        "distinct_questions": distinct,
        "mastery_accuracy": ratio(sum(o["first_attempt_correct"] for o in items), distinct),
        "repeat_exposure_rate": ratio(sum(o["repeat_answers"] for o in items), total),
        "objectives": items,
    }
