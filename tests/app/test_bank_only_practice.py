"""Bank-only configurable practice (T048, ADR-035): sizes, exact cells, D1-D4, shortage, no generation."""

from __future__ import annotations

import copy
import os
import time
import uuid
from collections import Counter

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.allocation import QUESTION_COUNTS, allocate
from app.generation.validation import CHECKER_VERSION
from app.practice import seeding
from app.practice.bank import QuestionBank
from app.practice.bank_allocation import BankComposer, Shortage, level_bounds
from app.practice.store import PracticeStore
from conftest import SYNTHETIC
from curriculum.catalog import PracticeScope, select_objectives
from test_bank_seeding import item, store_accepted
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_practice_api import FakeRunner, practice_client, request_body

PLACES = ["Liberia", "Cartago", "Limón", "Heredia", "Puntarenas", "Alajuela", "Nicoya", "Turrialba", "Grecia",
          "Quepos", "Golfito", "Upala", "Atenas", "Orotina", "Santa Cruz"]
LEVELS = ("easy", "medium", "hard")


def variant(n: int, tag: str = "") -> dict:
    """Distinct items (no two near duplicates): 15 places × 10 situations."""
    out = copy.deepcopy(item(n % 10))
    out["stem"] = f"En {PLACES[n // 10]}, " + out["stem"][0].lower() + out["stem"][1:]
    out["item_id"] = f"bo-{tag}{n}"
    return out


# ---------------------------------------------------------------- planner (fake bank, no database)

def objectives(k: int, evidences: int = 2) -> list[dict]:
    return [{"workbook_code": f"M{i + 1:02d}", "text_es": f"Objetivo {i + 1}",
             "evidences": [{"id": f"M{i + 1:02d}-E{j + 1}", "ordinal": j + 1} for j in range(evidences)]}
            for i in range(k)]


class FakeBank:
    def __init__(self, rows, seen=()):
        self.rows, self.seen, self.lookups = rows, set(seen), 0

    def candidates(self, catalog, baseline, subject, code, evidences, levels, db=None):
        self.lookups += 1
        return [r for r in self.rows if r["objective_code"] == code and r["evidence_id"] in evidences
                and r["difficulty"] in levels]

    def seen_questions(self):
        return self.seen


def stock(objs, per_cell, levels=LEVELS, evidence_filter=None):
    rows, n = [], 0
    for o in objs:
        for e in o["evidences"]:
            if evidence_filter and not evidence_filter(e):
                continue
            for level in levels:
                for _ in range(per_cell):
                    rows.append({"objective_code": o["workbook_code"], "evidence_id": e["id"], "difficulty": level,
                                 "item": variant(n), "request_id": f"r{n}"})
                    n += 1
    return rows


def composer(rows, objs, difficulty="mixed", seen=()):
    bank = FakeBank(rows, seen)
    return BankComposer(bank, None, SYNTHETIC, "matematicas", objs, difficulty), bank


@pytest.mark.parametrize("count", QUESTION_COUNTS)
def test_every_permitted_size_is_complete_exact_and_keeps_the_objective_distribution(count):
    objs = objectives(4)
    allocation, picks = composer(stock(objs, 2), objs)[0].compose_or_shortage(count)
    assert len(picks) == count and [p["slot"] for p in picks] == list(range(1, count + 1))
    expected = {r["workbook_code"]: r["questions"] for r in allocate(objs, count, "mixed")["allocation"]}
    assert {r["workbook_code"]: r["questions"] for r in allocation} == expected  # D2: objective counts unchanged
    cells = {s["slot"]: (r["workbook_code"], s["evidence_id"], s["difficulty"]) for r in allocation for s in r["slots"]}
    rows = {r["request_id"]: r for r in stock(objs, 2)}
    for p in picks:  # every question is an exact match for its recorded cell
        src = rows[p["source_request_id"]]
        assert cells[p["slot"]] == (src["objective_code"], src["evidence_id"], src["difficulty"])
        assert p["objective_code"] == src["objective_code"] and p["evidence_id"] == src["evidence_id"]
    low, high = level_bounds(count)  # D3: each level within ±1 of a third
    assert all(low <= n <= high for n in Counter(c[2] for c in cells.values()).values())
    assert len({p["item"]["item_id"] for p in picks}) == count


def test_a_thirty_question_practice_looks_up_the_bank_once_per_objective():
    objs = objectives(3)
    comp, bank = composer(stock(objs, 4), objs)
    comp.compose_or_shortage(30)
    assert bank.lookups == 3


def test_evidencias_with_stock_are_used_and_spread_before_repeating():  # D1
    objs = objectives(1, evidences=3)
    only_e2_e3 = stock(objs, 2, evidence_filter=lambda e: e["ordinal"] > 1)
    allocation, _ = composer(only_e2_e3, objs)[0].compose_or_shortage(5)
    used = [s["evidence_id"] for s in allocation[0]["slots"]]
    assert set(used) == {"M01-E2", "M01-E3"} and abs(used.count("M01-E2") - used.count("M01-E3")) <= 1


