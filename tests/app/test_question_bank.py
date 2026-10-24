"""Validated question bank (T013, ADR-014): reuse, eligibility, partial generation, composition."""

from __future__ import annotations

import copy
import json
import uuid

import psycopg
import pytest

from app.generation.store import GenerationStore
from app.generation.validation import CHECKER_VERSION
from app.llm.usage import MemoryUsageStore
from app.practice.bank import QuestionBank
from app.generation.pipeline import generate_one
from conftest import SYNTHETIC
from test_generation import MATH_ITEM, FakeLlm, bundle, catalog_conn, client_for  # noqa: F401  (fixture)
from test_practice_api import FakeRunner, practice_client, request_body, wait_ready
from test_practice_set import math_item

# Allocation for M01 + M02, 5 questions: slots 1-3 M01 (E1, E2, E1), slots 4-5 M02 (E1, E1).


@pytest.fixture()
def db_url(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    QuestionBank(url)  # ensure tables

    def clean():
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DELETE FROM generation.bank_revalidation WHERE request_id IN (SELECT request_id FROM "
                         "generation.question_attempt WHERE baseline_version = %s)", (SYNTHETIC,))
            conn.execute("DELETE FROM generation.question_attempt WHERE baseline_version = %s "
                         "AND practice_set_id IS NULL", (SYNTHETIC,))
    clean()
    yield url
    clean()


def seed(url, conn, code, ordinal, item, difficulty="medium"):
    """Generate one item through the real pipeline (fake LLM, real checker) and store it in the bank."""
    outcome = generate_one(client_for(FakeLlm([item])), MemoryUsageStore(), bundle(conn, "matematicas", code, ordinal),
                           difficulty)
    assert outcome.status == "accepted", outcome.reasons
    GenerationStore(url).add(outcome, SYNTHETIC, difficulty, "test")
    return outcome


def seed_full(url, conn):
    seed(url, conn, "M01", 1, math_item(0))
    seed(url, conn, "M01", 1, math_item(1))
    seed(url, conn, "M01", 2, math_item(2))
    seed(url, conn, "M02", 1, math_item(3))
    seed(url, conn, "M02", 1, math_item(4))


def session_items(url, session_id):
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT slot, objective_code, evidence_id, source, item FROM practice.item "
                            "WHERE session_id = %s ORDER BY slot", (session_id,)).fetchall()


class RecordingRunner(FakeRunner):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.requested_slots: list[list[int]] = []

    def __call__(self, session, on_slot_done):
        self.requested_slots.append([s["slot"] for row in session["allocation"] for s in row["slots"]])
        self.seed_count = len(session.get("seed_items", []))
        return super().__call__(session, on_slot_done)


def test_full_bank_builds_the_practice_without_generation(synthetic_client, db_url, catalog_conn):
    seed_full(db_url, catalog_conn)
    runner = RecordingRunner()
    client = practice_client(synthetic_client, runner)
    response = client.post("/api/practice/sessions", json=request_body())
    data = response.json()
    assert response.status_code == 202 and data["status"] == "complete"  # ready at once, no job
    assert data["composition"] == {"bank": 5, "generated": 0}
    assert runner.calls == 0
    assert [q["slot"] for q in data["questions"]] == [1, 2, 3, 4, 5]
    raw = json.dumps(data, ensure_ascii=False)
    assert "answer_key" not in raw and "explanation" not in raw
    rows = session_items(db_url, data["session_id"])
    planned = [("M01", "E1"), ("M01", "E2"), ("M01", "E1"), ("M02", "E1"), ("M02", "E1")]
    assert [(r[1], r[2][-2:]) for r in rows] == planned
    assert all(r[3] == "bank" for r in rows)
    assert len({r[4]["item_id"] for r in rows}) == 5 and len({r[4]["stem"] for r in rows}) == 5
    assert all(r[4]["difficulty"] == "medium" for r in rows)
    answer = client.post(f"/api/practice/sessions/{data['session_id']}/answers", json={"slot": 1, "label": "B"}).json()
    assert answer["correct"] is True  # evaluated on the server against the stored key


def test_partial_bank_generates_only_missing_slots(synthetic_client, db_url, catalog_conn):
    seed(db_url, catalog_conn, "M01", 1, math_item(0))
    seed(db_url, catalog_conn, "M01", 1, math_item(1))
    seed(db_url, catalog_conn, "M01", 2, math_item(2))
    runner = RecordingRunner()
    client = practice_client(synthetic_client, runner)
    created = client.post("/api/practice/sessions", json=request_body()).json()
    assert created["status"] in ("queued", "running") and created["composition"]["bank"] == 3
    assert "Generando preguntas adicionales" in created["message_es"] and "3 de 5" in created["message_es"]
    data = wait_ready(client, created["session_id"])
    assert runner.requested_slots == [[4, 5]] and runner.seed_count == 3
    assert data["status"] == "complete" and data["composition"] == {"bank": 3, "generated": 2}
    rows = session_items(db_url, data["session_id"])
    assert [r[3] for r in rows] == ["bank", "bank", "bank", "generated", "generated"]
    assert [r[1] for r in rows] == ["M01", "M01", "M01", "M02", "M02"]


