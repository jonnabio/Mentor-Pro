"""T060: tutor practice results and Question Bank analytics (read-only, tutor check only).

Practices are built directly with PracticeStore on the test database: a completed bank practice, a
generated practice left after two answers, a bank practice not yet answered that reuses bank questions,
a failed generation and an automated-test session that must never be shown.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import psycopg
import pytest

from app.main import create_app
from app.practice.store import PracticeStore
from app.practice.tutor_results import practice_state
from app.tutor_main import create_tutor_app
from conftest import SYNTHETIC

TOKEN = "tutor-practice-token-0123456789abcdef"
GATEWAY = "172.19.0.1"
GOOD = {"X-Tutor-Token": TOKEN}
LEVELS = ["easy", "medium", "hard", "medium", "easy"]


def call(app, path, headers=GOOD, client_ip=GATEWAY, method="GET"):
    transport = httpx.ASGITransport(app=app, client=(client_ip, 40000))

    async def go():
        async with httpx.AsyncClient(transport=transport, base_url="http://tutor") as c:
            return await c.request(method, path, headers=headers)

    return asyncio.run(go())


def item(stem: str, key: str = "B", difficulty: str | None = None) -> dict:
    body = {"stimulus": {"type": "none"}, "stem": stem, "answer_key": key, "explanation": f"Explicación {stem}",
            "options": [{"label": label, "text": f"{stem} {label}"} for label in "ABCD"]}
    return {**body, "difficulty": difficulty} if difficulty else body


def make_session(store: PracticeStore, subject: str, code: str, source: str, stems: list[str],
                 request_ids: list[str | None] | None = None, status: str = "complete"):
    allocation = [{"workbook_code": code, "text_es": f"Objetivo {code}",
                   "slots": [{"slot": n + 1, "difficulty": LEVELS[n]} for n in range(5)]}]
    config = {"subject": subject, "scope": "selected_objectives", "objective_codes": [code],
              "difficulty": "mixed", "question_count": 5}
    session, _ = store.create_or_get(str(uuid.uuid4()), SYNTHETIC, config, allocation)
    sid = session["session_id"]
    rows = [{"slot": n + 1, "objective_code": code, "evidence_id": f"ev-{n}", "item": item(stem),
             "source": source, "source_request_id": (request_ids or [None] * 5)[n]} for n, stem in enumerate(stems)]
    if source == "bank":
        store.add_bank_items(sid, rows, complete=True)
    else:
        store.finish(sid, status, "slot_retries_exhausted" if status == "failed" else None, None, rows)
    return sid


def answer(store: PracticeStore, sid: str, picks: dict[int, str]) -> None:
    for slot, label in picks.items():
        store.answer(sid, slot, label, label == "B")


@pytest.fixture()
def env(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    store = PracticeStore(url)
    tag = uuid.uuid4().hex[:6]
    bank_ids = [f"req-{tag}-{n}" for n in range(5)]
    bank_stems = [f"Banco {tag} {n}" for n in range(5)]
    ids = {}
    ids["complete"] = make_session(store, "matematicas", "M01", "bank", bank_stems, bank_ids)
    answer(store, ids["complete"], {1: "B", 2: "B", 3: "B", 4: "A", 5: "C"})  # 3 correct, 2 incorrect
    ids["left"] = make_session(store, "matematicas", "M05", "generated", [f"Gen {tag} {n}" for n in range(5)])
    answer(store, ids["left"], {1: "B", 2: "D"})
    assert store.cancel(ids["left"]) == "cancelled"
    ids["fresh"] = make_session(store, "matematicas", "M01", "bank", bank_stems[:2] + [f"Otro {tag} {n}" for n in range(3)],
                                bank_ids[:2] + [f"req-{tag}-x{n}" for n in range(3)])
    ids["failed"] = make_session(store, "ciencias", "C02", "generated", [], status="failed")
    ids["test"] = make_session(store, "matematicas", "M01", "bank", bank_stems, bank_ids)
    answer(store, ids["test"], {1: "A"})
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("INSERT INTO practice.session_classification (session_id, classification, reason, audit_ref) "
                     "VALUES (%s, 'automated_test', 't060', 't060')", (ids["test"],))
    app = create_tutor_app(url, TOKEN, GATEWAY)
    yield app, url, ids, tag
    with psycopg.connect(url, autocommit=True) as conn:
        everything = list(ids.values())
        for table in ("answer", "item", "classification_audit", "session_classification", "session"):
            conn.execute(f"DELETE FROM practice.{table} WHERE session_id = ANY(%s)", (everything,))


def mine(sessions, ids):
    wanted = set(ids.values())
    return {s["session_id"]: s for s in sessions if s["session_id"] in wanted}


def counts(url):
    with psycopg.connect(url) as conn:
        return [conn.execute(f"SELECT COUNT(*) FROM practice.{t}").fetchone()[0] for t in ("session", "item", "answer")]


# ------------------------------------------------------------------ access

@pytest.mark.parametrize("path", ["/api/tutor/practice/sessions", "/api/tutor/practice/questions"])
@pytest.mark.parametrize("headers", [{}, {"X-Tutor-Token": "wrong-token-0123456789abcdef0123"}])
def test_results_refuse_absent_or_wrong_token(env, path, headers):
    app, *_ = env
    assert call(app, path, headers).status_code == 403


@pytest.mark.parametrize("client_ip", ["192.168.50.20", "172.19.0.5"])
def test_results_refuse_other_addresses_even_with_the_token(env, client_ip):
    app, *_ = env
    assert call(app, "/api/tutor/practice/sessions", client_ip=client_ip).status_code == 403


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_results_are_read_only(env, method):
    app, url, ids, _ = env
    before = counts(url)
    for path in ("/api/tutor/practice/sessions", f"/api/tutor/practice/sessions/{ids['complete']}",
                 "/api/tutor/practice/questions"):
        assert call(app, path, method=method).status_code == 405
    assert counts(url) == before


def test_student_service_has_no_results_routes_without_the_tutor_token(env):
    _, url, ids, _ = env
    app = create_app(url, tutor_token="")
    for path in ("/api/tutor/practice/sessions", f"/api/tutor/practice/sessions/{ids['complete']}"):
        assert call(app, path, client_ip="127.0.0.1").status_code == 404


def test_main_app_serves_results_to_the_local_tutor(env):
    _, url, ids, _ = env
    app = create_app(url, tutor_token=TOKEN)
    assert call(app, "/api/tutor/practice/sessions", client_ip="127.0.0.1").status_code == 200
    assert call(app, "/api/tutor/practice/sessions", headers={}, client_ip="127.0.0.1").status_code == 403


# ------------------------------------------------------------------ history

def test_history_aggregates_completed_left_unanswered_and_failed(env):
    app, url, ids, _ = env
    before = counts(url)
    body = call(app, "/api/tutor/practice/sessions").json()
    got = mine(body["sessions"], ids)
    assert ids["test"] not in got  # automated_test sessions are never shown
    c, left, fresh, failed = (got[ids[k]] for k in ("complete", "left", "fresh", "failed"))
    assert (c["state"], c["composition"], c["answered"], c["correct"], c["incorrect"], c["unanswered"],
            c["accuracy"]) == ("completed", {"bank": 5, "generated": 0}, 5, 3, 2, 0, 0.6)
    assert c["objectives"] == ["M01"] and c["difficulty"] == "mixed" and c["subject"] == "matematicas"
    assert (left["state"], left["composition"], left["answered"], left["correct"], left["unanswered"],
            left["accuracy"]) == ("left", {"bank": 0, "generated": 5}, 2, 1, 3, 0.5)
    assert (fresh["state"], fresh["answered"], fresh["accuracy"]) == ("not_started", 0, None)
    assert (failed["state"], failed["questions"], failed["composition"]) == ("failed", 0, {"bank": 0, "generated": 0})
    assert {s["code"] for s in body["subjects"]} >= {"matematicas", "ciencias"}
    assert counts(url) == before


def test_history_filters(env):
    app, _, ids, _ = env
    get = lambda q: set(mine(call(app, f"/api/tutor/practice/sessions?{q}").json()["sessions"], ids))  # noqa: E731
    assert get("subject=ciencias") == {ids["failed"]}
    assert get("source=generated") == {ids["left"]}
    assert get("source=bank&subject=matematicas") == {ids["complete"], ids["fresh"]}
    assert get("objective=m05") == {ids["left"]}  # case-insensitive objective code
    assert get("from=2000-01-01&to=2000-01-02") == set()
    assert ids["complete"] in get("from=2000-01-01")


@pytest.mark.parametrize("query", ["subject=fisica", "source=mixed", "from=2026-02-02&to=2026-01-01", "from=ayer"])
def test_invalid_filters_are_explained(env, query):
    app, *_ = env
    response = call(app, f"/api/tutor/practice/sessions?{query}")
    assert response.status_code == 422


# ------------------------------------------------------------------ session detail

def test_detail_shows_each_answer_with_key_explanation_and_source(env):
    app, _, ids, tag = env
    body = call(app, f"/api/tutor/practice/sessions/{ids['left']}").json()
    assert body["state"] == "left" and len(body["items"]) == 5
    first, second, third = body["items"][:3]
    assert (first["result"], first["chosen_label"], first["correct_label"], first["source"]) == \
        ("correct", "B", "B", "generated")
    assert (second["result"], second["chosen_label"]) == ("incorrect", "D")
    assert (third["result"], third["chosen_label"], third["answered_at"]) == ("unanswered", None, None)
    assert first["stem"] == f"Gen {tag} 0" and first["explanation"] == f"Explicación Gen {tag} 0"
    assert [o["label"] for o in first["options"]] == list("ABCD")
    assert [i["difficulty"] for i in body["items"]] == LEVELS  # from the allocation when the item has none


def test_detail_of_unknown_or_excluded_sessions_is_404(env):
    app, _, ids, _ = env
    for sid in ("0" * 32, ids["test"], "x" * 100):
        assert call(app, f"/api/tutor/practice/sessions/{sid}").status_code == 404


def test_detail_never_carries_student_identity_fields(env):
    app, _, ids, _ = env
    body = call(app, f"/api/tutor/practice/sessions/{ids['complete']}").json()
    text = str(body).lower()
    for field in ("browser_hash", "client_request_id", "fingerprint", "student_name", "name"):
        assert f"'{field}'" not in text


# ------------------------------------------------------------------ question analytics

def test_question_metrics_count_repeats_unanswered_and_zero_attempts(env):
    app, _, ids, tag = env
    body = call(app, "/api/tutor/practice/questions?subject=matematicas").json()
    by_stem = {q["stem"]: q for q in body["questions"]}
    q0, q3 = by_stem[f"Banco {tag} 0"], by_stem[f"Banco {tag} 3"]
    # Served in the completed and the fresh practice; the automated-test session is not counted.
    assert (q0["served"], q0["answered"], q0["correct"], q0["incorrect"], q0["unanswered"], q0["success_rate"]) == \
        (2, 1, 1, 0, 1, 1.0)
    assert (q3["served"], q3["answered"], q3["correct"], q3["incorrect"], q3["success_rate"]) == (1, 1, 0, 1, 0.0)
    never = by_stem[f"Otro {tag} 0"]
    assert (never["served"], never["answered"], never["unanswered"], never["success_rate"]) == (1, 0, 1, None)
    gen = by_stem[f"Gen {tag} 4"]
    assert (gen["source"], gen["answered"], gen["unanswered"]) == ("generated", 0, 1)


def test_question_groups_by_objective_and_difficulty(env):
    app, _, ids, tag = env
    body = call(app, "/api/tutor/practice/questions?subject=matematicas&objective=M01").json()
    mine_q = [q for q in body["questions"] if tag in q["stem"]]
    assert {q["objective_code"] for q in mine_q} == {"M01"} and {q["source"] for q in mine_q} == {"bank"}
    groups = {(g["objective_code"], g["difficulty"]): g for g in body["groups"]}
    easy = groups[("M01", "easy")]
    assert easy["questions"] >= 2 and easy["served"] >= easy["answered"]
    assert easy["incorrect"] == easy["answered"] - easy["correct"]


def test_question_source_filter(env):
    app, _, _, tag = env
    body = call(app, "/api/tutor/practice/questions?source=generated").json()
    assert {q["source"] for q in body["questions"]} <= {"generated"}
    assert any(q["stem"] == f"Gen {tag} 0" for q in body["questions"])


@pytest.mark.parametrize("args,state", [
    (("queued", False, 0, 0), "preparing"), (("running", False, 0, 0), "preparing"),
    (("failed", False, 0, 0), "failed"), (("complete", False, 0, 0), "failed"),
    (("complete", False, 5, 5), "completed"), (("complete", True, 5, 2), "left"),
    (("partial", False, 3, 0), "not_started"), (("complete", False, 5, 1), "in_progress"),
])
def test_practice_state(args, state):
    assert practice_state(*args) == state
