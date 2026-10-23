"""Student practice sessions API (T010, ADR-013) with an injected set runner (no OpenRouter)."""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.generation.practice_set import PracticeSetResult, SlotResult
from app.main import create_app
from app.practice.routes import PracticeService
from app.practice.store import PracticeStore
from conftest import SYNTHETIC

KEYS = "BCDAB"


def fake_item(slot: SlotResult) -> dict:
    return {
        "item_id": f"Q-{slot.evidence_id}-{slot.slot}",
        "stimulus": {"type": "text", "text": f"Situación {slot.slot} en la feria de la escuela."},
        "stem": f"¿Cuál es la respuesta de la pregunta {slot.slot}?",
        "options": [{"label": label, "text": f"Opción {label}{slot.slot}"} for label in "ABCD"],
        "answer_key": KEYS[slot.slot - 1],
        "explanation": f"Explicación secreta {slot.slot}.",
        "distractor_rationales": {},
        "source_refs": [{"record_id": slot.evidence_id, "excerpt": f"Evidencia de {slot.evidence_id}"}],
    }


class FakeRunner:
    """accepted: how many slots succeed; stop_reason for partial/failed; raise_error; gate holds the job."""

    def __init__(self, accepted=None, stop_reason=None, raise_error=False, gate=None):
        self.accepted, self.stop_reason, self.raise_error, self.gate = accepted, stop_reason, raise_error, gate
        self.calls = 0

    def __call__(self, session, on_slot_done):
        self.calls += 1
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.raise_error:
            raise RuntimeError("boom")
        slots = [SlotResult(s["slot"], row["workbook_code"], s["evidence_id"], s["evidence_ordinal"],
                            s["difficulty"]) for row in session["allocation"] for s in row["slots"]]
        limit = len(slots) if self.accepted is None else self.accepted
        for index, slot in enumerate(slots):
            if index < limit:
                slot.status, slot.item, slot.request_id = "accepted", fake_item(slot), f"req-{index}"
            else:
                slot.status = "failed"
            on_slot_done(slot)
        complete = limit == len(slots)
        return PracticeSetResult(f"set-{uuid.uuid4().hex[:16]}", session["subject"],
                                 "complete" if complete else "partial", None if complete else self.stop_reason,
                                 slots, [], 1)


def practice_client(synthetic_client, runner):
    url, schema = synthetic_client.app.state.catalog_target
    return TestClient(create_app(url, schema, SYNTHETIC, practice_runner=runner))


def request_body(**overrides):
    body = {"subject": "matematicas", "scope": "selected_objectives", "objective_codes": ["M02", "M01"],
            "difficulty": "medium", "question_count": 5, "client_request_id": str(uuid.uuid4())}
    return {**body, **overrides}


def wait_ready(client, session_id, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/practice/sessions/{session_id}").json()
        if data["status"] not in ("queued", "running"):
            return data
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def start(client, **overrides):
    response = client.post("/api/practice/sessions", json=request_body(**overrides))
    assert response.status_code == 202, response.json()
    return response.json()


def test_complete_practice_flow_hides_keys_until_answered(synthetic_client):
    client = practice_client(synthetic_client, FakeRunner())
    created = start(client)
    assert created["created"] is True and created["status"] in ("queued", "running")
    data = wait_ready(client, created["session_id"])
    assert data["status"] == "complete" and data["slots_done"] == 5
    assert [q["slot"] for q in data["questions"]] == [1, 2, 3, 4, 5]
    assert [q["objective_code"] for q in data["questions"]] == ["M01", "M01", "M01", "M02", "M02"]
    raw = json.dumps(data, ensure_ascii=False)
    assert "answer_key" not in raw and "Explicación secreta" not in raw and "correct_label" not in raw
    assert data["summary"] is None

    sid = data["session_id"]
    wrong = client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 1, "label": "A"}).json()
    assert wrong["correct"] is False and wrong["correct_label"] == "B" and wrong["already_answered"] is False
    assert wrong["explanation"] == "Explicación secreta 1."
    right = client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 2, "label": "C"}).json()
    assert right["correct"] is True

    # After answering, the revealed feedback survives a refresh, unanswered questions stay hidden.
    data = client.get(f"/api/practice/sessions/{sid}").json()
    assert data["questions"][0]["answered"] and data["questions"][0]["correct_label"] == "B"
    assert "correct_label" not in data["questions"][2] and "explanation" not in data["questions"][2]

    for slot, label in ((3, "D"), (4, "A"), (5, "C")):
        last = client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": slot, "label": label}).json()
    summary = last["summary"]
    assert (summary["answered"], summary["correct"], summary["incorrect"], summary["percentage"]) == (5, 3, 2, 60)
    assert [o["code"] for o in summary["objectives"]] == ["M01", "M02"]
    assert sum(e["total"] for o in summary["objectives"] for e in o["evidences"]) == 5


