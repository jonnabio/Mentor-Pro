"""T071: tutor bulk approval of explicitly selected pending questions (mentor_pro_test only).

Pending questions come from a real seeding run with a fake model (six cells). Every approval goes through the
existing `item_review_record`, so the audit row, the lock and the exactly-once rule are the T068 ones. API tests
run always; the browser test is opt-in like the other browser regressions (MENTOR_PRO_BROWSER=1).
"""

from __future__ import annotations

import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app.practice import seeding
from app.practice.tutor_review import BULK_MAX
from test_bank_seeding import eligible, seed_run, url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_tutor_review import GATEWAY, GOOD, TOKEN, call, review_app, reviews

BULK = "/api/tutor/review/bulk-approve"
QUEUE = "/api/tutor/review/queue"


@pytest.fixture()
def six(url, catalog_conn, synthetic_client):  # noqa: F811
    batch_id = seed_run(url, catalog_conn)["batch_id"]  # six generated questions, cells 1..6, all pending
    _, schema = synthetic_client.app.state.catalog_target
    return review_app(url, schema), batch_id


def ids(app, query=""):
    return [q["request_id"] for q in call(app, QUEUE + query).json()["questions"]]


def all_reviews(url):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT request_id, verdict, reason, reviewer FROM generation.bank_item_review "
                            "ORDER BY request_id").fetchall()


def test_pagination_is_page_scoped_and_respects_filters(six):
    app, _ = six
    everything = ids(app)
    assert len(everything) == 6                                                   # no paging: the T068 full list
    first = call(app, QUEUE + "?page=1&page_size=4").json()
    second = call(app, QUEUE + "?page=2&page_size=4").json()
    assert first["pagination"] == {"page": 1, "page_size": 4, "pages": 2} and first["total"] == 6
    assert [q["request_id"] for q in first["questions"] + second["questions"]] == everything
    assert len(second["questions"]) == 2
    assert call(app, QUEUE + "?page=9&page_size=4").json()["pagination"]["page"] == 2  # clamped to the last page
    hard = call(app, QUEUE + "?difficulty=hard&page=1&page_size=1").json()
    assert hard["total"] == 2 and hard["pagination"]["pages"] == 2 and hard["questions"][0]["difficulty"] == "hard"
    assert call(app, QUEUE + "?page_size=51").status_code == 422
    assert call(app, QUEUE + "?page=0").status_code == 422
    q = first["questions"][0]                                                     # full inspection data
    assert q["answer_key"] and q["explanation"] and q["options"] and q["objective_code"]


def test_single_and_multiple_approval_with_audit(six, url, catalog_conn):  # noqa: F811
    app, batch_id = six
    queue = call(app, QUEUE).json()["questions"]
    by_cell = {q["cell"]: q["request_id"] for q in queue}
    assert eligible(url, catalog_conn, 3) == []                                   # pending: never served

    one = call(app, BULK, "POST", {"request_ids": [by_cell[3]]}).json()
    assert (one["requested"], one["approved"], one["failed"]) == (1, 1, 0)
    assert one["results"] == [{"request_id": by_cell[3], "status": "approved"}]
    assert [r["request_id"] for r in eligible(url, catalog_conn, 3)] == [by_cell[3]]

    many = call(app, BULK, "POST", {"request_ids": [by_cell[1], by_cell[5], by_cell[6]]}).json()
    assert many["approved"] == 3 and many["failed"] == 0
    mat = next(c for c in many["counts"] if c["subject"] == "matematicas")
    assert (mat["pending"], mat["approved"], mat["quarantined"]) == (2, 4, 0)
    rows = {r[0]: r[1:] for r in all_reviews(url)}
    assert set(rows) == {by_cell[c] for c in (1, 3, 5, 6)}
    assert set(rows.values()) == {("approved", "approved", "tutor")}               # same audit row as T068
    assert sorted(ids(app)) == sorted([by_cell[2], by_cell[4]])                   # others stay pending
    assert seeding.get_batch(url, batch_id)["review_status"] == "pending"        # the batch gate is untouched
    with psycopg.connect(url) as conn:                                            # curriculum mapping preserved
        links = {r[0]: r[1] for r in conn.execute(
            "SELECT request_id, cell FROM generation.bank_batch_item WHERE active AND batch_id = %s", (batch_id,))}
    assert all(links[by_cell[c]] == c for c in (1, 3, 5, 6))


