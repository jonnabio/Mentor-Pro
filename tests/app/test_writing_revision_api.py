"""Student revision API (T037, ADR-032): "Mejorar mi respuesta" after a completed tutor review."""

from __future__ import annotations

import threading
import uuid

import psycopg
import pytest

from test_writing_guided import SECTIONS, guided_exercise
from test_writing_tutor import HEADERS, L1, L23, REFERENCE, env, sid_for, submit  # noqa: F401  (env is a fixture)

L2 = L23["introduction_paragraph"]
L1_ANSWER = L1["source_text_es"].replace("las niños", "los niños")


def review(student, sid, scores):
    done = student.put(f"/api/tutor/submissions/{sid}/evaluation", headers=HEADERS,
                       json={"scores": scores, "complete": True, "strengths": ["Buen trabajo."],
                             "improvements": ["Agregá una idea más."]})
    assert done.status_code == 200 and done.json()["status"] == "completed", done.text


def reviewed(student, record, text="Mi párrafo de introducción."):
    sid = sid_for(submit(student, record["exercise_id"], text), record["exercise_id"])
    review(student, sid, {c: 2 for c in record["target_criteria"]})
    return sid


def view(student, exercise_id):
    return student.get(f"/api/writing/exercises/{exercise_id}").json()


def start(student, exercise_id):
    return student.post(f"/api/writing/exercises/{exercise_id}/revision")


def history(url):
    """Every stored row of the first attempt's work, to prove a revision never changes it."""
    with psycopg.connect(url) as conn:
        return [conn.execute(f"SELECT to_jsonb(t) FROM writing.{table} t ORDER BY 1").fetchall()
                for table in ("submission", "evaluation", "criterion_score")]


# ---------------------------------------------------------------- when the button is offered

def test_revision_offered_only_after_a_completed_review(env):
    student, _, _ = env
    eid = L2["exercise_id"]
    assert view(student, eid)["revision_attempt"] == {"available": False, "attempt": None}  # not started
    student.put(f"/api/writing/exercises/{eid}/draft", json={"text": "Borrador."})
    assert view(student, eid)["revision_attempt"]["available"] is False
    refused = start(student, eid)
    assert refused.status_code == 409 and refused.json()["error"] == "revision_not_allowed"
    assert refused.json()["message_es"] == "Primero entregá tu respuesta."

    sid = sid_for(submit(student, eid, "Mi párrafo."), eid)
    assert view(student, eid)["revision_attempt"]["available"] is False  # pending review
    student.put(f"/api/tutor/submissions/{sid}/evaluation", headers=HEADERS,
                json={"scores": {L2["target_criteria"][0]: 2}})
    assert view(student, eid)["revision_attempt"]["available"] is False  # review in progress
    refused = start(student, eid)
    assert refused.status_code == 409 and "termine de revisarla" in refused.json()["message_es"]

    review(student, sid, {c: 2 for c in L2["target_criteria"]})
    assert view(student, eid)["revision_attempt"] == {"available": True, "attempt": None}


def test_quarantined_exercise_cannot_be_revised_but_history_stays(env):
    student, store, _ = env
    eid = L2["exercise_id"]
    reviewed(student, L2)
    store.set_eligibility(eid, "quarantined", "self review", "RCA-004")
    data = view(student, eid)
    assert data["revision_attempt"] == {"available": False, "attempt": None}
    assert data["feedback"] is not None and data["submission"]["status"] == "reviewed"  # history readable
    refused = start(student, eid)
    assert refused.status_code == 409 and refused.json()["error"] == "exercise_unavailable"
    assert store.attempts(eid)[-1]["attempt_number"] == 1

    store.set_eligibility(eid, "eligible", "independent review passed", "RCA-004")
    attempt_id = start(student, eid).json()["attempt_id"]
    store.set_eligibility(eid, "quarantined", "self review", "RCA-004")  # quarantined while revising
    data = view(student, eid)["revision_attempt"]
    assert data["attempt"]["attempt_id"] == attempt_id and data["attempt"]["editable"] is False
    for response in (student.put(f"/api/writing/attempts/{attempt_id}/draft", json={"text": "Otra."}),
                     student.post(f"/api/writing/attempts/{attempt_id}/submit",
                                  json={"text": "Otra.", "client_request_id": str(uuid.uuid4())})):
        assert response.status_code == 409 and response.json()["error"] == "exercise_unavailable"
    assert store.attempt_draft(attempt_id)["text_es"] == "Mi párrafo de introducción."


# ---------------------------------------------------------------- start

