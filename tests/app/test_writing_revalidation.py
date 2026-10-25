"""RCA-004 remediation (T029, ADR-027): quarantine, independent revalidation, reinstatement; test database only."""

from __future__ import annotations

import copy
import json
import uuid

import httpx
import psycopg

from app.llm.usage import MemoryUsageStore
from app.writing import editing, generation, revalidation
from test_writing_editing import FakeLlm as EditFake, SPELLING, catalog, client_for as edit_client, store  # noqa: F401
from test_writing_generation import GOOD, FakeLlm, client_for
from test_writing_tutor import HEADERS, L1, L23, env  # noqa: F401  (env is a fixture)


class Down:
    """Wraps a fake: the given model answers 502 for every chat request."""

    def __init__(self, fake, model="rev/b:free"):
        self.fake, self.model, self.models = fake, model, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/models"):
            self.models.append(json.loads(request.content)["model"])
            if self.models[-1] == self.model:
                return httpx.Response(502, json={"error": {"message": "upstream down"}})
        return self.fake(request)


def stored_l2(catalog, store):
    outcome = generation.generate_exercise(client_for(FakeLlm([GOOD])), MemoryUsageStore(), catalog, store, "L2",
                                           "medium", ["EE03", "EE04"])
    eid = outcome.exercise["exercise_id"]
    store.set_eligibility(eid, "quarantined", "test: review not independent", "RCA-004")
    return eid


def snapshot(store, eid):
    with psycopg.connect(store.url) as conn:
        return [conn.execute(sql, (eid,)).fetchall() for sql in (
            "SELECT record, created_at FROM writing.exercise WHERE exercise_id = %s",
            "SELECT * FROM writing.reference_correction WHERE exercise_id = %s",
            "SELECT request_id, status, checks FROM writing.generation_attempt WHERE exercise_id = %s")]


# ---------------------------------------------------------------- revalidation

def test_l1_exercise_is_reinstated_by_an_independent_review(catalog, store):
    eid = editing.generate_editing_exercise(edit_client(EditFake([SPELLING])), MemoryUsageStore(), catalog, store,
                                            "spelling").exercise["exercise_id"]
    store.set_eligibility(eid, "quarantined", "test", "RCA-004")
    before = snapshot(store, eid)
    assert [r["exercise_id"] for r in store.exercises()] == []
    result = revalidation.revalidate(edit_client(EditFake([SPELLING])), MemoryUsageStore(), catalog, store, eid,
                                     "gen/a:free")
    assert (result["status"], result["reviewer_model"], result["models_called"]) == ("passed", "rev/b:free",
                                                                                     ["rev/b:free"])
    assert result["version"] == "independent-review-1.1+writing-edit-1.1" and result["calls"] == 1
    assert [c["id"] for c in result["checks"]][-1] == "W08" and all(c["status"] == "pass" for c in result["checks"])
    assert store.eligibility(eid) == "eligible" and [r["exercise_id"] for r in store.exercises()] == [eid]
    events = store.eligibility_events(eid)
    assert [e["status"] for e in events] == ["quarantined", "eligible"]
    assert events[-1]["validation_id"] == result["validation_id"]
    [row] = store.validations(eid)
    assert (row["status"], row["generator_model"], row["reviewer_model"], row["tokens_in"]) == (
        "passed", "gen/a:free", "rev/b:free", 1200)
    assert snapshot(store, eid) == before  # record, reference and generation history unchanged


def test_reviewer_outage_keeps_quarantine_and_never_asks_the_generator(catalog, store):
    eid = stored_l2(catalog, store)
    usage = MemoryUsageStore()
    down = Down(FakeLlm([GOOD]))
    result = revalidation.revalidate(client_for(down), usage, catalog, store, eid, "gen/a:free")
    assert result["status"] == "unavailable" and result["reviewer_model"] is None
    assert set(down.models) == {"rev/b:free"} and result["models_called"] == ["rev/b:free"]
    assert result["calls"] >= 1 and all(r["status"] == "error" for r in usage.records)  # failures preserved
    assert store.eligibility(eid) == "quarantined" and store.validations(eid)[0]["status"] == "unavailable"


def test_low_review_or_exhausted_budget_keeps_quarantine(catalog, store):
    eid = stored_l2(catalog, store)
    low = {k: 2 for k in generation.COMPOSE_REVIEW_KEYS} | {"clarity": 1, "notes": "Instrucción ambigua."}
    failed = revalidation.revalidate(client_for(FakeLlm([GOOD], [low])), MemoryUsageStore(), catalog, store, eid,
                                     "gen/a:free")
    assert failed["status"] == "failed" and "clarity" in failed["reasons"][0]
    blocked = revalidation.revalidate(client_for(FakeLlm([GOOD]), max_requests_per_day=0), MemoryUsageStore(),
                                      catalog, store, eid, "gen/a:free")
    assert blocked["status"] == "unavailable" and blocked["calls"] == 0
    unknown = revalidation.revalidate(client_for(FakeLlm([GOOD])), MemoryUsageStore(), catalog, store, eid, None)
    assert unknown["status"] == "unavailable" and unknown["models_called"] == []
    assert store.eligibility(eid) == "quarantined"
    assert [v["status"] for v in store.validations(eid)] == ["failed", "unavailable", "unavailable"]


