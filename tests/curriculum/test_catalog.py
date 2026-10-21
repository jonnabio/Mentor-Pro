"""Practice selection over the catalog: scopes, assessment types, errors."""

import pytest

from curriculum import importer
from curriculum.catalog import (
    AssessmentType, PracticeScope, SelectionError, get_objective, list_objectives,
    list_rubric_criteria, open_catalog, select_objectives,
)

V = "TEST-v1"


@pytest.fixture()
def conn(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db, V, manifest)
    connection = open_catalog(db)
    yield connection
    connection.close()


def codes(objectives):
    return [o["workbook_code"] for o in objectives]


def test_single_objective(conn):
    sel = select_objectives(conn, V, PracticeScope.SINGLE_OBJECTIVE, "matematicas", ["M01"])
    assert codes(sel.objectives) == ["M01"]
    assert [e["ordinal"] for e in sel.objectives[0]["evidences"]] == [1, 2]


def test_selected_objectives_keep_their_evidences(conn):
    sel = select_objectives(conn, V, "selected_objectives", "matematicas", ["M03", "M01"])
    assert codes(sel.objectives) == ["M03", "M01"]
    assert {o["workbook_code"]: len(o["evidences"]) for o in sel.objectives} == {"M03": 1, "M01": 2}


def test_objectives_with_identical_text_are_distinct(conn):
    # M02 and M03 share the same afirmación text in different bloques.
    sel = select_objectives(conn, V, "selected_objectives", "matematicas", ["M02", "M03"])
    assert [o["evidences"][0]["text_es"] for o in sel.objectives] == ["Usa los símbolos <, > o =.", "Compara medidas de ángulos."]


def test_subject_simulation_all_and_subset(conn):
    everything = select_objectives(conn, V, "subject_simulation", "matematicas")
    assert codes(everything.objectives) == ["M01", "M02", "M03"]
    subset = select_objectives(conn, V, "subject_simulation", "matematicas", ["M02"])
    assert codes(subset.objectives) == ["M02"]


def test_rubric_criteria_are_separate(conn):
    assert codes(list_objectives(conn, V, "espanol")) == ["EL01"]
    assert codes(list_rubric_criteria(conn, V)) == ["EE01"]
    assert codes(select_objectives(conn, V, "subject_simulation", "espanol").objectives) == ["EL01"]
    with pytest.raises(SelectionError, match="written_rubric criteria cannot be practised"):
        select_objectives(conn, V, "single_objective", "espanol", ["EE01"])


@pytest.mark.parametrize(
    ("scope", "subject", "selection", "message"),
    [
        ("single_objective", "matematicas", ["M01", "M02"], "exactly one"),
        ("single_objective", "matematicas", [], "exactly one"),
        ("selected_objectives", "matematicas", ["M01"], "two or more"),
        ("selected_objectives", "matematicas", ["M01", "M01"], "duplicate"),
        ("single_objective", "matematicas", ["EL01"], "belongs to espanol"),
        ("single_objective", "matematicas", ["M99"], "not in baseline"),
        ("subject_simulation", "ciencias", None, "no multiple-choice objectives"),
    ],
)
def test_invalid_selections(conn, scope, subject, selection, message):
    with pytest.raises(SelectionError, match=message):
        select_objectives(conn, V, scope, subject, selection)


def test_unknown_scope_is_rejected(conn):
    with pytest.raises(ValueError):
        select_objectives(conn, V, "mixed", "matematicas")


def test_get_objective_and_types(conn):
    assert get_objective(conn, V, "M07") is None
    assert get_objective(conn, V, "EE01")["assessment_type"] == AssessmentType.WRITTEN_RUBRIC.value


def test_catalog_is_read_only(conn):
    import sqlite3

    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM evidence")
