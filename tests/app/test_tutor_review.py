"""T068: tutor question review in the browser, through the existing individual review (mentor_pro_test only).

Pending questions come from a real seeding run with a fake model; verdicts go through `item_review_record`.
API tests run always; the browser test is opt-in like the other browser regressions (MENTOR_PRO_BROWSER=1).
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.main import STATIC_DIR, SUBJECTS, ApiError, open_catalog
from app.practice import seeding
from app.practice.tutor_review import ReviewQueue, build_review_router
from conftest import SYNTHETIC
from test_bank_seeding import eligible, targeted, url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)

TOKEN = "tutor-review-token-0123456789abcdefgh"
GATEWAY = "127.0.0.1"
GOOD = {"X-Tutor-Token": TOKEN}


def review_app(url, schema):
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def api_error(_, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message_es": exc.message_es})

    queue = ReviewQueue(lambda: url, SYNTHETIC, SUBJECTS, lambda u: open_catalog(u, schema))
    app.include_router(build_review_router(queue, ApiError, TOKEN, frozenset({GATEWAY})))

    @app.get("/api/tutor/queue")  # the writing queue the page opens after login (not under test here)
    def writing_queue(request: Request):
        if request.headers.get("x-tutor-token") != TOKEN:
            raise ApiError(403, "tutor_only", "Acceso solo para el tutor.")
        return {"submissions": []}

    @app.get("/tutor")
    def page():
        return FileResponse(STATIC_DIR / "tutor.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def call(app, path, method="GET", json=None, headers=GOOD, client_ip=GATEWAY):
    transport = httpx.ASGITransport(app=app, client=(client_ip, 40000))

    async def go():
        async with httpx.AsyncClient(transport=transport, base_url="http://tutor") as c:
            return await c.request(method, path, json=json, headers=headers)

    return asyncio.run(go())


@pytest.fixture()
def pending(url, catalog_conn, synthetic_client):  # noqa: F811
    batch_id = targeted(url, catalog_conn, "M02")["batch_id"]  # two generated questions, cells 3 and 4
    _, schema = synthetic_client.app.state.catalog_target
    return review_app(url, schema), batch_id


def reviews(url, request_id):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT verdict, reason, reviewer, comment, recorded_at FROM generation.bank_item_review "
                            "WHERE request_id = %s", (request_id,)).fetchall()


def test_queue_lists_pending_questions_with_key_and_grounding(pending):
    app, batch_id = pending
    out = call(app, "/api/tutor/review/queue").json()
    qs = out["questions"]
    assert [q["cell"] for q in qs] == [3, 4] and {q["subject"] for q in qs} == {"matematicas"}
    q = qs[0]
    assert q["batch_id"] == batch_id and q["answer_key"] == "B" and len(q["options"]) == 4
    assert q["objective_code"] == "M02" and q["objective_es"] and "evidencia_es" in q and q["explanation"]
    assert "verdict" not in q
    mat = next(c for c in out["counts"] if c["subject"] == "matematicas")
    assert mat == {"subject": "matematicas", "name_es": mat["name_es"], "pending": 2, "approved": 0, "quarantined": 0}
    assert set(out["reasons"]) == set(seeding.REASONS)


def test_filters(pending):
    app, batch_id = pending
    assert len(call(app, "/api/tutor/review/queue?subject=matematicas&objective=m02").json()["questions"]) == 2
    assert call(app, "/api/tutor/review/queue?objective=M01").json()["questions"] == []
    assert call(app, "/api/tutor/review/queue?subject=espanol").json()["questions"] == []
    hard = call(app, "/api/tutor/review/queue?difficulty=hard").json()["questions"]
    assert [q["difficulty"] for q in hard] == ["hard"]
    assert call(app, "/api/tutor/review/queue?batch=other").json()["questions"] == []
    assert len(call(app, f"/api/tutor/review/queue?batch={batch_id}").json()["questions"]) == 2
    assert call(app, "/api/tutor/review/queue?subject=nope").status_code == 422
    assert call(app, "/api/tutor/review/queue?difficulty=mixed").status_code == 422


def test_authorization_is_required(pending, url):  # noqa: F811
    app, _ = pending
    q = call(app, "/api/tutor/review/queue").json()["questions"][0]
    body = {"request_id": q["request_id"], "verdict": "approved"}
    assert call(app, "/api/tutor/review/queue", headers={}).status_code == 403
    assert call(app, "/api/tutor/review/queue", headers={"X-Tutor-Token": "x" * 40}).status_code == 403
    assert call(app, "/api/tutor/review/queue", client_ip="10.0.0.9").status_code == 403
    assert call(app, "/api/tutor/review/decisions", "POST", body, headers={}).status_code == 403
    assert call(app, "/api/tutor/review/decisions", "POST", body, client_ip="10.0.0.9").status_code == 403
    assert reviews(url, q["request_id"]) == []


def test_approve_and_quarantine_once_with_audit_trail(pending, url, catalog_conn):  # noqa: F811
    app, batch_id = pending
    qs = {q["cell"]: q["request_id"] for q in call(app, "/api/tutor/review/queue").json()["questions"]}
    assert eligible(url, catalog_conn, 3) == []                                   # pending: never eligible
    bad = call(app, "/api/tutor/review/decisions", "POST", {"request_id": qs[4], "verdict": "quarantined"})
    assert bad.status_code == 422 and bad.json()["error"] == "reason_required"
    assert call(app, "/api/tutor/review/decisions", "POST",
                {"request_id": qs[4], "verdict": "approved", "reason": "level"}).status_code == 422
    assert call(app, "/api/tutor/review/decisions", "POST", {"request_id": qs[4], "verdict": "maybe"}).status_code == 422

    ok = call(app, "/api/tutor/review/decisions", "POST",
              {"request_id": qs[3], "verdict": "approved", "comment": "  Bien planteada.  "})
    assert ok.status_code == 200 and ok.json()["approved"] == 1
    mat = next(c for c in ok.json()["counts"] if c["subject"] == "matematicas")
    assert (mat["pending"], mat["approved"], mat["quarantined"]) == (1, 1, 0)
    assert [r["request_id"] for r in eligible(url, catalog_conn, 3)] == [qs[3]]

    q = call(app, "/api/tutor/review/decisions", "POST",
             {"request_id": qs[4], "verdict": "quarantined", "reason": "ambiguous", "comment": "Dos opciones válidas."})
    assert q.status_code == 200
    assert eligible(url, catalog_conn, 4, include_held=True) == []

    [(verdict, reason, reviewer, comment, at)] = reviews(url, qs[3])
    assert (verdict, reason, reviewer, comment) == ("approved", "approved", "tutor", "Bien planteada.") and at
    [(verdict, reason, reviewer, comment, _)] = reviews(url, qs[4])
    assert (verdict, reason, reviewer, comment) == ("quarantined", "ambiguous", "tutor", "Dos opciones válidas.")

    again = call(app, "/api/tutor/review/decisions", "POST", {"request_id": qs[3], "verdict": "quarantined",
                                                               "reason": "other"})
    assert again.status_code == 409 and again.json()["error"] == "already_reviewed"
    assert len(reviews(url, qs[3])) == 1 and call(app, "/api/tutor/review/queue").json()["questions"] == []
    assert seeding.get_batch(url, batch_id)["review_status"] == "pending"        # the batch gate is untouched
    unknown = call(app, "/api/tutor/review/decisions", "POST", {"request_id": "req-none", "verdict": "approved"})
    assert unknown.status_code == 409


def test_simultaneous_submissions_record_one_verdict(pending, url):  # noqa: F811
    app, _ = pending
    rid = call(app, "/api/tutor/review/queue").json()["questions"][0]["request_id"]
    body = {"request_id": rid, "verdict": "approved"}
    with ThreadPoolExecutor(4) as pool:
        codes = sorted(pool.map(lambda _: call(app, "/api/tutor/review/decisions", "POST", body).status_code, range(4)))
    assert codes == [200, 409, 409, 409] and len(reviews(url, rid)) == 1


def test_review_is_not_in_the_student_app(synthetic_client):
    assert synthetic_client.get("/api/tutor/review/queue").status_code == 404
    assert synthetic_client.post("/api/tutor/review/decisions", json={}).status_code in (404, 405)
    index = (STATIC_DIR / "index.html").read_text(encoding="utf-8") + (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "review/decisions" not in index


def test_the_tutor_service_serves_the_review_routes():
    from app.tutor_main import create_tutor_app

    paths = {r.path for r in create_tutor_app("postgresql://unused/x", TOKEN, GATEWAY).routes}
    assert {"/api/tutor/review/queue", "/api/tutor/review/decisions"} <= paths


# ---------------------------------------------------------------- browser (opt-in)


@pytest.fixture()
def server(pending):
    import uvicorn

    app, batch_id = pending
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
def test_review_in_the_browser(server, url):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base)
        page.fill("#tutor-token", "wrong-token-0123456789abcdefghijkl")
        page.click("#tutor-enter")
        expect(page.locator("#tutor-login")).to_be_visible()                 # wrong code: back to login
        expect(page.locator("#tutor-nav")).to_be_hidden()
        expect(page.locator("#tutor-review")).to_be_hidden()

        page.fill("#tutor-token", TOKEN)
        page.click("#tutor-enter")
        page.click("#tutor-nav-review")
        expect(page.locator("#review-progress")).to_have_text("Pregunta 1 de 2")
        expect(page.locator("#review-options li.review-key")).to_have_count(1)
        expect(page.locator("#review-options li.review-key")).to_contain_text("Respuesta propuesta")
        expect(page.locator("#review-counts [data-subject=matematicas]")).to_contain_text("por revisar 2")
        first = page.locator("#review-item").get_attribute("data-request")

        page.click("#review-submit")                                          # nothing chosen: refused
        expect(page.locator("#tutor-error")).to_contain_text("Elegí aprobar o cuarentena")
        page.check('input[name="review-verdict"][value="quarantined"]')
        page.click("#review-submit")                                          # no reason: refused
        expect(page.locator("#tutor-error")).to_contain_text("motivo")
        assert reviews(url, first) == []

        page.click("#review-skip")
        expect(page.locator("#review-progress")).to_have_text("Pregunta 2 de 2")
        page.click("#review-skip")
        expect(page.locator("#review-progress")).to_have_text("Pregunta 1 de 2")

        page.check('input[name="review-verdict"][value="approved"]')
        page.fill("#review-comment", "Clara y correcta.")
        page.locator("#review-submit").dblclick()                             # a double click records once
        expect(page.locator("#review-saved")).to_contain_text("Aprobada")
        expect(page.locator("#review-progress")).to_have_text("Pregunta 1 de 1")
        expect(page.locator("#review-counts [data-subject=matematicas]")).to_contain_text("aprobadas 1")
        assert [r[:4] for r in reviews(url, first)] == [("approved", "approved", "tutor", "Clara y correcta.")]

        second = page.locator("#review-item").get_attribute("data-request")
        page.check('input[name="review-verdict"][value="quarantined"]')
        page.select_option("#review-reason", "wrong_key")
        page.click("#review-submit")
        expect(page.locator("#review-empty")).to_be_visible()
        expect(page.locator("#review-counts [data-subject=matematicas]")).to_contain_text("en cuarentena 1")
        assert [r[:3] for r in reviews(url, second)] == [("quarantined", "wrong_key", "tutor")]

        # A stale second tab submitting the same question is refused and records nothing more.
        out = page.evaluate("""async (rid) => (await fetch('/api/tutor/review/decisions', {method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-Tutor-Token': sessionStorage.getItem('mentorpro.tutor')},
            body: JSON.stringify({request_id: rid, verdict: 'approved'})})).status""", second)
        assert out == 409 and len(reviews(url, second)) == 1
        browser.close()
