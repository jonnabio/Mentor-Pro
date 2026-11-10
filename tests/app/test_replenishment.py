"""Inventory and performance-based replenishment (T061, T062; ADR-036). mentor_pro_test, mocked LLM only."""

from __future__ import annotations

import functools
import uuid

import psycopg
import pytest

from app.practice import replenishment, seeding
from app.practice.replenishment import Policy, PolicyError, triggers
from conftest import SYNTHETIC
from test_bank_seeding import TARGET, factory, item, url  # noqa: F401  (fixture)
from test_generation import FakeLlm, catalog_conn  # noqa: F401  (fixture)
from app.practice.store import PracticeStore

POLICY = Policy()


def clean_requests(url):
    replenishment.ensure_schema(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DELETE FROM generation.replenishment_request WHERE baseline_version = %s", (SYNTHETIC,))
        conn.execute("DELETE FROM generation.inventory_snapshot WHERE baseline_version = %s", (SYNTHETIC,))


@pytest.fixture()
def db(url):
    clean_requests(url)
    yield url
    clean_requests(url)


def run(url, conn, max_calls=200, policy=POLICY, fake=None):
    llm = factory(url, fake or FakeLlm([item(i) for i in range(10)]))
    return replenishment.run(url, conn, SYNTHETIC, "matematicas", llm, policy, max_calls,
                             seed_run=functools.partial(seeding.run, target=TARGET))


def cell(rows, code, level):
    return next(r for r in rows if r["objective_code"] == code and r["difficulty"] == level)


def pending(url):
    return replenishment.requests(url, SYNTHETIC, "matematicas", pending_only=True)


# ---------------------------------------------------------------- policy


def test_policy_defaults_and_validation():
    assert (POLICY.min_answered, POLICY.mastery_threshold, POLICY.max_batch) == (10, 0.80, 100)
    assert Policy.from_env({"MENTOR_PRO_REPLENISH_MASTERY": "0.9"}).mastery_threshold == 0.9
    for env in ({"MENTOR_PRO_REPLENISH_MIN_ANSWERED": "0"}, {"MENTOR_PRO_REPLENISH_MASTERY": "1.5"},
                {"MENTOR_PRO_REPLENISH_MAX_BATCH": "500"}, {"MENTOR_PRO_REPLENISH_LOW_INVENTORY": "x"}):
        with pytest.raises(PolicyError):
            Policy.from_env(env)


def base(**overrides):
    return {"eligible": 5, "pending_review": 0, "answered": 0, "accuracy": None, **overrides}


def test_triggers_are_independent_and_need_enough_answers():
    assert [t for t, _ in triggers(base(eligible=0), POLICY)] == ["coverage"]
    assert [t for t, _ in triggers(base(eligible=2), POLICY)] == ["low_inventory"]
    assert triggers(base(eligible=2, pending_review=1), POLICY) == []        # awaiting review counts as stock
    assert triggers(base(answered=9, accuracy=1.0), POLICY) == []             # too few answers: no performance
    assert triggers(base(answered=10, accuracy=0.79), POLICY) == []
    found = triggers(base(answered=10, accuracy=0.8), POLICY)
    assert [t for t, _ in found] == ["performance"]
    assert found[0][1] == {"answered": 10, "accuracy": 0.8, "min_answered": 10, "threshold": 0.8}
    both = triggers(base(eligible=0, answered=12, accuracy=0.9), POLICY)
    assert [t for t, _ in both] == ["coverage", "performance"]               # coverage never waits for accuracy


# ---------------------------------------------------------------- inventory and assessment (no LLM)


def test_inventory_reports_every_cell_and_starts_empty(db, catalog_conn):
    rows = replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas")
    assert {(r["objective_code"], r["difficulty"]) for r in rows} == {
        (c, d) for c in ("M01", "M02", "M03") for d in ("easy", "medium", "hard")}
    totals = replenishment.totals(rows)
    assert totals["eligible"] == totals["pending_review"] == totals["covered_cells"] == 0 and totals["cells"] == 9


def test_assess_opens_one_request_per_cell_once_with_its_reason(db, catalog_conn):
    first = replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
    assert len(first["opened"]) == 9 and all(o["trigger"] == "coverage" for o in first["opened"])
    second = replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
    assert second["opened"] == [] and second["closed"] == [] and len(pending(db)) == 9
    with psycopg.connect(db) as conn:
        snaps = conn.execute("SELECT count(*) FROM generation.inventory_snapshot WHERE baseline_version = %s",
                             (SYNTHETIC,)).fetchone()[0]
        assert snaps == 2


def test_the_database_allows_one_pending_request_per_cell(db, catalog_conn):
    replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
    with psycopg.connect(db, autocommit=True) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("""INSERT INTO generation.replenishment_request (replenishment_id, baseline_version, subject,
                            objective_code, difficulty, trigger, evidence, policy)
                        VALUES ('rp-dup', %s, 'matematicas', 'M01', 'easy', 'coverage', '{}', '{}')""", (SYNTHETIC,))


# ---------------------------------------------------------------- generation, review and eligibility (E, F, G, J)


def test_run_generates_candidates_once_and_holds_them_for_review(db, catalog_conn):
    fake = FakeLlm([item(i) for i in range(10)])
    out = run(db, catalog_conn, fake=fake)
    assert out["generated"] == TARGET and out["stop_reason"] is None
    assert {r["status"] for r in pending(db)} == {"candidates_generated"}
    rows = replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas")
    totals = replenishment.totals(rows)
    assert totals["pending_review"] == TARGET and totals["eligible"] == 0      # E: held, never served

    calls = len(fake.calls)
    again = run(db, catalog_conn, fake=fake)                                    # J: pending requests are not redone
    assert again["generated"] == 0 and again["calls"] == 0 and len(fake.calls) == calls


def test_review_decides_eligibility_and_closes_the_request(db, catalog_conn):
    run(db, catalog_conn)
    batch_id = seeding.current_batch(db, SYNTHETIC, "matematicas")["batch_id"]
    export = seeding.item_review_export(db, catalog_conn, batch_id, "M02")["questions"]
    approve, reject = export[0], export[1]
    seeding.item_review_record(db, batch_id, [{"request_id": approve["request_id"], "verdict": "approved"},
                                              {"request_id": reject["request_id"], "verdict": "quarantined",
                                               "reason": "wrong_key"}])
    rows = replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas")
    approved = cell(rows, "M02", approve["difficulty"])
    rejected = cell(rows, "M02", reject["difficulty"])
    assert approved["eligible"] == 1 and approved["pending_review"] == 0      # G: eligible inventory grows
    assert rejected["eligible"] == 0 and rejected["quarantined"] == 1         # F: never eligible
    out = replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
    closed = {(c["objective_code"], c["difficulty"]): c["close_reason"] for c in out["closed"]}
    assert closed[("M02", approve["difficulty"])] == "reviewed"               # still below 3: may reopen later
    assert closed[("M02", reject["difficulty"])] == "reviewed"


def test_budget_and_call_limits_stop_the_run_and_keep_requests_open(db, catalog_conn):
    out = run(db, catalog_conn, max_calls=0)
    assert out["generated"] == 0 and out["stop_reason"] == "run_call_limit"
    assert {r["status"] for r in pending(db)} == {"open"}
    capped = run(db, catalog_conn, policy=Policy(max_batch=1))
    assert capped["generated"] >= 1 and capped["stop_reason"] == "max_batch"
    assert any(r["status"] == "open" for r in pending(db))


def test_a_full_plan_closes_requests_as_needing_a_decision(db, catalog_conn):
    run(db, catalog_conn)                                       # fills all six planned cells
    with psycopg.connect(db, autocommit=True) as conn:          # the tutor reviewed everything long ago
        conn.execute("UPDATE generation.replenishment_request SET status = 'closed', close_reason = 'reviewed' "
                     "WHERE baseline_version = %s", (SYNTHETIC,))
    batch_id = seeding.current_batch(db, SYNTHETIC, "matematicas")["batch_id"]
    export = seeding.item_review_export(db, catalog_conn, batch_id)["questions"]
    seeding.item_review_record(db, batch_id, [{"request_id": q["request_id"], "verdict": "approved"} for q in export])
    out = run(db, catalog_conn)
    assert out["generated"] == 0
    closed = replenishment.requests(db, SYNTHETIC, "matematicas")
    assert any(r["close_reason"] == "no_planned_gap" for r in closed)


def hard_session(store, tag, n):
    """A completed generated M02 practice of five hard questions with unique question identities."""
    allocation = [{"workbook_code": "M02", "text_es": "Objetivo M02",
                   "slots": [{"slot": k + 1, "difficulty": "hard"} for k in range(5)]}]
    config = {"subject": "matematicas", "scope": "single_objective", "objective_codes": ["M02"],
              "difficulty": "hard", "question_count": 5}
    session, _ = store.create_or_get(str(uuid.uuid4()), SYNTHETIC, config, allocation)
    rows = [{"slot": k + 1, "objective_code": "M02", "evidence_id": "ev", "source": "generated",
             "source_request_id": f"rp-test-{tag}-{n}-{k}",
             "item": {"stimulus": {"type": "none"}, "stem": f"P {tag} {n} {k}", "answer_key": "B",
                      "explanation": "x", "options": [{"label": x, "text": x} for x in "ABCD"]}}
            for k in range(5)]
    store.finish(session["session_id"], "complete", None, None, rows)
    return session["session_id"]


def test_performance_trigger_comes_from_real_answers(db, catalog_conn):
    """12 answered M02 hard questions, 11 correct (accuracy 0.92 >= 0.8 with >= 10 answers): performance."""
    store = PracticeStore(db)
    before = cell(replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas"), "M02", "hard")
    tag = uuid.uuid4().hex[:6]
    sessions = [hard_session(store, tag, n) for n in range(3)]
    try:
        picks = [(sid, slot) for sid in sessions for slot in range(1, 5)]          # 12 answers, 3 left unanswered
        for number, (sid, slot) in enumerate(picks):
            label = "A" if number == 0 else "B"
            store.answer(sid, slot, label, label == "B")
        after = cell(replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas"), "M02", "hard")
        assert after["answered"] - before["answered"] == 12 and after["correct"] - before["correct"] == 11
        assert after["served"] - before["served"] == 15
        row = {**after, "answered": 12, "correct": 11, "accuracy": round(11 / 12, 4)} if before["answered"] else after
        found = dict(triggers(row, POLICY))
        assert found["performance"]["answered"] == 12 and found["performance"]["accuracy"] == round(11 / 12, 4)
        out = replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
        opened = {(o["objective_code"], o["difficulty"]): o for o in out["opened"]}
        if not before["answered"]:
            assert "performance" in opened[("M02", "hard")]["evidence"]["also"]
    finally:
        with psycopg.connect(db, autocommit=True) as conn:
            for table in ("answer", "item", "session"):
                conn.execute(f"DELETE FROM practice.{table} WHERE session_id = ANY(%s)", (sessions,))


# ---------------------------------------------------------------- tutor view (K)


def test_tutor_sees_inventory_and_pending_replenishment_read_only(db, catalog_conn):
    from test_tutor_practice_results import GATEWAY, TOKEN, call, create_tutor_app
    run(db, catalog_conn)
    replenishment.assess(db, catalog_conn, SYNTHETIC, "matematicas", POLICY)
    app = create_tutor_app(db, TOKEN, GATEWAY)
    assert call(app, "/api/tutor/practice/bank", headers={}).status_code == 403
    out = call(app, "/api/tutor/practice/bank").json()
    subject = next(s for s in out["subjects"] if s["subject"] == "matematicas")
    assert subject["totals"]["pending_review"] == TARGET and subject["totals"]["eligible"] == 0
    assert {r["status"] for r in out["pending"]} >= {"candidates_generated"}
    assert all("stem" not in c for c in subject["cells"])
    assert call(app, "/api/tutor/practice/bank", method="POST").status_code == 405