def test_partial_failure_reports_each_id_and_keeps_state_consistent(six, url):  # noqa: F811
    app, batch_id = six
    a, b, c, d = ids(app)[:4]
    seeding.item_review_record(url, batch_id, [{"request_id": b, "verdict": "quarantined", "reason": "ambiguous"}])
    seeding.item_review_record(url, batch_id, [{"request_id": c, "verdict": "approved"}])
    out = call(app, BULK, "POST", {"request_ids": [a, b, c, "req-none", d]}).json()
    assert (out["requested"], out["approved"], out["failed"]) == (5, 2, 3)
    assert [r["status"] for r in out["results"]] == ["approved", "already_reviewed", "already_reviewed",
                                                      "not_pending", "approved"]
    rows = {r[0]: r[1] for r in all_reviews(url)}
    assert rows == {a: "approved", b: "quarantined", c: "approved", d: "approved"}  # quarantine not overridden
    assert len(reviews(url, b)) == 1 and len(reviews(url, c)) == 1


def test_repeated_submission_records_once(six, url):  # noqa: F811
    app, _ = six
    a, b = ids(app)[:2]
    assert call(app, BULK, "POST", {"request_ids": [a, b]}).json()["approved"] == 2
    again = call(app, BULK, "POST", {"request_ids": [a, b]}).json()
    assert again["approved"] == 0 and {r["status"] for r in again["results"]} == {"already_reviewed"}
    assert len(reviews(url, a)) == 1 and len(reviews(url, b)) == 1


def test_simultaneous_bulk_submissions_record_one_verdict_each(six, url):  # noqa: F811
    app, _ = six
    chosen = ids(app)
    with ThreadPoolExecutor(4) as pool:
        outs = list(pool.map(lambda _: call(app, BULK, "POST", {"request_ids": chosen}).json(), range(4)))
    assert sum(o["approved"] for o in outs) == 6
    assert [len(reviews(url, r)) for r in chosen] == [1] * 6


def test_invalid_payloads_are_refused_without_recording(six, url):  # noqa: F811
    app, _ = six
    a = ids(app)[0]
    dup = call(app, BULK, "POST", {"request_ids": [a, a]})
    assert dup.status_code == 422 and dup.json()["error"] == "duplicate_ids"
    many = call(app, BULK, "POST", {"request_ids": [f"req-{i}" for i in range(BULK_MAX + 1)]})
    assert many.status_code == 422 and many.json()["error"] == "too_many"
    assert call(app, BULK, "POST", {"request_ids": []}).status_code == 422
    assert call(app, BULK, "POST", {"request_ids": [""]}).status_code == 422
    assert call(app, BULK, "POST", {"request_ids": ["x" * 65]}).status_code == 422
    assert call(app, BULK, "POST", {}).status_code == 422
    assert all_reviews(url) == []


def test_bulk_approval_requires_the_tutor(six, url):  # noqa: F811
    app, _ = six
    body = {"request_ids": ids(app)[:2]}
    assert call(app, BULK, "POST", body, headers={}).status_code == 403
    assert call(app, BULK, "POST", body, headers={"X-Tutor-Token": "x" * 40}).status_code == 403
    assert call(app, BULK, "POST", body, client_ip="10.0.0.9").status_code == 403
    assert all_reviews(url) == []


