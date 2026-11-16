"""T069: quiz sizes 5-30 in all four subjects on a synthetic bank (PO-T069-2026-11-16, RCA-006).

A synthetic workbook with the four subjects (own baseline, own catalog schema) and a bank of approved questions
for every evidencia and level. For every subject and size: the availability the student sees is what the real
composer builds; each offered size starts a complete bank practice with exactly that many distinct questions, the
curriculum allocation unchanged, the level balance kept and no model call; answering scores correctly and the
practice appears in the history and in the tutor's analytics. A short bank refuses larger sizes with nothing
created. Browser tests (opt-in, MENTOR_PRO_BROWSER=1) run a 30-question practice on desktop and on a phone.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from collections import Counter
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from app.allocation import QUESTION_COUNTS, allocate
from app.generation.validation import CHECKER_VERSION
from app.main import create_app, open_catalog
from app.practice.bank import QuestionBank
from app.practice.bank_allocation import level_bounds
from app.practice.store import PracticeStore
from app.practice.tutor_results import PracticeResults
from curriculum import importer
from curriculum.catalog import PracticeScope, select_objectives
from test_bank_only_practice import LEVELS, variant
from test_bank_seeding import item, store_accepted
from test_generation import catalog_conn  # noqa: F401  (fixture: the TEST-v1 template catalog)
from test_practice_api import FakeRunner
from workbook_fixtures import SRC_MAT, drop_target, new_target, register, write_workbook

BASELINE = "SIZES-v1"
SUBJECT_NAMES = {"espanol": "Español", "matematicas": "Matemáticas", "ciencias": "Ciencias",
                 "estudios_sociales": "Estudios Sociales"}
# subject -> (code prefix, evidencias per objective): unequal objectives and evidencias, like the real catalog.
SHAPE = {"espanol": ("EL", (2, 1, 2)), "matematicas": ("M", (2, 1, 1, 2)), "ciencias": ("C", (1, 2, 2)),
         "estudios_sociales": ("ES", (1, 1, 1, 1, 1))}
PER_CELL = 4  # approved questions per evidencia and level: every objective holds at least 12


def workbook_rows():
    cat, ev = [], []
    for subject, (prefix, evidences) in SHAPE.items():
        name = SUBJECT_NAMES[subject]
        for i, n in enumerate(evidences, start=1):
            code = f"{prefix}{i:02d}"
            text = f"Objetivo sintético {code} de {name}."
            cat.append([code, name, "Bloque 1", f"Afirmación {i}", text, "Concepto.", "Actividad.", SRC_MAT, float(n),
                        "1 ítem(s) previsto(s)"])
            for j in range(1, n + 1):
                ev.append([code, float(j), f"Evidencia {j} de {code}.", name, False, text, "Bloque 1", SRC_MAT])
    return cat, ev


@pytest.fixture(scope="module")
def sizes_target(tmp_path_factory):
    target = new_target()
    folder = tmp_path_factory.mktemp("wb4")
    manifest = folder / "MANIFEST.sha256"
    manifest.write_text("", encoding="utf-8")
    workbook = write_workbook(folder / "wb.xlsx", *workbook_rows())
    register(manifest, workbook)
    importer.import_workbook(workbook, target.url, BASELINE, manifest, target.schema)
    PracticeStore(target.url)
    QuestionBank(target.url)
    yield target
    clean(target.url)
    drop_target(target)


def clean(url):
    with psycopg.connect(url, autocommit=True) as conn:
        sessions = "SELECT session_id FROM practice.session WHERE baseline_version = %s"
        for table in ("practice.answer", "practice.session_classification", "practice.item"):
            conn.execute(f"DELETE FROM {table} WHERE session_id IN ({sessions})", (BASELINE,))
        conn.execute("DELETE FROM practice.session WHERE baseline_version = %s", (BASELINE,))
        conn.execute("DELETE FROM generation.question_attempt WHERE baseline_version = %s", (BASELINE,))


def objectives_of(target, subject):
    conn = open_catalog(target.url, target.schema)
    try:
        return select_objectives(conn, BASELINE, PracticeScope.SUBJECT_SIMULATION, subject).objectives
    finally:
        conn.close()


def stock(target, template_conn, per_cell=PER_CELL, subjects=tuple(SHAPE)):
    """Approved questions (current checker, accepted) for every evidencia and level of the given subjects."""
    clean(target.url)
    template = store_accepted(target.url, template_conn, "M01", 1, item(0), "medium")  # one real accepted row
    with psycopg.connect(target.url, autocommit=True) as db:
        for subject in subjects:
            n = 0
            for o in objectives_of(target, subject):
                for e in o["evidences"]:
                    for level in LEVELS:
                        for _ in range(per_cell):
                            it = variant(n % 150, f"{subject}-{n // 150}-")
                            db.execute(
                                """INSERT INTO generation.question_attempt (request_id, baseline_version,
                                       objective_code, evidence_id, difficulty, status, verdict, item_id,
                                       models_used, calls, tokens_in, tokens_out, cost_usd, cost_complete,
                                       checker_version, prompt_version, validation, item, reasons)
                                   SELECT %s, %s, %s, %s, %s, status, 'accept', %s, models_used, calls, tokens_in,
                                       tokens_out, cost_usd, cost_complete, %s, 'sizes-test', validation,
                                       item || %s, reasons
                                   FROM generation.question_attempt WHERE request_id = %s""",
                                (f"sz-{subject}-{n}", BASELINE, o["workbook_code"], e["id"], level,
                                 it["item_id"] + subject, CHECKER_VERSION,
                                 Jsonb({**{k: it[k] for k in ("stem", "options", "explanation", "subject_checks")},
                                        "item_id": it["item_id"] + subject, "subject": subject,
                                        "difficulty": level}), template))
                            n += 1
        db.execute("DELETE FROM generation.question_attempt WHERE request_id = %s", (template,))


@pytest.fixture(scope="module")
def runner():
    return FakeRunner()


@pytest.fixture(scope="module")
def client(sizes_target, runner):
    with TestClient(create_app(sizes_target.url, sizes_target.schema, BASELINE, practice_runner=runner,
                               bank_only=True)) as c:
        yield c


@pytest.fixture(scope="module")
def stocked(sizes_target, synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    template_conn = open_catalog(url, schema)  # TEST-v1 catalog: builds the one real accepted template row
    try:
        stock(sizes_target, template_conn)
    finally:
        template_conn.close()
    return sizes_target


def body(subject, size=None, difficulty="mixed"):
    out = {"subject": subject, "scope": "subject_simulation", "objective_codes": [], "difficulty": difficulty}
    if size is not None:
        out.update(question_count=size, source="bank_only", client_request_id=str(uuid.uuid4()))
    return out


# ---------------------------------------------------------------- every subject, every size (API)


@pytest.mark.parametrize("subject", list(SHAPE))
def test_every_size_composes_exactly_in_every_subject(subject, client, stocked, runner):
    calls = runner.calls
    offered = client.post("/api/practice/availability", json=body(subject)).json()
    assert offered["bank_counts"] == list(QUESTION_COUNTS), offered
    objectives = objectives_of(stocked, subject)
    for size in QUESTION_COUNTS:
        response = client.post("/api/practice/sessions", json=body(subject, size))
        assert response.status_code == 202, (subject, size, response.json())
        s = response.json()
        assert s["status"] == "complete" and s["composition"] == {"bank": size, "generated": 0}
        assert len(s["questions"]) == size == s["slots_total"]
        stems = [q["stem"] for q in s["questions"]]
        assert len(set(stems)) == size                                    # no question twice
        expected = {r["workbook_code"]: r["questions"] for r in allocate(objectives, size, "mixed")["allocation"]}
        assert Counter(q["objective_code"] for q in s["questions"]) == expected   # allocation unchanged (D2)
        assert {o["code"]: o["questions"] for o in s["objectives"]} == expected
        with psycopg.connect(stocked.url) as conn:
            allocation = conn.execute("SELECT allocation FROM practice.session WHERE session_id = %s",
                                      (s["session_id"],)).fetchone()[0]
        levels = Counter(slot["difficulty"] for row in allocation for slot in row["slots"])
        low, high = level_bounds(size)
        assert sum(levels.values()) == size and all(low <= levels[lv] <= high for lv in LEVELS), levels
    assert runner.calls == calls                                          # bank only: no model call


@pytest.mark.parametrize("subject", ["ciencias", "estudios_sociales"])
def test_scoring_history_and_tutor_analytics(subject, client, stocked):
    s = client.post("/api/practice/sessions", json=body(subject, 30)).json()
    correct = 0
    with psycopg.connect(stocked.url) as conn:
        keys = dict(conn.execute("SELECT slot, item->>'answer_key' FROM practice.item WHERE session_id = %s",
                                 (s["session_id"],)).fetchall())
    for q in s["questions"]:
        right = q["slot"] % 3 != 0
        label = keys[q["slot"]] if right else next(lb for lb in "ABCD" if lb != keys[q["slot"]])
        out = client.post(f"/api/practice/sessions/{s['session_id']}/answers",
                          json={"slot": q["slot"], "label": label}).json()
        assert out["correct"] is right
        correct += right
    assert out["summary"]["answered"] == 30 and out["summary"]["correct"] == correct == 20
    assert out["summary"]["percentage"] == 67
    results = PracticeResults(lambda: stocked.url)
    [row] = [h for h in results.history(subject=subject) if h["session_id"] == s["session_id"]]
    assert row["question_count"] == 30 and row["composition"] == {"bank": 30, "generated": 0}
    assert (row["answered"], row["correct"], row["state"]) == (30, 20, "completed")
    detail = results.detail(s["session_id"])
    assert len(detail["items"]) == 30 and Counter(i["result"] for i in detail["items"]) == {"correct": 20,
                                                                                            "incorrect": 10}
    assert {i["difficulty"] for i in detail["items"]} == set(LEVELS)
    groups = results.questions(subject=subject)["groups"]
    assert sum(g["answered"] for g in groups) >= 30


def test_a_short_bank_offers_only_what_composes_and_refuses_the_rest(sizes_target, synthetic_client, runner):
    url, schema = synthetic_client.app.state.catalog_target
    template_conn = open_catalog(url, schema)
    try:
        stock(sizes_target, template_conn, per_cell=1, subjects=("estudios_sociales",))  # 3 per objective
    finally:
        template_conn.close()
    with TestClient(create_app(sizes_target.url, sizes_target.schema, BASELINE, practice_runner=runner,
                               bank_only=True)) as c:
        calls = runner.calls
        offered = c.post("/api/practice/availability", json=body("estudios_sociales")).json()
        assert offered["bank_counts"] == [5, 10, 15]                      # 5 objectives × 3 questions
        with psycopg.connect(sizes_target.url) as conn:
            before = conn.execute("SELECT count(*) FROM practice.session").fetchone()[0]
        for size in (20, 25, 30):
            response = c.post("/api/practice/sessions", json=body("estudios_sociales", size))
            assert response.status_code == 409
            assert response.json()["error"] == "insufficient_inventory"
            assert (response.json()["requested"], response.json()["largest_available"]) == (size, 15)
        with psycopg.connect(sizes_target.url) as conn:
            assert conn.execute("SELECT count(*) FROM practice.session").fetchone()[0] == before
        assert c.post("/api/practice/sessions", json=body("estudios_sociales", 15)).status_code == 202
        offered = c.post("/api/practice/availability", json=body("ciencias")).json()
        assert offered["bank_counts"] == []                               # nothing stocked: bank offers nothing
        assert offered["question_counts"] == [5]                          # 5 stays (generation, T059)
        assert runner.calls == calls
    clean(sizes_target.url)


# ---------------------------------------------------------------- browser: desktop and phone (opt-in)


@pytest.fixture()
def server(stocked, runner):
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(stocked.url, stocked.schema, BASELINE, practice_runner=runner,
                                                   bank_only=True), host="127.0.0.1", port=port,
                                        log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/"
    srv.should_exit = True
    thread.join(timeout=10)


def shot(page, name):
    folder = os.environ.get("MENTOR_PRO_SHOTS")
    if folder:
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=True)


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
@pytest.mark.parametrize("viewport,subject", [({"width": 1280, "height": 800}, "ciencias"),
                                               ({"width": 390, "height": 844}, "estudios_sociales")],
                         ids=["desktop", "mobile"])
def test_a_thirty_question_practice_in_the_browser(server, runner, viewport, subject):
    from playwright.sync_api import expect, sync_playwright

    calls = runner.calls
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport)
        page.goto(server)
        page.check(f'input[name="subject"][value="{subject}"]')
        page.check('input[name="scope"][value="subject_simulation"]')
        page.check('input[name="difficulty"][value="mixed"]')
        for size in QUESTION_COUNTS:                                       # every size offered and enabled
            expect(page.locator(f'input[name="question_count"][value="{size}"]')).to_be_enabled()
        page.check('input[name="question_count"][value="30"]')
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")  # no sideways scroll
        shot(page, f"t069-{viewport['width']}-1-form-30")
        page.click("#submit")
        expect(page.locator("#quiz-view")).to_be_visible()
        expect(page.locator("#quiz-position")).to_contain_text("30")
        shot(page, f"t069-{viewport['width']}-2-quiz")
        for _ in range(30):
            page.locator('#quiz-options input[type="radio"]').first.check()
            page.click("#answer-submit")
            expect(page.locator("#feedback")).to_be_visible()
            page.click("#next")
        expect(page.locator("#result-view")).to_be_visible()
        total = int(page.locator("#result-correct").inner_text()) + int(page.locator("#result-incorrect").inner_text())
        assert total == 30
        shot(page, f"t069-{viewport['width']}-3-summary")
        assert runner.calls == calls
        browser.close()