def test_start_is_idempotent_and_seeds_from_the_submitted_text(env):
    student, store, _ = env
    eid = L2["exercise_id"]
    reviewed(student, L2, "Mi primer párrafo.")
    first = start(student, eid)
    again = start(student, eid)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["attempt_id"] == again.json()["attempt_id"] and again.json()["created"] is False
    attempt = first.json()
    assert attempt["attempt_number"] == 2 and attempt["editable"] is True and attempt["submission"] is None
    assert attempt["draft"]["text"] == "Mi primer párrafo." and attempt["feedback"] is None
    data = view(student, eid)
    assert data["revision_attempt"]["available"] is False
    assert data["revision_attempt"]["attempt"]["attempt_id"] == attempt["attempt_id"]
    assert data["draft"]["text"] == "Mi primer párrafo." and data["submission"]["status"] == "reviewed"
    assert len(store.attempts(eid)) == 2


def test_parallel_starts_create_one_revision(env):
    student, store, _ = env
    eid = L2["exercise_id"]
    reviewed(student, L2)
    ids, barrier = [], threading.Barrier(6)

    def go():
        barrier.wait()
        ids.append(start(student, eid).json()["attempt_id"])

    threads = [threading.Thread(target=go) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(ids)) == 1 and len(store.attempts(eid)) == 2


def test_l1_revision_starts_from_the_correction_not_the_source(env):
    student, _, _ = env
    eid = L1["exercise_id"]
    sid = sid_for(submit(student, eid, L1_ANSWER), eid)
    review(student, sid, {"EE07": 3, "EE08": 2})
    attempt = start(student, eid).json()
    assert attempt["draft"]["text"] == L1_ANSWER and attempt["draft"]["text"] != L1["source_text_es"]
    body = student.get(f"/api/writing/exercises/{eid}").text
    assert REFERENCE["corrected_text_es"] not in body and "corrections" not in body