def test_bulk_route_is_only_in_the_tutor_service(synthetic_client):
    from app.main import STATIC_DIR
    from app.tutor_main import create_tutor_app

    assert synthetic_client.post(BULK, json={"request_ids": ["x"]}).status_code in (404, 405)
    paths = {r.path for r in create_tutor_app("postgresql://unused/x", TOKEN, GATEWAY).routes}
    assert BULK in paths
    student = (STATIC_DIR / "index.html").read_text(encoding="utf-8") + (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "bulk-approve" not in student


# ---------------------------------------------------------------- browser (opt-in)


@pytest.fixture()
def server(six):
    import uvicorn

    app, batch_id = six
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/tutor", batch_id
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
def test_bulk_approval_in_the_browser(server, url):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, batch_id = server
    shots = os.environ.get("MENTOR_PRO_SCREENSHOTS")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script("window.__bulkPageSize = 4")
        page.goto(base)
        page.fill("#tutor-token", TOKEN)
        page.click("#tutor-enter")
        page.click("#tutor-nav-review")
        rows = page.locator("#bulk-list .bulk-row")
        expect(rows).to_have_count(4)                                         # page 1 of 2
        expect(page.locator("#bulk-page")).to_contain_text("Página 1 de 2 · 6 por revisar")
        expect(page.locator("#bulk-approve")).to_be_disabled()
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")

        rows.nth(0).locator("summary").click()                                # full inspection
        expect(rows.nth(0).locator("li.review-key")).to_contain_text("Respuesta propuesta")
        expect(rows.nth(0).locator(".bulk-explanation")).to_contain_text("Explicación:")

        rows.nth(0).locator(".bulk-check").check()                            # single selection
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (1)")
        page.click("#bulk-select-page")                                       # page-scoped select all
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (4)")
        page.click("#bulk-clear")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")

        page.click("#bulk-select-page")
        page.click("#bulk-next")                                              # page change resets the selection
        expect(page.locator("#bulk-page")).to_contain_text("Página 2 de 2")
        expect(rows).to_have_count(2)
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        page.click("#bulk-prev")

        page.click("#bulk-select-page")
        page.select_option("#rf-difficulty", "hard")                          # a filter change resets it too
        page.click("#review-filters button[type=submit]")
        expect(page.locator("#bulk-page")).to_contain_text("2 por revisar")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        page.click("#rf-clear")
        expect(page.locator("#bulk-page")).to_contain_text("6 por revisar")

        page.click("#bulk-select-page")
        page.once("dialog", lambda d: d.dismiss())                            # cancelled: nothing recorded
        page.click("#bulk-approve")
        assert all_reviews(url) == []

        if shots:
            page.screenshot(path=os.path.join(shots, "bulk-selected.png"), full_page=True)
        # One of the selected questions is decided elsewhere first: the result reports a partial failure.
        taken = rows.nth(1).get_attribute("data-request")
        seeding.item_review_record(url, batch_id, [{"request_id": taken, "verdict": "approved"}])
        messages = []
        page.once("dialog", lambda d: (messages.append(d.message), d.accept()))
        page.click("#bulk-approve")
        expect(page.locator("#bulk-result")).to_contain_text("Se aprobaron 3 de 4 preguntas. No se aprobaron:")
        expect(page.locator("#bulk-result")).to_contain_text("ya tenía una decisión")
        assert messages and "¿Aprobar 4 preguntas?" in messages[0]
        expect(page.locator("#bulk-page")).to_contain_text("Página 1 de 1 · 2 por revisar")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        expect(page.locator("#review-counts [data-subject=matematicas]")).to_contain_text("aprobadas 4")
        if shots:
            page.screenshot(path=os.path.join(shots, "bulk-result.png"), full_page=True)
        assert len(all_reviews(url)) == 4 and {r[1] for r in all_reviews(url)} == {"approved"}
        browser.close()


# ---------------------------------------------------------------- structured stimulus (PR #77 review)

TABLE = {"type": "table", "text": "Ventas de la feria\n| Puesto | Lunes | Martes |\n| --- | --- | --- |\n"
                                  "| Frutas | 12 | 15 |\n| Pan | 8 | 11 |"}
TEXT = {"type": "text", "text": "En la feria hay cuatro puestos.\nCada puesto vende frutas."}


def set_stimulus(url, request_id, stimulus):  # noqa: F811
    from psycopg.types.json import Jsonb

    with psycopg.connect(url) as conn:  # synthetic test database only
        conn.execute("UPDATE generation.question_attempt SET item = jsonb_set(item::jsonb, '{stimulus}', %s) "
                     "WHERE request_id = %s", (Jsonb(stimulus), request_id))


def test_the_queue_returns_the_structured_stimulus_unchanged(six, url):  # noqa: F811
    app, _ = six
    rid = ids(app)[0]
    set_stimulus(url, rid, TABLE)
    q = next(q for q in call(app, QUEUE).json()["questions"] if q["request_id"] == rid)
    assert q["stimulus"] == TABLE


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
def test_stimulus_rendering_cases(server):
    from playwright.sync_api import sync_playwright

    base, _ = server
    cases = {
        "none": {"type": "none"}, "missing": None, "empty": {"type": "text", "text": "  "},
        "plain": "Texto simple de un registro anterior.", "text": TEXT, "table": TABLE,
        "tabs": {"type": "table", "text": "Mes\tLluvia\nEnero\t20\nFebrero\t35"},
        "loose": {"type": "table", "text": "Lunes: 12 frutas\nMartes: 15 frutas"},
        "unsafe": {"type": "text", "text": "<img src=x onerror=\"window.hacked=1\"><b>negrita</b>"},
    }
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(base)
        out = page.evaluate("""(cases) => Object.fromEntries(Object.entries(cases).map(([k, s]) => {
            const n = renderStimulus(s);
            if (n) document.body.append(n);
            return [k, n && { text: n.textContent, html: n.innerHTML,
              rows: [...n.querySelectorAll('tr')].map((r) => [...r.children].map((c) => c.tagName + ':' + c.textContent)),
              paras: [...n.querySelectorAll('p')].map((x) => x.textContent) }];
        }))""", cases)
        assert out["none"] is None and out["missing"] is None and out["empty"] is None
        assert out["plain"]["text"] == cases["plain"] and out["plain"]["rows"] == []
        assert out["text"]["text"] == TEXT["text"] and out["text"]["rows"] == []          # line breaks kept
        assert out["table"]["paras"] == ["Ventas de la feria"]
        assert out["table"]["rows"] == [["TH:Puesto", "TH:Lunes", "TH:Martes"], ["TD:Frutas", "TD:12", "TD:15"],
                                        ["TD:Pan", "TD:8", "TD:11"]]                        # separator dropped
        assert out["tabs"]["rows"] == [["TH:Mes", "TH:Lluvia"], ["TD:Enero", "TD:20"], ["TD:Febrero", "TD:35"]]
        assert out["loose"]["rows"] == [] and out["loose"]["text"] == cases["loose"]["text"]  # nothing dropped
        assert out["unsafe"]["text"] == cases["unsafe"]["text"] and "<img" not in out["unsafe"]["html"]
        assert page.evaluate("window.hacked === undefined && document.querySelectorAll('img').length === 0")
        browser.close()


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
def test_structured_stimulus_in_both_review_views(server, url):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    shots = os.environ.get("MENTOR_PRO_SCREENSHOTS")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base)
        page.fill("#tutor-token", TOKEN)
        page.click("#tutor-enter")
        page.click("#tutor-nav-review")
        expect(page.locator("#bulk-list .bulk-row")).to_have_count(6)          # the queue has loaded
        first = page.locator("#review-item").get_attribute("data-request")
        second = page.locator("#bulk-list .bulk-row").nth(1).get_attribute("data-request")
        set_stimulus(url, first, TABLE)
        set_stimulus(url, second, TEXT)
        page.click("#review-filters button[type=submit]")                     # reload with the stimuli

        individual = page.locator("#review-stimulus")                          # individual review
        expect(individual).to_be_visible()
        expect(individual.locator("table th")).to_have_text(["Puesto", "Lunes", "Martes"])
        expect(individual.locator("table tr")).to_have_count(3)
        expect(individual).not_to_contain_text("[object Object]")
        page.click("#review-skip")
        expect(individual).to_have_text(TEXT["text"])
        page.click("#review-skip")
        expect(individual).to_be_hidden()                                     # type none: nothing shown

        row = page.locator(f'#bulk-list .bulk-row[data-request="{first}"]')    # bulk review
        row.locator("summary").click()
        expect(row.locator("table td")).to_have_text(["Frutas", "12", "15", "Pan", "8", "11"])
        expect(row.locator(".bulk-explanation")).to_contain_text("Explicación:")
        expect(row.locator("li.review-key")).to_contain_text("Respuesta propuesta")
        plain = page.locator(f'#bulk-list .bulk-row[data-request="{second}"]')
        plain.locator("summary").click()
        expect(plain.locator(".stimulus")).to_have_text(TEXT["text"])
        expect(page.locator("#tutor-review")).not_to_contain_text("[object Object]")
        if shots:
            page.screenshot(path=os.path.join(shots, "structured-stimulus.png"), full_page=True)
        browser.close()