def test_ineligible_items_are_excluded_and_revalidation_is_recorded(synthetic_client, db_url, catalog_conn):
    valid_old = seed(db_url, catalog_conn, "M01", 1, math_item(0))          # will be marked as checker 1.5.0
    hollow = copy.deepcopy(math_item(1))                                     # property question, select: max
    hollow.update(stem="¿Cuál es la mayor cantidad que es múltiplo de 3 y par?",
                  options=[{"label": "A", "text": "6"}, {"label": "B", "text": "24"},
                           {"label": "C", "text": "12"}, {"label": "D", "text": "18"}],
                  answer_key="B", subject_checks={"math": {"select": "max"}})
    hollow_old = seed_raw(db_url, catalog_conn, "M01", 1, hollow)
    easy = seed(db_url, catalog_conn, "M01", 1, math_item(2), difficulty="easy")
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("UPDATE generation.question_attempt SET checker_version = '1.5.0' WHERE request_id IN (%s, %s)",
                     (valid_old.request_id, hollow_old))
    bank = QuestionBank(db_url)
    eligible = bank.eligible(catalog_conn, SYNTHETIC, "matematicas", "M01", 1,
                             valid_old.evidence_id, "medium")
    assert [r["request_id"] for r in eligible] == [valid_old.request_id]   # hollow and easy excluded
    with psycopg.connect(db_url) as conn:
        records = dict(conn.execute("SELECT request_id, eligible FROM generation.bank_revalidation "
                                    "WHERE checker_version = %s", (CHECKER_VERSION,)).fetchall())
        history = conn.execute("SELECT checker_version, verdict FROM generation.question_attempt "
                               "WHERE request_id = %s", (hollow_old,)).fetchone()
    assert records == {valid_old.request_id: True, hollow_old: False}
    assert history == ("1.5.0", "accept")                                  # historical record unchanged
    assert easy.request_id not in records                                  # wrong difficulty: never considered


def seed_raw(url, conn, code, ordinal, item):
    """Store an item as accepted under an older policy, with a full rubric but no blind solve."""
    outcome = generate_one(client_for(FakeLlm([MATH_ITEM])), MemoryUsageStore(),
                           bundle(conn, "matematicas", code, ordinal), "medium")
    outcome.item = {**outcome.item, **{k: item[k] for k in ("stem", "options", "answer_key", "subject_checks")},
                    "item_id": f"Q-old-{uuid.uuid4().hex[:8]}"}
    outcome.request_id = f"req-old-{uuid.uuid4().hex[:12]}"
    outcome.validation = {**outcome.validation, "independent_solve": {"performed": False}}
    GenerationStore(url).add(outcome, SYNTHETIC, "medium", "test")
    return outcome.request_id


def test_near_duplicates_never_share_a_practice(synthetic_client, db_url, catalog_conn):
    seed(db_url, catalog_conn, "M02", 1, math_item(3))
    twin = seed(db_url, catalog_conn, "M02", 1, math_item(3))  # same content, another request
    assert twin.status == "accepted"
    runner = RecordingRunner()
    client = practice_client(synthetic_client, runner)
    data = wait_ready(client, client.post("/api/practice/sessions", json=request_body()).json()["session_id"])
    rows = session_items(db_url, data["session_id"])
    bank_m02 = [r for r in rows if r[1] == "M02" and r[3] == "bank"]
    assert len(bank_m02) == 1                                    # the twin was not used for the other M02 slot
    assert len({r[4]["stem"] for r in rows}) == len(rows)


def test_unseen_questions_are_preferred_across_tabs_from_server_history(synthetic_client, db_url, catalog_conn):
    """T014: exposure comes from PostgreSQL, so a new tab (new token, or none) still avoids served items."""
    for index in range(3):  # three M01-E2 items for the two M01-E2 slots (2 and 4) of a single-objective set
        seed(db_url, catalog_conn, "M01", 2, math_item(index))
    with psycopg.connect(db_url, autocommit=True) as conn:  # start from no recorded exposure for these items
        conn.execute("DELETE FROM practice.answer WHERE session_id IN (SELECT session_id FROM practice.session "
                     "WHERE baseline_version = %s)", (SYNTHETIC,))
        conn.execute("DELETE FROM practice.item WHERE session_id IN (SELECT session_id FROM practice.session "
                     "WHERE baseline_version = %s)", (SYNTHETIC,))
    client = practice_client(synthetic_client, RecordingRunner())
    body = request_body(scope="single_objective", objective_codes=["M01"])
    served = []
    for token in ("tab-one-" + uuid.uuid4().hex, None):
        payload = {**body, "client_request_id": str(uuid.uuid4())}
        if token:
            payload["browser_token"] = token
        data = wait_ready(client, client.post("/api/practice/sessions", json=payload).json()["session_id"])
        served.append({r[4]["item_id"] for r in session_items(db_url, data["session_id"]) if r[2].endswith("E2")})
    assert len(served[0]) == 2 and served[1] - served[0]  # the unseen third item is used by the other tab