def test_the_only_other_model_being_the_generator_means_no_review(catalog, store):
    eid = stored_l2(catalog, store)
    down = Down(FakeLlm([GOOD]), model="gen/a:free")
    result = revalidation.revalidate(client_for(down), MemoryUsageStore(), catalog, store, eid, "rev/b:free")
    assert result["status"] == "unavailable" and "rev/b:free" not in down.models  # excluded, not just tried last


# ---------------------------------------------------------------- student side

def test_quarantined_exercise_is_hidden_and_takes_no_new_work(env):
    student, store, _ = env
    eid = L23["introduction_paragraph"]["exercise_id"]
    student.put(f"/api/writing/exercises/{eid}/draft", json={"text": "Mi borrador."})
    store.set_eligibility(eid, "quarantined", "test", "RCA-004")
    listed = student.get("/api/writing/levels/idea_development/exercises").json()["exercises"]
    counts = {lv["code"]: lv["exercise_count"] for lv in student.get("/api/writing/levels").json()["levels"]}
    assert eid not in [e["exercise_id"] for e in listed] and counts["idea_development"] == 0
    assert student.get(f"/api/writing/exercises/{eid}").status_code == 404
    submit = student.post(f"/api/writing/exercises/{eid}/submit", json={"text": "Texto.",
                                                                         "client_request_id": str(uuid.uuid4())})
    assert submit.status_code == 404 and store.submission(eid) is None
    assert store.draft(eid)["text_es"] == "Mi borrador."  # the draft is kept
    store.set_eligibility(eid, "eligible", "test reinstatement", "independent-review-1.0")
    assert student.get(f"/api/writing/exercises/{eid}").json()["draft"]["text"] == "Mi borrador."


def test_submitted_work_on_a_quarantined_exercise_stays_readable(env):
    student, store, _ = env
    eid = L1["exercise_id"]
    student.post(f"/api/writing/exercises/{eid}/submit", json={"text": "Mi corrección.",
                                                                "client_request_id": str(uuid.uuid4())})
    sid = store.submission(eid)["submission_id"]
    student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": {"EE07": 3, "EE08": 2}, "complete": True},
                headers=HEADERS)
    store.set_eligibility(eid, "quarantined", "test", "RCA-004")
    view = student.get(f"/api/writing/exercises/{eid}")
    assert view.status_code == 200 and view.json()["feedback"]["scores"][0]["points"] == 3
    assert "REFERENCIA-SOLO-TUTOR" not in view.text  # the tutor-only reference stays protected
    draft = student.put(f"/api/writing/exercises/{eid}/draft", json={"text": "otro"})
    assert draft.status_code == 409 and draft.json()["error"] == "exercise_unavailable"
    assert sid in [s["submission_id"] for s in student.get("/api/tutor/queue", headers=HEADERS).json()["submissions"]]
    progress = student.get("/api/writing/progress").json()
    assert progress["activity"]["evaluations_completed"] == 1  # history still counts


def test_events_are_append_only_and_idempotent(env):
    _, store, _ = env
    eid = L1["exercise_id"]
    assert store.set_eligibility(eid, "quarantined", "a", "RCA-004")
    assert not store.set_eligibility(eid, "quarantined", "again", "RCA-004")
    assert store.set_eligibility(eid, "eligible", "b", "independent-review-1.0")
    assert [e["status"] for e in store.eligibility_events(eid)] == ["quarantined", "eligible"]


def test_inventory_counts_eligible_exercises_only(env):
    _, store, _ = env
    before = revalidation.inventory(store)
    store.set_eligibility(L1["exercise_id"], "quarantined", "test", "RCA-004")
    after = revalidation.inventory(store)
    assert after["eligible"]["writing_conventions"] == before["eligible"]["writing_conventions"] - 1
    assert after["gap"]["writing_conventions"] == 3 - after["eligible"]["writing_conventions"]
    assert copy.deepcopy(after["required"]) == {"writing_conventions": 3, "idea_development": 3,
                                                "paragraph_writing": 3, "guided_composition": 1}


def test_rerunning_the_quarantine_never_undoes_a_reinstatement(env):
    _, store, _ = env
    affected = [{"exercise_id": L1["exercise_id"], "generator_model": "gen/a:free", "reviewer_model": "gen/a:free"}]
    assert revalidation.quarantine(store, affected)[0]["new_event"]
    store.set_eligibility(L1["exercise_id"], "eligible", "independent review passed", "independent-review-1.1")
    again = revalidation.quarantine(store, affected)
    assert again[0] == {"exercise_id": L1["exercise_id"], "quarantined": False, "new_event": False,
                        "status": "eligible"}
    assert store.eligibility(L1["exercise_id"]) == "eligible"
