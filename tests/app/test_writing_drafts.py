"""Reliable draft saving (T030, ADR-028): ordering, failures, restart, immutability; test database only."""

from __future__ import annotations

import uuid

import psycopg
from fastapi.testclient import TestClient

from app.main import create_app
from conftest import SYNTHETIC
from test_writing_guided import SECTIONS, guided_exercise
from test_writing_tutor import L1, L23, env  # noqa: F401  (env is a fixture)

L2 = L23["introduction_paragraph"]["exercise_id"]


def url(eid):
    return f"/api/writing/exercises/{eid}"


def test_a_delayed_older_save_never_overwrites_newer_text(env):
    student, store, _ = env
    newer = student.put(f"{url(L2)}/draft", json={"text": "Texto nuevo y completo.", "client_seq": 2000}).json()
    older = student.put(f"{url(L2)}/draft", json={"text": "Texto viejo.", "client_seq": 1000}).json()
    same = student.put(f"{url(L2)}/draft", json={"text": "Repetido.", "client_seq": 2000}).json()
    assert newer["applied"] and not older["applied"] and not same["applied"]
    assert older["client_seq"] == 2000
    draft = student.get(url(L2)).json()["draft"]
    assert (draft["text"], draft["client_seq"]) == ("Texto nuevo y completo.", 2000)
    assert student.put(f"{url(L2)}/draft", json={"text": "Más nuevo.", "client_seq": 2001}).json()["applied"]
    assert store.draft(L2)["text_es"] == "Más nuevo."
    # A save without a sequence (older clients) still saves and keeps the stored sequence.
    assert student.put(f"{url(L2)}/draft", json={"text": "Sin secuencia."}).json()["applied"]
    assert store.draft(L2)["client_seq"] == 2001


def test_guided_sections_keep_their_order_and_revision(env):
    student, store, _ = env
    record = guided_exercise()
    store.add_exercise(record)
    eid = record["exercise_id"]
    student.put(f"{url(eid)}/draft", json={"sections": SECTIONS, "client_seq": 50})
    student.put(f"{url(eid)}/draft", json={"sections": {**SECTIONS, "conclusion": ""}, "client_seq": 40})
    draft = store.draft(eid)
    assert draft["sections"] == SECTIONS and draft["exercise_revision"] == 1


def test_a_database_failure_keeps_the_earlier_draft(env, monkeypatch):
    student, store, _ = env
    student.put(f"{url(L2)}/draft", json={"text": "Borrador válido.", "client_seq": 10})
    live = student.app.state.writing.get()

    def down(*args, **kwargs):
        raise psycopg.OperationalError("connection lost")

    monkeypatch.setattr(live, "save_draft", down)
    failed = student.put(f"{url(L2)}/draft", json={"text": "Texto que no se guardó.", "client_seq": 11})
    assert failed.status_code == 503 and failed.json()["error"] == "save_failed"
    monkeypatch.setattr(live, "exercises", down)
    assert student.put(f"{url(L2)}/draft", json={"text": "x", "client_seq": 12}).status_code == 503
    monkeypatch.undo()
    assert store.draft(L2)["text_es"] == "Borrador válido."
    retried = student.put(f"{url(L2)}/draft", json={"text": "Texto que no se guardó.", "client_seq": 13}).json()
    assert retried["applied"] and store.draft(L2)["text_es"] == "Texto que no se guardó."


def test_drafts_survive_a_server_restart(env, synthetic_client):
    student, _, _ = env
    student.put(f"{url(L1['exercise_id'])}/draft", json={"text": "Corrección en curso.", "client_seq": 7})
    db_url, schema = synthetic_client.app.state.catalog_target
    restarted = TestClient(create_app(db_url, schema, SYNTHETIC))
    draft = restarted.get(url(L1["exercise_id"])).json()["draft"]
    assert (draft["text"], draft["client_seq"]) == ("Corrección en curso.", 7)


def test_submitted_work_is_immutable_and_never_duplicated(env):
    student, store, db_url = env
    eid = L1["exercise_id"]
    student.put(f"{url(eid)}/draft", json={"text": "Antes de entregar.", "client_seq": 5})
    first = student.post(f"{url(eid)}/submit", json={"text": "Entregado.", "client_request_id": str(uuid.uuid4())})
    again = student.post(f"{url(eid)}/submit", json={"text": "Otro.", "client_request_id": str(uuid.uuid4())})
    late = student.put(f"{url(eid)}/draft", json={"text": "Guardado tardío.", "client_seq": 99})
    assert first.json()["created"] and not again.json()["created"]
    assert late.status_code == 409 and late.json()["error"] == "already_submitted"
    assert store.submission(eid)["text_es"] == "Entregado." and store.draft(eid)["text_es"] == "Entregado."
    with psycopg.connect(db_url) as conn:
        assert conn.execute("SELECT COUNT(*) FROM writing.submission WHERE exercise_id = %s",
                            (eid,)).fetchone()[0] == 1
