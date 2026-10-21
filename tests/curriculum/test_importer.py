"""Importer behaviour on a synthetic workbook: fidelity, idempotency, fail-closed checks."""

import pytest

from workbook_fixtures import catalog_rows, evidence_rows, query
from curriculum import importer


def rows(db, sql, *args):
    return query(db, sql, *args)


def test_import_counts_and_ids(build, db):
    workbook, manifest = build()
    report = importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    assert report["status"] == "imported"
    assert (report["assertions"], report["evidences"], report["blocks"]) == (5, 6, 4)
    ids = dict(rows(db, "SELECT workbook_code, id FROM assertion"))
    assert ids["M01"] == "PNE2026-PRI-MAT-SUM-B1-A1"
    assert ids["M03"] == "PNE2026-PRI-MAT-SUM-B2-A1"
    assert ids["EE01"] == "PNE2026-PRI-ESP-PE-B1-A1"
    assert ("PNE2026-PRI-MAT-SUM-B1-A1-E2",) in rows(db, "SELECT id FROM evidence")


def test_text_is_stored_verbatim(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    concepts, activity, citation, block = rows(
        db, "SELECT a.concepts_es, a.check_activity_es, a.source_citation_es, b.name_es FROM assertion a "
            "JOIN block b ON b.id = a.block_id AND b.baseline_version = a.baseline_version WHERE workbook_code = 'EE01'")[0]
    assert (concepts, activity, citation, block) == (
        "Tilde diacrítica.", "Revisá tu texto.", "rúbrica MEP 2026; pág. PDF 4.", "Convenciones lingüísticas (15 %)")
    assert rows(db, "SELECT concepts_es FROM assertion WHERE workbook_code = 'M01'")[0][0] == "Valor posicional.\n• Lectura y escritura."
    # Double space inside the evidence text is preserved.
    assert ("Lee números  mayores que 100 000.",) in rows(db, "SELECT text_es FROM evidence")


def test_parsed_fields(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    m01 = rows(db, "SELECT source_table, source_page, planned_items, planned_items_raw, evidence_count, "
                   "provenance, baseline_status, verification_status FROM assertion WHERE workbook_code = 'M01'")[0]
    assert m01 == ("Tabla 3", 18, 3, "3 ítem(s) previsto(s)", 2, "secondary", "approved", "unverified")
    ee = rows(db, "SELECT planned_items, source_document_id FROM assertion WHERE workbook_code = 'EE01'")[0]
    assert ee == (None, "MEP-RUBRICA-PE-2026")
    assert rows(db, "SELECT weight_pct, assessment_type FROM block WHERE name_es LIKE 'Convenciones%%'")[0] == (15, "written_rubric")


def test_no_student_data_is_stored(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    columns = {c[0].lower() for c in rows(
        db, "SELECT column_name FROM information_schema.columns WHERE table_schema = %s", db.schema)}
    assert len(columns) > 30
    assert not any("logrado" in c or "student" in c or "achieved" in c for c in columns)
    file_ref = rows(db, "SELECT file_ref FROM source_document WHERE kind = 'workbook'")[0][0]
    assert file_ref == "synthetic-workbook.xlsx"


def test_reimport_is_idempotent(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    before = rows(db, "SELECT * FROM evidence ORDER BY id")
    again = importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    assert again["status"] == "unchanged"
    assert rows(db, "SELECT * FROM evidence ORDER BY id") == before


def test_changed_workbook_needs_new_version(build, db):
    workbook, manifest = build()
    importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    cat = catalog_rows()
    cat[0][4] = "Texto revisado."
    workbook2, _ = build(cat=cat, ev=[r if r[0] != "M01" else r[:5] + ["Texto revisado."] + r[6:] for r in evidence_rows()])
    with pytest.raises(importer.WorkbookImportError, match="different workbook"):
        importer.import_workbook(workbook2, db.url, "TEST-v1", manifest, db.schema)
    assert importer.import_workbook(workbook2, db.url, "TEST-v2", manifest, db.schema)["status"] == "imported"
    assert rows(db, "SELECT COUNT(DISTINCT baseline_version) FROM assertion")[0][0] == 2


def test_unregistered_workbook_is_refused(build, db):
    workbook, manifest = build(register_it=False)
    with pytest.raises(importer.WorkbookImportError, match="not registered"):
        importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)


def assert_fails_and_writes_nothing(build, db, match, **kwargs):
    workbook, manifest = build(**kwargs)
    with pytest.raises(importer.WorkbookImportError) as info:
        importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)
    assert any(match in p for p in info.value.problems), info.value.problems
    assert rows(db, "SELECT COUNT(*) FROM assertion")[0][0] == 0
    assert rows(db, "SELECT COUNT(*) FROM source_document")[0][0] == 0


def test_orphan_evidence_fails(build, db):
    ev = evidence_rows() + [["M99", 1.0, "Huérfana.", "Matemáticas", False, "x", "Números", "y"]]
    assert_fails_and_writes_nothing(build, db, "not in 07 Catálogo", ev=ev)


def test_inconsistent_copy_column_fails(build, db):
    ev = evidence_rows()
    ev[2][6] = "Geometría"
    assert_fails_and_writes_nothing(build, db, "'Bloque temático' differs", ev=ev)


def test_evidence_count_mismatch_fails(build, db):
    cat = catalog_rows()
    cat[0][8] = 3.0
    assert_fails_and_writes_nothing(build, db, "Cantidad evidencias 3 != 2", cat=cat)


def test_numbering_gap_fails(build, db):
    ev = evidence_rows()
    ev[1][1] = 3.0
    assert_fails_and_writes_nothing(build, db, "not 1..n", ev=ev)


def test_duplicate_code_fails(build, db):
    cat = catalog_rows() + [catalog_rows()[1]]
    assert_fails_and_writes_nothing(build, db, "duplicate objective code M02", cat=cat)


def test_bad_citation_fails(build, db):
    cat = catalog_rows()
    cat[1][7] = "Guía didáctica, p. 4"
    assert_fails_and_writes_nothing(build, db, "unparseable source citation", cat=cat)


def test_subject_prefix_mismatch_fails(build, db):
    cat = catalog_rows()
    cat[3][1] = "Ciencias"
    assert_fails_and_writes_nothing(build, db, "implies 'Español'", cat=cat)


def test_rubric_with_item_count_fails(build, db):
    cat = catalog_rows()
    cat[4][9] = "2 ítem(s) previsto(s)"
    assert_fails_and_writes_nothing(build, db, "rubric code EE01", cat=cat)


def test_changed_headers_fail(build, db):
    headers = list(importer.CATALOG_HEADERS)
    headers[4] = "Afirmación"
    assert_fails_and_writes_nothing(build, db, "header row 4", cat_headers=headers)


def test_concurrent_imports_of_same_version_do_not_race(build, db):
    from concurrent.futures import ThreadPoolExecutor

    workbook, manifest = build()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(
            lambda _: importer.import_workbook(workbook, db.url, "TEST-v1", manifest, db.schema)["status"], range(3)))
    assert sorted(results) == ["imported", "unchanged", "unchanged"]
    assert rows(db, "SELECT COUNT(*) FROM evidence")[0][0] == 6


def test_database_url_from_environment_or_env_file(tmp_path, monkeypatch):
    from curriculum import db as dbmod

    env_file = tmp_path / ".env"
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(dbmod.ConfigurationError):
        dbmod.database_url(env_file)
    env_file.write_text("OTHER=1\nDATABASE_URL=postgresql://u@h:5432/from_file\n", encoding="utf-8")
    assert dbmod.database_url(env_file).endswith("/from_file")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h:5432/from_env")
    assert dbmod.database_url(env_file).endswith("/from_env")


def test_cli_never_prints_connection_string(build, monkeypatch, capsys):
    workbook, manifest = build()
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:s3cret@127.0.0.1:1/nowhere")
    code = importer.main(["--workbook", str(workbook), "--manifest", str(manifest)])
    out = capsys.readouterr().out
    assert code == 2 and "s3cret" not in out and "OperationalError" in out


def test_invalid_schema_name_is_rejected():
    from curriculum import db as dbmod

    with pytest.raises(ValueError):
        dbmod.connect("postgresql://unused", "bad; DROP SCHEMA public")