def test_repeated_submission_keeps_the_first_answer(synthetic_client):
    client = practice_client(synthetic_client, FakeRunner())
    sid = wait_ready(client, start(client)["session_id"])["session_id"]
    first = client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 1, "label": "A"}).json()
    again = client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 1, "label": "B"}).json()
    assert first["correct"] is False and first["already_answered"] is False
    assert again["already_answered"] is True and again["chosen_label"] == "A" and again["correct"] is False


def test_duplicate_requests_create_one_job(synthetic_client):
    gate = threading.Event()
    runner = FakeRunner(gate=gate)
    client = practice_client(synthetic_client, runner)
    body = request_body()
    first = client.post("/api/practice/sessions", json=body).json()
    same_request = client.post("/api/practice/sessions", json=body).json()
    same_config = client.post("/api/practice/sessions", json={**body, "client_request_id": str(uuid.uuid4())}).json()
    assert same_request["session_id"] == same_config["session_id"] == first["session_id"]
    assert same_request["created"] is False and same_config["created"] is False
    gate.set()
    wait_ready(client, first["session_id"])
    assert runner.calls == 1
    # Once finished, the same configuration may be generated again.
    assert start(client)["session_id"] != first["session_id"]


def test_parallel_duplicate_clicks_create_one_job(synthetic_client):
    gate = threading.Event()
    runner = FakeRunner(gate=gate)
    client = practice_client(synthetic_client, runner)
    body = request_body(objective_codes=["M03", "M02"])
    results = []
    threads = [threading.Thread(target=lambda: results.append(
        client.post("/api/practice/sessions", json={**body, "client_request_id": str(uuid.uuid4())}).json()))
        for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len({r["session_id"] for r in results}) == 1 and sum(r["created"] for r in results) == 1
    gate.set()
    wait_ready(client, results[0]["session_id"])
    assert runner.calls == 1


def test_budget_exhaustion_gives_a_usable_partial_set(synthetic_client):
    client = practice_client(synthetic_client, FakeRunner(accepted=2, stop_reason="daily_budget"))
    data = wait_ready(client, start(client)["session_id"])
    assert data["status"] == "partial" and data["stop_reason"] == "daily_budget"
    assert "límite diario" in data["message_es"] and "2 de 5" in data["message_es"]
    assert len(data["questions"]) == 2


@pytest.mark.parametrize("runner,reason,text", [
    (FakeRunner(accepted=0, stop_reason="llm_unavailable"), "llm_unavailable", "no respondió"),
    (FakeRunner(accepted=0, stop_reason="daily_budget"), "daily_budget", "límite diario"),
    (FakeRunner(raise_error=True), "internal_error", "error inesperado"),
])
def test_failed_generation_is_reported(synthetic_client, runner, reason, text):
    client = practice_client(synthetic_client, runner)
    data = wait_ready(client, start(client)["session_id"])
    assert data["status"] == "failed" and data["stop_reason"] == reason
    assert text in data["message_es"] and "ninguna pregunta" in data["message_es"]
    assert data["questions"] == []
    response = client.post(f"/api/practice/sessions/{data['session_id']}/answers", json={"slot": 1, "label": "A"})
    assert response.status_code == 409


def test_answering_before_ready_and_bad_requests(synthetic_client):
    gate = threading.Event()
    client = practice_client(synthetic_client, FakeRunner(gate=gate))
    sid = start(client)["session_id"]
    assert client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 1, "label": "A"}).status_code == 409
    gate.set()
    wait_ready(client, sid)
    assert client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 9, "label": "A"}).status_code == 404
    assert client.post(f"/api/practice/sessions/{sid}/answers", json={"slot": 1, "label": "E"}).status_code == 422
    assert client.get("/api/practice/sessions/" + "0" * 32).status_code == 404
    assert client.get("/api/practice/sessions/not-a-token").status_code == 422


@pytest.mark.parametrize("overrides", [{"question_count": 10}, {"objective_codes": []},
                                       {"objective_codes": ["M01", "EL01"]}, {"client_request_id": "x"}])
def test_invalid_configurations_are_rejected(synthetic_client, overrides):
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner)
    response = client.post("/api/practice/sessions", json=request_body(**overrides))
    assert response.status_code == 422 and response.json()["message_es"]
    assert runner.calls == 0


def test_server_restart_marks_active_sessions_interrupted(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    store = PracticeStore(url)
    session, created = store.create_or_get(str(uuid.uuid4()), SYNTHETIC,
                                           {"subject": "matematicas", "scope": "single_objective",
                                            "objective_codes": ["Z99"], "difficulty": "easy", "question_count": 5},
                                           [{"workbook_code": "M01", "questions": 5, "slots": []}])
    assert created and session["status"] == "queued"
    PracticeService(lambda: url, lambda: FakeRunner()).get()  # a new server process starts
    after = store.get(session["session_id"])
    assert after["status"] == "failed" and after["stop_reason"] == "interrupted"