def test_l4_revision_keeps_the_five_sections(env):
    student, store, _ = env
    record = guided_exercise()
    store.add_exercise(record)
    eid = record["exercise_id"]
    student.post(f"/api/writing/exercises/{eid}/submit",
                 json={"sections": SECTIONS, "client_request_id": str(uuid.uuid4())})
    sid = sid_for(student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"], eid)
    review(student, sid, {c: 3 for c in record["target_criteria"][:6]})
    attempt = start(student, eid).json()
    assert attempt["draft"]["sections"] == SECTIONS
    url = f"/api/writing/attempts/{attempt['attempt_id']}"

    assert student.put(f"{url}/draft", json={"text": "sin partes"}).json()["error"] == "sections_required"
    missing = student.post(f"{url}/submit", json={"sections": {**SECTIONS, "conclusion": ""},
                                                  "client_request_id": str(uuid.uuid4())})
    assert missing.status_code == 422 and "Conclusión" in missing.json()["message_es"]
    split = student.post(f"{url}/submit", json={"sections": {**SECTIONS, "conclusion": "Uno.\n\nDos."},
                                                "client_request_id": str(uuid.uuid4())})
    assert split.json()["error"] == "blank_line_in_paragraph"

    better = {**SECTIONS, "conclusion": "La escuela puede organizar juegos y torneos cada semana."}
    assert student.put(f"{url}/draft", json={"sections": better, "client_seq": 5}).json()["applied"] is True
    done = student.post(f"{url}/submit", json={"sections": better, "client_request_id": str(uuid.uuid4())})
    assert done.status_code == 200 and done.json()["created"] is True
    sub = store.attempt_submission(attempt["attempt_id"])
    assert sub["sections"] == better and sub["paragraph_count"] == 4 and "torneos" in sub["text_es"]
    assert store.submission(eid)["sections"] == SECTIONS  # the first composition is unchanged


# ---------------------------------------------------------------- drafts and submission

def test_attempt_draft_ordering_freezing_and_submit_retry(env):
    student, store, url = env
    eid = L2["exercise_id"]
    reviewed(student, L2, "Mi primer párrafo.")
    before = history(url)
    attempt_id = start(student, eid).json()["attempt_id"]
    draft = f"/api/writing/attempts/{attempt_id}/draft"

    saved = student.put(draft, json={"text": "Versión nueva dos.", "client_seq": 20}).json()
    assert saved["applied"] is True and saved["client_seq"] == 20 and saved["word_count"] == 3
    stale = student.put(draft, json={"text": "Versión vieja.", "client_seq": 10}).json()
    assert stale["applied"] is False and stale["client_seq"] == 20
    assert view(student, eid)["revision_attempt"]["attempt"]["draft"]["text"] == "Versión nueva dos."

    request_id = str(uuid.uuid4())
    first = student.post(f"/api/writing/attempts/{attempt_id}/submit",
                         json={"text": "Versión final.", "client_request_id": request_id})
    retry = student.post(f"/api/writing/attempts/{attempt_id}/submit",
                         json={"text": "Otra cosa.", "client_request_id": str(uuid.uuid4())})
    assert first.json()["created"] is True and retry.json()["created"] is False
    assert retry.json()["submitted_at"] == first.json()["submitted_at"]
    assert first.json()["status_es"] == "Pendiente de revisión del tutor"
    frozen = student.put(draft, json={"text": "Tarde.", "client_seq": 99})
    assert frozen.status_code == 409 and frozen.json()["error"] == "already_submitted"
    empty = student.post(f"/api/writing/attempts/{attempt_id}/submit",
                         json={"text": " ", "client_request_id": str(uuid.uuid4())})
    assert empty.status_code == 422 and empty.json()["error"] == "empty_text"  # as on the exercise route

    revision = view(student, eid)["revision_attempt"]
    assert revision["attempt"]["submission"]["status"] == "pending_review"
    assert revision["attempt"]["editable"] is False and revision["available"] is False
    assert store.attempt_submission(attempt_id)["text_es"] == "Versión final."
    assert history(url)[1:] == before[1:]  # evaluations and scores untouched
    first_sub = [row for row in history(url)[0] if row[0]["attempt_id"] != attempt_id]
    assert first_sub == before[0]  # the first submission is byte-identical
    refused = start(student, eid)
    assert refused.status_code == 409 and refused.json()["message_es"] == "Ya entregaste tu mejora de este ejercicio."
    # The tutor screens (T038) are unchanged; the store queue already tells the attempts apart.
    assert sorted(s["attempt_number"] for s in store.tutor_queue() if s["exercise_id"] == eid) == [1, 2]


def test_empty_revision_cannot_be_submitted(env):
    student, _, _ = env
    reviewed(student, L2)
    attempt_id = start(student, L2["exercise_id"]).json()["attempt_id"]
    empty = student.post(f"/api/writing/attempts/{attempt_id}/submit",
                         json={"text": "  ", "client_request_id": str(uuid.uuid4())})
    assert empty.status_code == 422 and empty.json()["error"] == "empty_text"


# ---------------------------------------------------------------- isolation of the two attempts

@pytest.mark.parametrize("attempt_id,status,error", [
    ("ATT-no-such-attempt", 404, "attempt_not_found"),
    ("not-an-attempt", 422, "invalid_attempt"),
    ("ATT-" + "x" * 90, 422, "invalid_attempt"),
])
def test_unknown_or_malformed_attempts_are_refused(env, attempt_id, status, error):
    student, _, _ = env
    for response in (student.put(f"/api/writing/attempts/{attempt_id}/draft", json={"text": "x"}),
                     student.post(f"/api/writing/attempts/{attempt_id}/submit",
                                  json={"text": "x", "client_request_id": str(uuid.uuid4())})):
        assert response.status_code == status and response.json()["error"] == error


def test_attempt_routes_refuse_attempt_one_and_exercise_routes_never_write_the_revision(env):
    student, store, _ = env
    eid = L2["exercise_id"]
    reviewed(student, L2, "Mi primer párrafo.")
    first_id = store.attempts(eid)[0]["attempt_id"]
    for response in (student.put(f"/api/writing/attempts/{first_id}/draft", json={"text": "x"}),
                     student.post(f"/api/writing/attempts/{first_id}/submit",
                                  json={"text": "x", "client_request_id": str(uuid.uuid4())})):
        assert response.status_code == 409 and response.json()["error"] == "attempt_routes_are_for_revisions"

    attempt_id = start(student, eid).json()["attempt_id"]
    old_client = student.put(f"/api/writing/exercises/{eid}/draft", json={"text": "Cliente viejo."})
    assert old_client.status_code == 409 and old_client.json()["error"] == "already_submitted"
    resubmit = student.post(f"/api/writing/exercises/{eid}/submit",
                            json={"text": "Cliente viejo.", "client_request_id": str(uuid.uuid4())})
    assert resubmit.json()["created"] is False  # returns the first submission
    assert store.attempt_draft(attempt_id)["text_es"] == "Mi primer párrafo."
    assert store.attempt_submission(attempt_id) is None


def test_progress_shape_unchanged_by_a_revision(env):
    student, _, _ = env
    reviewed(student, L2)
    before = student.get("/api/writing/progress").json()
    attempt_id = start(student, L2["exercise_id"]).json()["attempt_id"]
    student.post(f"/api/writing/attempts/{attempt_id}/submit",
                 json={"text": "Versión final.", "client_request_id": str(uuid.uuid4())})
    after = student.get("/api/writing/progress").json()
    assert set(after) == set(before)  # counting attempts apart from exercises is T039
