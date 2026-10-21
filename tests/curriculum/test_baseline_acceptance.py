"""Acceptance checks for baseline PNE2026-SUM-v1.0 against the real workbook.

The workbook is not in Git (references/original/ is ignored). It is located
by its SHA-256 from references/MANIFEST.sha256. Without it these tests skip
with an explicit reason; the import report records the run that passed.
"""

from collections import Counter

import openpyxl
import pytest
from psycopg.rows import tuple_row

from workbook_fixtures import baseline_workbook, drop_target, new_target
from curriculum import importer
from curriculum.catalog import list_objectives, list_rubric_criteria, open_catalog, select_objectives

V = importer.DEFAULT_VERSION
EXPECTED_COMPONENTS = {
    ("Español", "multiple_choice"): (8, 53),
    ("Español", "written_rubric"): (20, 20),
    ("Matemáticas", "multiple_choice"): (22, 108),
    ("Ciencias", "multiple_choice"): (19, 82),
    ("Estudios Sociales", "multiple_choice"): (29, 81),
}
SUBJECT_CODES = {"Español": "espanol", "Matemáticas": "matematicas", "Ciencias": "ciencias",
                 "Estudios Sociales": "estudios_sociales"}


WORKBOOK = baseline_workbook()
pytestmark = pytest.mark.skipif(WORKBOOK is None, reason="baseline workbook not present in references/original/")


@pytest.fixture(scope="module")
def baseline():
    target = new_target()
    report = importer.import_workbook(WORKBOOK, target.url, V, schema=target.schema)
    conn = open_catalog(target.url, target.schema)
    yield report, conn
    conn.close()
    drop_target(target)


def t(conn):
    """Cursor returning tuples, for direct SQL assertions."""
    return conn.cursor(row_factory=tuple_row)


@pytest.fixture(scope="module")
def raw():
    wb = openpyxl.load_workbook(WORKBOOK, read_only=True, data_only=True)
    cat = importer.read_sheet(wb, importer.CATALOG_SHEET, importer.CATALOG_HEADERS)
    ev = importer.read_sheet(wb, importer.EVIDENCE_SHEET, importer.EVIDENCE_HEADERS)
    wb.close()
    return [c for _, c in cat], [e for _, e in ev]


def test_totals(baseline):
    report, _ = baseline
    assert (report["assertions"], report["evidences"]) == (98, 344)
    assert report["warnings"] == []


def test_component_counts(baseline):
    report, _ = baseline
    got = {(c["subject"], c["assessment_type"]): (c["objectives"], c["evidences"]) for c in report["components"]}
    assert got == EXPECTED_COMPONENTS


def test_relationships_and_identifiers(baseline, raw):
    _, conn = baseline
    cat, _ = raw
    assert t(conn).execute("SELECT COUNT(*) FROM evidence e LEFT JOIN assertion a ON a.id = e.assertion_id "
                        "AND a.baseline_version = e.baseline_version WHERE a.id IS NULL").fetchone()[0] == 0
    stored = {r[0] for r in t(conn).execute("SELECT workbook_code FROM assertion WHERE baseline_version = %s", (V,))}
    assert stored == {c["Código"] for c in cat}
    ids = [r[0] for r in t(conn).execute("SELECT id FROM evidence WHERE baseline_version = %s", (V,))]
    assert len(ids) == len(set(ids)) == 344


def test_text_matches_workbook_verbatim(baseline, raw):
    _, conn = baseline
    cat, ev = raw
    for cells in cat:
        row = t(conn).execute(
            "SELECT a.text_es, a.concepts_es, a.check_activity_es, a.source_citation_es, a.numbering_es, "
            "a.planned_items_raw, a.evidence_count, b.name_es FROM assertion a JOIN block b ON b.id = a.block_id "
            "AND b.baseline_version = a.baseline_version WHERE a.workbook_code = %s", (cells["Código"],)).fetchone()
        assert tuple(row) == (
            cells["Afirmación / criterio"], cells["Conceptos detallados"], cells["Actividad de comprobación"],
            cells["Fuente / página"], cells["Numeración"], cells["Ítems previstos"],
            int(cells["Cantidad evidencias"]), cells["Bloque MEP"])
    for cells in ev:
        text = t(conn).execute(
            "SELECT e.text_es FROM evidence e JOIN assertion a ON a.id = e.assertion_id "
            "AND a.baseline_version = e.baseline_version WHERE a.workbook_code = %s AND e.ordinal = %s",
            (cells["Objetivo"], int(cells["N.º"]))).fetchone()[0]
        assert text == cells["Evidencia / criterio verificable"]


def test_no_student_data(baseline):
    _, conn = baseline
    columns = {c[0].lower() for c in t(conn).execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema()")}
    assert len(columns) > 30
    assert not any("logrado" in c for c in columns)
    refs = [r[0] or "" for r in t(conn).execute("SELECT file_ref FROM source_document")]
    assert "PNE-Tracker-2026-workbook.xlsx" in refs  # generic manifest name, not the local file name


def test_every_multiple_choice_objective_is_selectable(baseline, raw):
    _, conn = baseline
    cat, ev = raw
    expected = Counter(e["Objetivo"] for e in ev)
    mc = [c for c in cat if not c["Código"].startswith("EE")]
    assert len(mc) == 78
    for cells in mc:
        sel = select_objectives(conn, V, "single_objective", SUBJECT_CODES[cells["Materia"]], [cells["Código"]])
        assert len(sel.objectives[0]["evidences"]) == expected[cells["Código"]]


def test_multiple_selection_keeps_evidences(baseline, raw):
    _, conn = baseline
    _, ev = raw
    expected = Counter(e["Objetivo"] for e in ev)
    chosen = ["M01", "M07", "M14", "M22"]
    sel = select_objectives(conn, V, "selected_objectives", "matematicas", chosen)
    assert [o["workbook_code"] for o in sel.objectives] == chosen
    assert [len(o["evidences"]) for o in sel.objectives] == [expected[c] for c in chosen]


def test_subject_retrieval_and_rubric_separation(baseline):
    _, conn = baseline
    sizes = {s: len(list_objectives(conn, V, s)) for s in SUBJECT_CODES.values()}
    assert sizes == {"espanol": 8, "matematicas": 22, "ciencias": 19, "estudios_sociales": 29}
    rubric = list_rubric_criteria(conn, V)
    assert len(rubric) == 20 and all(r["workbook_code"].startswith("EE") for r in rubric)
    sim = select_objectives(conn, V, "subject_simulation", "espanol")
    assert all(o["assessment_type"] == "multiple_choice" for o in sim.objectives)


def test_baseline_provenance_labels(baseline):
    _, conn = baseline
    assert {tuple(r) for r in t(conn).execute("SELECT DISTINCT provenance, baseline_status, verification_status FROM assertion")} == {
        ("secondary", "approved", "unverified")}
    assert {tuple(r) for r in t(conn).execute("SELECT DISTINCT provenance, verification_status FROM evidence")} == {("secondary", "unverified")}