def test_an_explicit_level_is_never_substituted():
    objs = objectives(2)
    comp, _ = composer(stock(objs, 3, levels=("easy",)), objs, difficulty="medium")
    with pytest.raises(Shortage) as exc:
        comp.compose_or_shortage(5)
    assert exc.value.largest == 0
    _, picks = composer(stock(objs, 3, levels=("easy", "medium")), objs, "medium")[0].compose_or_shortage(5)
    assert {p["source_request_id"] for p in picks} <= {r["request_id"] for r in stock(objs, 3, ("easy", "medium"))
                                                        if r["difficulty"] == "medium"}


def test_mixed_needs_a_balance_and_never_fills_with_one_level():
    objs = objectives(2)
    with pytest.raises(Shortage):
        composer(stock(objs, 10, levels=("easy",)), objs)[0].compose_or_shortage(5)


def test_unseen_questions_are_preferred_and_seen_ones_fill_the_rest():
    objs = objectives(1, evidences=1)
    rows = stock(objs, 2)  # 6 questions: one cell per level, two questions each
    seen = {r["item"]["item_id"] for r in rows[::2]}
    _, picks = composer(rows, objs, seen=seen)[0].compose_or_shortage(5)
    chosen = [p["item"]["item_id"] for p in picks]
    assert set(chosen) >= {r["item"]["item_id"] for r in rows[1::2]}  # all 3 unseen used
    assert sum(i in seen for i in chosen) == 2


def test_no_question_or_near_duplicate_appears_twice():
    objs = objectives(1, evidences=1)
    rows = stock(objs, 1)
    twin = {**rows[0], "request_id": "twin"}  # same item stored twice
    near = {**rows[1], "request_id": "near", "item": {**copy.deepcopy(rows[1]["item"]), "item_id": "near"}}
    with pytest.raises(Shortage):
        composer(rows + [twin, near], objs)[0].compose_or_shortage(5)


def test_a_shortage_reports_the_largest_permitted_size_that_fits():
    objs = objectives(4)
    comp, _ = composer(stock(objs, 1), objs)  # 24 questions: 6 cells per objective
    with pytest.raises(Shortage) as exc:
        comp.compose_or_shortage(30)
    assert (exc.value.requested, exc.value.largest) == (30, 20)
    assert comp.compose(25) is None and comp.compose(20) is not None


# ---------------------------------------------------------------- API (mentor_pro_test, synthetic catalog)

@pytest.fixture()
def url(synthetic_client):
    url, _ = synthetic_client.app.state.catalog_target
    PracticeStore(url)
    QuestionBank(url)
    clean(url)
    yield url
    clean(url)


def clean(url):
    with psycopg.connect(url, autocommit=True) as conn:
        mine = "SELECT request_id FROM generation.question_attempt WHERE prompt_version = 'bank-only-test'"
        conn.execute(f"DELETE FROM generation.bank_item_review WHERE request_id IN ({mine})")
        conn.execute(f"DELETE FROM generation.bank_revalidation WHERE request_id IN ({mine})")
        conn.execute("DELETE FROM generation.question_attempt WHERE prompt_version IN ('bank-only-test', 'test') "
                     "AND baseline_version = %s AND practice_set_id IS NULL", (SYNTHETIC,))


def fill_bank(url, conn, per_cell, levels=LEVELS, tag=None):
    """Accepted rows for every synthetic Matemáticas cell: one real accepted row, cloned with distinct items."""
    tag = tag or uuid.uuid4().hex[:6]
    template = store_accepted(url, conn, "M01", 1, item(0), "medium")
    objs = select_objectives(conn, SYNTHETIC, PracticeScope.SUBJECT_SIMULATION, "matematicas").objectives
    n = 0
    with psycopg.connect(url, autocommit=True) as db:
        for o in objs:
            for e in o["evidences"]:
                for level in levels:
                    for _ in range(per_cell):
                        it = variant(n, tag)
                        db.execute(
                            """INSERT INTO generation.question_attempt (request_id, baseline_version, objective_code,
                                   evidence_id, difficulty, status, verdict, item_id, models_used, calls, tokens_in,
                                   tokens_out, cost_usd, cost_complete, checker_version, prompt_version, validation,
                                   item, reasons)
                               SELECT %s, baseline_version, %s, %s, %s, status, 'accept', %s, models_used, calls,
                                   tokens_in, tokens_out, cost_usd, cost_complete, %s, 'bank-only-test', validation,
                                   item || %s, reasons
                               FROM generation.question_attempt WHERE request_id = %s""",
                            (f"bo-{tag}-{n}", o["workbook_code"], e["id"], level, it["item_id"], CHECKER_VERSION,
                             Jsonb({k: it[k] for k in ("item_id", "stem", "options", "explanation", "subject_checks")}),
                             template))
                        n += 1
        db.execute("DELETE FROM generation.question_attempt WHERE request_id = %s", (template,))
    return n


