"""Browser regression for configurable practice (T048): sizes, bank-only quiz, shortage message.

Opt-in (needs Playwright Chromium): MENTOR_PRO_BROWSER=1. Screenshots go to MENTOR_PRO_SHOTS when set.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest

from app.main import create_app
from conftest import SYNTHETIC
from test_bank_only_practice import fill_bank, url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_practice_api import FakeRunner

pytestmark = pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")


@pytest.fixture()
def server(synthetic_client, url):  # noqa: F811
    import uvicorn

    target_url, schema = synthetic_client.app.state.catalog_target
    runner = FakeRunner()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(target_url, schema, SYNTHETIC, practice_runner=runner),
                                        host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", runner
    srv.should_exit = True
    thread.join(timeout=10)


def shot(page, name):
    folder = os.environ.get("MENTOR_PRO_SHOTS")
    if folder:
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=True)


def configure(page, count):
    page.check('input[name="subject"][value="matematicas"]')
    page.check('input[name="scope"][value="subject_simulation"]')
    page.check('input[name="difficulty"][value="mixed"]')
    page.check(f'input[name="question_count"][value="{count}"]')


def test_sizes_quiz_and_shortage_in_the_browser(server, url, catalog_conn):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, runner = server
    fill_bank(url, catalog_conn, per_cell=1)  # 12 questions (4 evidencias × 3 levels): 10 fits, 30 does not
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(base)
        sizes = page.locator('input[name="question_count"]')
        expect(sizes).to_have_count(6)
        assert [sizes.nth(i).get_attribute("value") for i in range(6)] == ["5", "10", "15", "20", "25", "30"]
        expect(page.locator('input[name="question_count"][value="5"]')).to_be_checked()
        expect(page.get_by_text("Por ahora las prácticas tienen 5 preguntas.")).to_have_count(0)
        page.check('input[name="subject"][value="matematicas"]')
        expect(sizes.nth(5)).to_be_enabled()  # the settings card opens once a subject is chosen
        assert all(sizes.nth(i).is_enabled() for i in range(6))

        configure(page, 30)
        shot(page, "1-form-30")
        page.click("#submit")
        error = page.locator("#form-error")
        expect(error).to_be_visible()
        expect(error).to_contain_text("Todavía no tenemos suficientes preguntas revisadas")
        retry = page.locator("#shortage-retry")
        expect(retry).to_be_visible()
        expect(retry).to_have_text("Hacer una práctica de 10 preguntas")
        shot(page, "2-shortage")

        retry.click()
        expect(page.locator("#quiz-view")).to_be_visible()
        expect(page.locator("#quiz-position")).to_contain_text("10")
        shot(page, "3-quiz-10")
        for _ in range(10):
            page.locator('#quiz-options input[type="radio"]').first.check()
            page.click("#answer-submit")
            expect(page.locator("#feedback")).to_be_visible()
            page.click("#next")
        shot(page, "4-summary")
        assert runner.calls == 0
        browser.close()
