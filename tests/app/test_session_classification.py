"""T017 classification script: refuses mismatches, applies idempotently, rolls back (test database only)."""

from __future__ import annotations

import sys
import uuid

import psycopg
import pytest
from psycopg.rows import dict_row

from conftest import SYNTHETIC
from workbook_fixtures import REPO_ROOT

sys.path.insert(0, str(REPO_ROOT / "scripts" / "dev"))
import classify_sessions as cs  # noqa: E402

from app.practice.store import PracticeStore  # noqa: E402


@pytest.fixture()
def sessions(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    store = PracticeStore(url)
    ids = []
    for _ in range(3):
        session, _ = store.create_or_get(str(uuid.uuid4()), SYNTHETIC, {
            "subject": "matematicas", "scope": "selected_objectives", "objective_codes": [str(uuid.uuid4())],
            "difficulty": "medium", "question_count": 5}, [])
        ids.append(session["session_id"])
    manifest = dict(zip(ids, ({"class": "confirmed_test", "answers": 0}, {"class": "probable_test", "answers": 0},
                              {"class": "presumed_student", "answers": 0})))
    yield url, manifest
    with psycopg.connect(url, autocommit=True) as conn:
        for table in ("classification_audit", "session_classification", "session"):
            conn.execute(f"DELETE FROM practice.{table} WHERE session_id = ANY(%s)", (ids,))


def classes(url, ids):
    with psycopg.connect(url, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT session_id, classification, audit_ref FROM practice.session_classification "
                            "WHERE session_id = ANY(%s)", (list(ids),)).fetchall()
        audit = conn.execute("SELECT action FROM practice.classification_audit WHERE session_id = ANY(%s) "
                             "ORDER BY audit_id", (list(ids),)).fetchall()
    return {r["session_id"]: r["classification"] for r in rows}, [a["action"] for a in audit]


def test_check_refuses_changed_or_unknown_sessions():
    manifest = {"a": {"class": "confirmed_test", "answers": 2}}
    assert any("missing" in p for p in cs.check({}, manifest))
    assert any("!= manifest" in p for p in cs.check({"a": {"class": "probable_test", "answers": 2}}, manifest))
    assert any("not in the manifest" in p for p in cs.check({**{"a": manifest["a"]}, "b": manifest["a"]}, manifest))
    assert any("approved" in p for p in cs.check({"a": manifest["a"]}, manifest))  # totals differ from PO decision


def test_apply_is_idempotent_and_rollback_restores_student_status(sessions):
    url, manifest = sessions
    with psycopg.connect(url, row_factory=dict_row) as conn:
        assert cs.apply(conn, manifest) == {"inserted": 3, "unchanged": 0}
        assert cs.apply(conn, manifest) == {"inserted": 0, "unchanged": 3}
    got, audit = classes(url, manifest)
    assert sorted(got.values()) == ["automated_test", "quarantined", "student"] and audit == ["classify"] * 3
    with psycopg.connect(url, row_factory=dict_row) as conn:
        assert cs.rollback(conn, cs.AUDIT_REF) >= 3
    got, audit = classes(url, manifest)
    assert got == {} and audit == ["classify"] * 3 + ["rollback"] * 3


def test_apply_refuses_conflicting_classification_and_writes_nothing(sessions):
    url, manifest = sessions
    first = next(iter(manifest))
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO practice.session_classification (session_id, classification, reason, audit_ref) "
                     "VALUES (%s, 'student', 'manual', 'other')", (first,))
    with psycopg.connect(url, row_factory=dict_row) as conn, pytest.raises(SystemExit, match="already classified"):
        cs.apply(conn, manifest)
    got, audit = classes(url, manifest)
    assert got == {first: "student"} and audit == []  # transaction rolled back