def sessions_with(url, request_id):
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT count(*) FROM practice.session WHERE client_request_id = %s",
                            (request_id,)).fetchone()[0]


def bank_only(**overrides):
    return request_body(scope="subject_simulation", objective_codes=[], difficulty="mixed", source="bank_only",
                        **overrides)


@pytest.mark.parametrize("count", [5, 15, 30])
def test_a_bank_only_practice_is_ready_at_once_without_generation(synthetic_client, url, catalog_conn, count):
    fill_bank(url, catalog_conn, per_cell=4)  # M02 has one evidencia: 12 questions for its 10 slots
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner)
    body = bank_only(question_count=count)
    response = client.post("/api/practice/sessions", json=body)
    assert response.status_code == 202, response.json()
    session = response.json()
    assert session["status"] == "complete" and session["created"]
    assert session["slots_total"] == count and session["composition"] == {"bank": count, "generated": 0}
    assert len(session["questions"]) == count and runner.calls == 0
    assert all("answer_key" not in q and "explanation" not in q for q in session["questions"])
    again = client.post("/api/practice/sessions", json=body).json()  # same request id: same practice
    assert again["session_id"] == session["session_id"] and not again["created"]
    answer = client.post(f"/api/practice/sessions/{session['session_id']}/answers", json={"slot": count, "label": "B"})
    assert answer.status_code == 200 and answer.json()["correct"] is True


def test_a_shortage_creates_nothing_and_explains_in_spanish(synthetic_client, url, catalog_conn):
    fill_bank(url, catalog_conn, per_cell=1)  # 4 evidencias × 3 levels = 12 questions
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner)
    body = bank_only(question_count=30)
    response = client.post("/api/practice/sessions", json=body)
    assert response.status_code == 409
    out = response.json()
    assert out["error"] == "insufficient_inventory" and out["requested"] == 30
    assert out["largest_available"] == 10
    assert f"práctica de {out['largest_available']} preguntas" in out["message_es"]
    assert sessions_with(url, body["client_request_id"]) == 0 and runner.calls == 0
    retry = client.post("/api/practice/sessions", json={**body, "question_count": out["largest_available"]})
    assert retry.status_code == 202 and retry.json()["status"] == "complete"


def test_an_empty_bank_gives_no_smaller_option_and_never_generates(synthetic_client, url):
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner)
    body = {**bank_only(question_count=5), "difficulty": "hard"}
    out = client.post("/api/practice/sessions", json=body)
    assert out.status_code == 409 and out.json()["largest_available"] == 0
    assert "Todavía estamos preparando" in out.json()["message_es"]
    assert sessions_with(url, body["client_request_id"]) == 0 and runner.calls == 0


def test_quarantined_questions_are_never_served(synthetic_client, url, catalog_conn):
    fill_bank(url, catalog_conn, per_cell=1, levels=("easy",))
    with psycopg.connect(url) as conn:
        rows = conn.execute("SELECT request_id FROM generation.question_attempt WHERE prompt_version = "
                            "'bank-only-test' AND objective_code = 'M02'").fetchall()
    for (request_id,) in rows:
        seeding.quarantine(url, request_id, "wrong_key", "test")
    client = practice_client(synthetic_client, FakeRunner())
    body = request_body(source="bank_only", scope="single_objective", objective_codes=["M02"], difficulty="easy")
    assert client.post("/api/practice/sessions", json=body).status_code == 409


def test_generation_requests_keep_five_questions_and_their_flow(synthetic_client, url):
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner)
    for count in (7, 10):  # not permitted / bank-only sizes only
        assert client.post("/api/practice/sessions", json=request_body(question_count=count)).status_code == 422
    assert client.post("/api/practice/sessions", json=request_body(source="bank_only",
                                                                   question_count=7)).status_code == 422
    assert runner.calls == 0


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_LATENCY"), reason="set MENTOR_PRO_LATENCY=1 to time startup")
def test_bank_only_startup_latency(synthetic_client, url, catalog_conn):
    fill_bank(url, catalog_conn, per_cell=12)
    client = practice_client(synthetic_client, FakeRunner())
    for count, limit in ((5, 0.5), (30, 1.0)):
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            assert client.post("/api/practice/sessions", json=bank_only(question_count=count)).status_code == 202
            timings.append(time.perf_counter() - start)
        p95 = sorted(timings)[18]
        print(f"bank-only {count}: p95 {p95 * 1000:.0f} ms")
        assert p95 < limit
    timings = []  # reference: the earlier bank-first flow, filled completely from the bank
    for _ in range(20):
        start = time.perf_counter()
        assert client.post("/api/practice/sessions", json=request_body()).json()["status"] == "complete"
        timings.append(time.perf_counter() - start)
    print(f"bank-then-generate 5 (reference): p95 {sorted(timings)[18] * 1000:.0f} ms")
