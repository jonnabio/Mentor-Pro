"""Tutor re-evaluation of revision submissions (T038, ADR-032): identification, context, immutability, feedback."""

from __future__ import annotations

import uuid

import psycopg

from app.tutor_main import create_tutor_app
from app.writing import contracts
from test_tutor_service import GATEWAY, TOKEN as SERVICE_TOKEN, call
from test_writing_guided import SECTIONS, guided_exercise
from test_writing_revision_api import L2, history, review, reviewed, start, view
from test_writing_tutor import HEADERS, L1, REFERENCE, env, sid_for, submit  # noqa: F401  (env is a fixture)

L1_ANSWER = L1["source_text_es"].replace("las niños", "los niños")


def revise(student, exercise_id, text=None, sections=None):
    """Start and submit the improved version; returns its submission id from the tutor queue."""
    attempt_id = start(student, exercise_id).json()["attempt_id"]
    body = {"client_request_id": str(uuid.uuid4()), **({"sections": sections} if sections else {"text": text})}
    assert student.post(f"/api/writing/attempts/{attempt_id}/submit", json=body).status_code == 200
    queue = student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"]
    return next(s["submission_id"] for s in queue if s["exercise_id"] == exercise_id and s["attempt_number"] == 2)


def test_queue_and_detail_identify_the_revision_with_its_context(env):
    student, _, _ = env
    eid = L2["exercise_id"]
    first_sid = reviewed(student, L2, "Mi primer párrafo.")
    sid = revise(student, eid, "Mi párrafo mejorado con una idea más.")
    queue = student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"]
    mine = sorted((s["attempt_number"], s["status"]) for s in queue if s["exercise_id"] == eid)
    assert mine == [(1, "completed"), (2, "pending")]

    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert detail["attempt_number"] == 2 and detail["student_text"] == "Mi párrafo mejorado con una idea más."
    previous = detail["previous"]
    assert previous["submission_id"] == first_sid and previous["student_text"] == "Mi primer párrafo."
    assert previous["evaluation"]["status"] == "completed" and previous["evaluation"]["evaluated_at"]
    assert previous["evaluation"]["feedback_es"]["improvements"] == ["Agregá una idea más."]
    for score in previous["evaluation"]["scores"]:
        assert score["points"] == 2 and score["descriptor_es"] == contracts.descriptor(score["criterion"], 2)
    # The same official rubric and the same pinned exercise revision as the first attempt.
    assert [c["code"] for c in detail["criteria"]] == L2["target_criteria"] and detail["evaluation"] is None
    assert detail["rubric"]["rubric_sha256"] == contracts.rubric()["source"]["file_sha256"]
    assert detail["exercise_revision"] == student.get(f"/api/tutor/submissions/{first_sid}",
                                                      headers=HEADERS).json()["exercise_revision"]
    first = student.get(f"/api/tutor/submissions/{first_sid}", headers=HEADERS).json()
    assert first["attempt_number"] == 1 and first["previous"] is None


