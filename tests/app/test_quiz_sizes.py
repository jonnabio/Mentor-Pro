"""Quiz sizes 5-30 offered only when they can start (T063, RCA-006).

Every choice the student UI can make (whole subject, each single objective, each difficulty) is checked: each
advertised size starts a complete bank practice with no generation, and every size not advertised is refused,
so an offered option never leads to a predictable inventory error.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from app.allocation import QUESTION_COUNTS
from conftest import SYNTHETIC
from curriculum.catalog import PracticeScope, select_objectives
from test_bank_only_practice import (FakeBank, LEVELS, clean, composer, fill_bank, objectives,  # noqa: F401
                                     stock, url)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_practice_api import FakeRunner, practice_client

DIFFICULTIES = ("mixed", "easy", "medium", "hard")
ALL_SIZES = {"matematicas": QUESTION_COUNTS}


def choice(scope="subject_simulation", codes=(), difficulty="mixed"):
    return {"subject": "matematicas", "scope": scope, "objective_codes": list(codes), "difficulty": difficulty}


def counts(client, body):
    response = client.post("/api/practice/availability", json=body)
    assert response.status_code == 200, response.json()
    return response.json()


def session_count(url):
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT count(*) FROM practice.session").fetchone()[0]


# ---------------------------------------------------------------- composer


def test_available_sizes_are_those_the_composer_fills_in_ascending_order():
    objs = objectives(4)
    comp, _ = composer(stock(objs, 1), objs)          # 4 objectives × 2 evidencias × 3 levels = 24 questions
    ready = comp.available_sizes(QUESTION_COUNTS)
    assert ready == [5, 10, 15, 20]
    assert all(comp.compose(n) is not None for n in ready)
    assert comp.compose(25) is None


def test_an_explicit_level_offers_only_what_that_level_holds():
    objs = objectives(2)
    comp, _ = composer(stock(objs, 3, levels=("easy",)), objs, difficulty="easy")   # 12 easy questions
    assert comp.available_sizes(QUESTION_COUNTS) == [5, 10]
    comp, _ = composer(stock(objs, 3, levels=("easy",)), objs, difficulty="hard")
    assert comp.available_sizes(QUESTION_COUNTS) == []


# ---------------------------------------------------------------- API


def test_switch_off_offers_five_only(synthetic_client, url):
    client = practice_client(synthetic_client, FakeRunner())
    assert counts(client, choice()) == {"bank_only": False, "question_counts": [5], "bank_counts": []}


def test_an_empty_bank_still_offers_five_through_generation(synthetic_client, url):
    client = practice_client(synthetic_client, FakeRunner(), bank_only=ALL_SIZES)
    out = counts(client, choice())
    assert out["question_counts"] == [5] and out["bank_counts"] == []


def test_an_incomplete_choice_offers_five_only(synthetic_client, url):
    client = practice_client(synthetic_client, FakeRunner(), bank_only=ALL_SIZES)
    assert counts(client, choice("selected_objectives"))["question_counts"] == [5]


def test_configured_sizes_cap_what_is_offered(synthetic_client, url, catalog_conn):
    fill_bank(url, catalog_conn, per_cell=4)
    client = practice_client(synthetic_client, FakeRunner(), bank_only={"matematicas": (5, 10)})
    assert counts(client, choice())["question_counts"] == [5, 10]


def test_availability_creates_nothing_and_calls_nothing(synthetic_client, url, catalog_conn):
    fill_bank(url, catalog_conn, per_cell=2)
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner, bank_only=ALL_SIZES)
    before = session_count(url)
    counts(client, choice())
    assert session_count(url) == before and runner.calls == 0


def test_invalid_selection_is_refused(synthetic_client, url):
    client = practice_client(synthetic_client, FakeRunner(), bank_only=ALL_SIZES)
    response = client.post("/api/practice/availability", json=choice("single_objective", ["M99"]))
    assert response.status_code == 422


def test_every_offered_choice_starts_and_every_other_size_is_refused(synthetic_client, url, catalog_conn):
    """RCA-006: whole subject and each single objective, at every difficulty."""
    fill_bank(url, catalog_conn, per_cell=3, levels=("easy", "medium"))   # no hard questions at all
    runner = FakeRunner()
    client = practice_client(synthetic_client, runner, bank_only=ALL_SIZES)
    codes = [o["workbook_code"] for o in
             select_objectives(catalog_conn, SYNTHETIC, PracticeScope.SUBJECT_SIMULATION, "matematicas").objectives]
    choices = [choice(difficulty=d) for d in DIFFICULTIES] + [
        choice("single_objective", [c], d) for c in codes for d in DIFFICULTIES]
    offered_any_larger = False
    for body in choices:
        out = counts(client, body)
        assert 5 in out["question_counts"]
        offered_any_larger |= any(n > 5 for n in out["question_counts"])
        # Every offered size, plus the first permitted size above them (it must be refused, not half-filled).
        above = [n for n in QUESTION_COUNTS if n > max(out["bank_counts"] or [0])][:1]
        for size in sorted(set(out["bank_counts"]) | {5} | set(above)):
            request = {**body, "question_count": size, "source": "bank_only",
                       "client_request_id": str(uuid.uuid4())}
            response = client.post("/api/practice/sessions", json=request)
            if size in out["bank_counts"]:
                assert response.status_code == 202, (body, size, response.json())
                session = response.json()
                assert session["status"] == "complete" and len(session["questions"]) == size
                assert session["composition"] == {"bank": size, "generated": 0}
            elif size == 5:
                assert response.status_code == 202      # T059: the whole practice is generated instead
            else:
                assert response.status_code == 409, (body, size)
                assert response.json()["error"] == "insufficient_inventory"
    assert offered_any_larger                            # the check is not vacuous
