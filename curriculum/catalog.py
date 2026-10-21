"""Read-only queries over the curriculum catalog for practice selection.

Practice scope (how objectives are chosen) is independent of assessment type
(how they are assessed). Only `multiple_choice` objectives can be selected for
practice; `written_rubric` criteria are retrieved separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import psycopg

from curriculum import db


class PracticeScope(str, Enum):
    SINGLE_OBJECTIVE = "single_objective"
    SELECTED_OBJECTIVES = "selected_objectives"
    SUBJECT_SIMULATION = "subject_simulation"


class AssessmentType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    WRITTEN_RUBRIC = "written_rubric"


class SelectionError(ValueError):
    """Raised when a practice selection is invalid."""


@dataclass(frozen=True)
class Selection:
    scope: PracticeScope
    subject_code: str
    objectives: list[dict[str, Any]]  # each with its "evidences" list, ordered by ordinal


_OBJECTIVE_SQL = """
    SELECT a.workbook_code, a.id, a.ordinal, a.numbering_es, a.text_es, a.concepts_es,
           a.check_activity_es, a.source_citation_es, a.source_page, a.planned_items,
           a.provenance, a.baseline_status, a.verification_status,
           b.id AS block_id, b.name_es AS block_name_es, b.assessment_type, b.subject_code
    FROM assertion a
    JOIN block b ON b.baseline_version = a.baseline_version AND b.id = a.block_id
    WHERE a.baseline_version = %s
"""


def open_catalog(url: str | None = None, schema: str = db.DEFAULT_SCHEMA) -> psycopg.Connection:
    """Open the catalog read-only (writes are rejected by the server)."""
    return db.connect(url or db.database_url(), schema, read_only=True)


def _with_evidences(conn: psycopg.Connection, version: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objectives = []
    for row in rows:
        evidences = conn.execute(
            "SELECT id, ordinal, text_es, provenance, verification_status FROM evidence "
            "WHERE baseline_version = %s AND assertion_id = %s ORDER BY ordinal",
            (version, row["id"]),
        ).fetchall()
        objectives.append({**row, "evidences": list(evidences)})
    return objectives


def list_objectives(conn: psycopg.Connection, version: str, subject_code: str,
                    assessment_type: AssessmentType = AssessmentType.MULTIPLE_CHOICE) -> list[dict[str, Any]]:
    """All objectives of one subject and assessment type, in workbook code order, with evidences."""
    rows = conn.execute(
        _OBJECTIVE_SQL + " AND b.subject_code = %s AND b.assessment_type = %s "
        "AND a.baseline_status = 'approved' ORDER BY a.workbook_code",
        (version, subject_code, assessment_type.value),
    ).fetchall()
    return _with_evidences(conn, version, rows)


def get_objective(conn: psycopg.Connection, version: str, workbook_code: str) -> dict[str, Any] | None:
    """One objective by its workbook code (e.g. "M07"), with evidences; None if absent."""
    rows = conn.execute(_OBJECTIVE_SQL + " AND a.workbook_code = %s", (version, workbook_code)).fetchall()
    found = _with_evidences(conn, version, rows)
    return found[0] if found else None


def list_rubric_criteria(conn: psycopg.Connection, version: str) -> list[dict[str, Any]]:
    """Written-production rubric criteria (Español EE); never part of practice selection."""
    return list_objectives(conn, version, "espanol", AssessmentType.WRITTEN_RUBRIC)


def select_objectives(conn: psycopg.Connection, version: str, scope: PracticeScope | str,
                      subject_code: str, codes: list[str] | None = None) -> Selection:
    """Resolve a practice selection to objectives with their evidences.

    @param scope - single_objective (exactly one code), selected_objectives (two or
        more codes) or subject_simulation (all objectives, or a subset given in codes)
    @param codes - workbook codes; order is preserved, duplicates rejected
    @throws SelectionError for unknown codes, other subjects, rubric criteria or
        a code count that does not match the scope
    """
    scope = PracticeScope(scope)
    available = {o["workbook_code"]: o for o in list_objectives(conn, version, subject_code)}
    if not available:
        raise SelectionError(f"no multiple-choice objectives for subject {subject_code!r} in {version}")

    if scope is PracticeScope.SUBJECT_SIMULATION and not codes:
        return Selection(scope, subject_code, list(available.values()))

    codes = list(codes or [])
    if len(set(codes)) != len(codes):
        raise SelectionError("duplicate objective codes in selection")
    if scope is PracticeScope.SINGLE_OBJECTIVE and len(codes) != 1:
        raise SelectionError("single_objective requires exactly one objective code")
    if scope is PracticeScope.SELECTED_OBJECTIVES and len(codes) < 2:
        raise SelectionError("selected_objectives requires two or more objective codes")

    unknown = [c for c in codes if c not in available]
    if unknown:
        reasons = []
        for code in unknown:
            other = get_objective(conn, version, code)
            if other is None:
                reasons.append(f"{code}: not in baseline {version}")
            elif other["assessment_type"] != AssessmentType.MULTIPLE_CHOICE.value:
                reasons.append(f"{code}: {other['assessment_type']} criteria cannot be practised")
            else:
                reasons.append(f"{code}: belongs to {other['subject_code']}, not {subject_code}")
        raise SelectionError("; ".join(reasons))
    return Selection(scope, subject_code, [available[c] for c in codes])