def test_new_evaluation_attaches_to_the_revision_only_and_reaches_the_student(env):
    student, _, url = env
    eid = L2["exercise_id"]
    first_sid = reviewed(student, L2, "Mi primer párrafo.")
    before = history(url)
    sid = revise(student, eid, "Mi párrafo mejorado.")
    assert view(student, eid)["revision_attempt"]["attempt"]["feedback"] is None  # not reviewed yet

    scores = {c: 3 for c in L2["target_criteria"]}
    partial = student.put(f"/api/tutor/submissions/{sid}/evaluation", headers=HEADERS,
                          json={"scores": {L2["target_criteria"][0]: 4}})
    assert partial.json()["status"] == "in_progress"
    assert view(student, eid)["revision_attempt"]["attempt"]["feedback"] is None  # in progress stays hidden
    done = student.put(f"/api/tutor/submissions/{sid}/evaluation", headers=HEADERS,
                       json={"scores": scores, "complete": True, "strengths": ["Agregaste la segunda idea."]})
    assert done.json()["status"] == "completed"
    again = student.put(f"/api/tutor/submissions/{first_sid}/evaluation", headers=HEADERS,
                        json={"scores": scores, "complete": True})
    assert again.status_code == 409 and again.json()["error"] == "evaluation_completed"  # first stays locked

    with psycopg.connect(url) as conn:
        rows = conn.execute("""SELECT s.submission_id, a.attempt_number, v.status FROM writing.evaluation v
                               JOIN writing.submission s USING (submission_id)
                               JOIN writing.student_attempt a USING (attempt_id)
                               WHERE s.exercise_id = %s ORDER BY a.attempt_number""", (eid,)).fetchall()
    assert rows == [(first_sid, 1, "completed"), (sid, 2, "completed")]
    after = history(url)
    first_rows = [[r for r in table if first_sid in str(r[0])] for table in after]
    assert first_rows[0] == [r for r in before[0] if first_sid in str(r[0])]  # first submission identical
    assert [r for r in after[1] if first_sid in str(r[0])] == before[1]  # first evaluation identical
    assert all(r in after[2] for r in before[2])  # first criterion scores identical

    data = view(student, eid)
    revision = data["revision_attempt"]["attempt"]
    assert revision["submission"]["status"] == "reviewed" and revision["submission"]["status_es"] == \
        "Revisado por el tutor"
    assert [s["points"] for s in revision["feedback"]["scores"]] == [3] * len(scores)
    assert revision["feedback"]["strengths_es"] == ["Agregaste la segunda idea."]
    assert [s["points"] for s in data["feedback"]["scores"]] == [2] * len(scores)  # first review unchanged
    assert "Agregá una idea más." in data["feedback"]["improvements_es"]


def test_l1_revision_keeps_the_reference_on_the_tutor_side_only(env):
    student, _, _ = env
    eid = L1["exercise_id"]
    review(student, sid_for(submit(student, eid, L1_ANSWER), eid), {"EE07": 3, "EE08": 2})
    sid = revise(student, eid, L1_ANSWER + " Ahora sin errores.")
    detail = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()
    assert detail["reference"]["corrected_text_es"] == REFERENCE["corrected_text_es"]
    assert detail["previous"]["student_text"] == L1_ANSWER
    body = student.get(f"/api/writing/exercises/{eid}").text
    assert REFERENCE["corrected_text_es"] not in body and "corrections" not in body


def test_l4_revision_shows_both_sets_of_sections(env):
    student, store, _ = env
    record = guided_exercise()
    store.add_exercise(record)
    eid = record["exercise_id"]
    student.post(f"/api/writing/exercises/{eid}/submit",
                 json={"sections": SECTIONS, "client_request_id": str(uuid.uuid4())})
    review(student, sid_for(student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"], eid),
           {c: 3 for c in record["target_criteria"][:6]})
    better = {**SECTIONS, "conclusion": "La escuela puede organizar juegos y torneos."}
    detail = student.get(f"/api/tutor/submissions/{revise(student, eid, sections=better)}", headers=HEADERS).json()
    assert {s["key"]: s["text_es"] for s in detail["sections"]} == better
    assert {s["key"]: s["text_es"] for s in detail["previous"]["sections"]} == SECTIONS
    assert sum(c["optional"] for c in detail["criteria"]) == 12  # optional EE07-EE18 as before


def test_tutor_service_boundary_unchanged_for_revisions(env):
    student, _, url = env
    reviewed(student, L2)
    sid = revise(student, L2["exercise_id"], "Mejorado.")
    tutor = create_tutor_app(url, SERVICE_TOKEN, GATEWAY)
    good = {"X-Tutor-Token": SERVICE_TOKEN}
    ok = call(tutor, GATEWAY, f"/api/tutor/submissions/{sid}", good)
    assert ok.status_code == 200 and ok.json()["previous"]["evaluation"]["status"] == "completed"
    assert call(tutor, GATEWAY, f"/api/tutor/submissions/{sid}").status_code == 403  # no token
    assert call(tutor, "192.168.50.20", f"/api/tutor/submissions/{sid}", good).status_code == 403  # not allowed
    assert call(tutor, GATEWAY, f"/api/writing/exercises/{L2['exercise_id']}", good).status_code == 404
    assert student.get(f"/api/tutor/submissions/{sid}").status_code == 403  # student side: no token
