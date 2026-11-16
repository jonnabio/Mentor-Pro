"""T069: tutor coverage view (sizes per subject, blockers, pending that could close them). mentor_pro_test only.

The synthetic Matemáticas bank: a 6-cell seeding plan whose M02 run left two generated questions awaiting review,
plus one approved question per evidencia and level (12). The composer builds 5 and 10; 15 lacks 2 questions in
M02 and 2 in M03, and M02's two pending questions could close half of it. The view never counts pending questions
as available and records nothing.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import psycopg
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.main import STATIC_DIR, SUBJECTS, ApiError, open_catalog
from app.practice.tutor_coverage import CoverageReport, build_coverage_router
from conftest import SYNTHETIC
from test_bank_only_practice import fill_bank
from test_bank_seeding import targeted, url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_tutor_review import GATEWAY, GOOD, TOKEN, call


def coverage_app(url, schema):
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()

    @app.exception_handler(ApiError)
    async def api_error(_, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "message_es": exc.message_es})

    report = CoverageReport(lambda: url, SYNTHETIC, SUBJECTS, lambda u: open_catalog(u, schema))
    app.include_router(build_coverage_router(report, ApiError, TOKEN, frozenset({GATEWAY})))

    @app.get("/api/tutor/queue")
    def writing_queue(request: Request):
        if request.headers.get("x-tutor-token") != TOKEN:
            raise ApiError(403, "tutor_only", "Acceso solo para el tutor.")
        return {"submissions": []}

    @app.get("/tutor")
    def page():
        return FileResponse(STATIC_DIR / "tutor.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


@pytest.fixture()
def bank(url, catalog_conn, synthetic_client):  # noqa: F811
    targeted(url, catalog_conn, "M02")          # two generated questions awaiting review (M02 easy and hard)
    fill_bank(url, catalog_conn, per_cell=1)    # 12 approved: M01 6, M02 3, M03 3
    _, schema = synthetic_client.app.state.catalog_target
    return coverage_app(url, schema)


def counts(url):
    with psycopg.connect(url) as conn:
        return [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("generation.bank_item_review", "practice.session", "generation.question_attempt")]


def test_sizes_blockers_and_pending_per_subject(bank, url):  # noqa: F811
    before = counts(url)
    response = call(bank, "/api/tutor/coverage?subject=matematicas")
    assert response.status_code == 200, response.json()
    out = response.json()
    assert out["available_sizes"] == [5, 10] and out["next_size"] == 15
    assert (out["approved"], out["pending"], out["plan_cells"], out["objectives"]) == (12, 2, 6, 3)
    by_size = {s["size"]: s for s in out["sizes"]}
    assert by_size[10]["available"] and not by_size[15]["available"]
    fifteen = by_size[15]
    assert fifteen["missing"] == {"plan": 9, "generated": 2, "approved": 4}
    assert (fifteen["first_failure"], fifteen["blocker"]) == ("plan", "structural")   # a 6-cell plan holds 6
    gap = {b["objective_code"]: b for b in fifteen["gap"]["objectives"]}
    assert gap["M02"] == {"objective_code": "M02", "needed": 5, "approved": 3, "missing": 2, "pending": 2}
    assert gap["M03"]["missing"] == 2 and gap["M03"]["pending"] == 0
    assert "M01" not in gap
    assert out["progress"] == {"size": 30, "approved_fill": 12, "with_pending_fill": 14, "plan_fill": 6}
    m02 = next(c for c in out["cells"] if c["objective_code"] == "M02")
    assert m02["easy"] == {"approved": 1, "pending": 1, "plan": 1} and m02["hard"]["pending"] == 1
    assert counts(url) == before                                                     # read-only


def test_other_subjects_without_a_bank_report_nothing_available(bank):
    out = call(bank, "/api/tutor/coverage?subject=matematicas").json()
    assert {s["subject"] for s in out["subjects"]} == {c for c, _ in SUBJECTS}
    response = call(bank, "/api/tutor/coverage?subject=espanol")                    # EL01 only, no questions
    assert response.status_code == 200
    out = response.json()
    assert out["available_sizes"] == [] and out["next_size"] == 5 and out["approved"] == 0
    assert out["sizes"][0]["blocker"] in ("generation", "structural")


def test_unknown_subject_and_authorization(bank):
    assert call(bank, "/api/tutor/coverage?subject=fisica").status_code == 422
    assert call(bank, "/api/tutor/coverage?subject=matematicas", headers={}).status_code == 403
    assert call(bank, "/api/tutor/coverage?subject=matematicas", client_ip="10.0.0.9").status_code == 403


def test_the_tutor_service_serves_the_coverage_route():
    from app.tutor_main import create_tutor_app

    app = create_tutor_app("postgresql://unused@127.0.0.1:1/x_test", "tutor-service-token-0123456789abcdef",
                           "172.19.0.1")
    assert "/api/tutor/coverage" in {r.path for r in app.routes}


def test_coverage_is_not_in_the_student_app(synthetic_client):
    assert synthetic_client.get("/api/tutor/coverage?subject=matematicas").status_code == 404


# ---------------------------------------------------------------- browser (opt-in)


@pytest.fixture()
def server(bank):
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(bank, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/tutor"
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
@pytest.mark.parametrize("viewport", [{"width": 1280, "height": 800}, {"width": 390, "height": 844}],
                         ids=["desktop", "mobile"])
def test_coverage_in_the_browser(server, viewport):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport)
        page.goto(server)
        page.fill("#tutor-token", TOKEN)
        page.click("#tutor-enter")
        page.click("#tutor-nav-coverage")
        expect(page.locator("#tutor-coverage")).to_be_visible()
        expect(page.locator("#cv-summary")).to_contain_text("tamaños disponibles 5, 10")
        expect(page.locator("#cv-summary")).to_contain_text("por revisar 2")
        expect(page.locator("#cv-sizes li")).to_have_count(6)
        expect(page.locator('#cv-sizes [data-size="10"]')).to_contain_text("disponible")
        expect(page.locator('#cv-sizes [data-size="15"]')).to_contain_text("Faltan 4 aprobadas")
        expect(page.locator('#cv-sizes [data-size="15"]')).to_contain_text("plan de generación")
        expect(page.locator("#cv-next-title")).to_have_text("Qué falta para 15 preguntas")
        expect(page.locator('#cv-blockers [data-blocker="M02"]')).to_contain_text("faltan 2 · por revisar 2")
        expect(page.locator("#cv-progress")).to_contain_text("12 de 30")
        page.locator("#cv-cells-block summary").click()
        expect(page.locator('#cv-cells [data-objective="M02"]')).to_contain_text("1 / 1 / 1")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")  # no sideways scroll
        folder = os.environ.get("MENTOR_PRO_SHOTS")
        if folder:
            page.screenshot(path=str(Path(folder) / f"t069-coverage-{viewport['width']}.png"), full_page=True)
        page.select_option("#cv-subject", "espanol")
        expect(page.locator("#cv-summary")).to_contain_text("Español: tamaños disponibles ninguno")
        browser.close()
