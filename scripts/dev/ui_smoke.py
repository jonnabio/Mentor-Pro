"""Browser smoke test of the practice-configuration UI on desktop and mobile.

Starts the app on a local port against DATABASE_URL, drives it with Playwright
using the installed Microsoft Edge (no browser download), checks the three
selection scopes and horizontal overflow, and saves screenshots.

Usage:
    DATABASE_URL=... .venv/Scripts/python.exe scripts/dev/ui_smoke.py [--out DIR]
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.main import create_app  # noqa: E402

PORT = 8765
VIEWPORTS = {"desktop": {"width": 1280, "height": 900}, "mobile": {"width": 390, "height": 844}}


def no_horizontal_overflow(page: Page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def run_flow(page: Page, out: Path, name: str) -> list[str]:
    results = []
    page.goto(f"http://127.0.0.1:{PORT}/")
    expect(page.locator("#subjects label")).to_have_count(4)
    results.append("4 subjects shown")

    # Single objective
    page.get_by_label("Matemáticas").check()
    expect(page.locator('input[name="objective"]')).to_have_count(22)
    page.locator('input[name="objective"][value="M07"]').check()
    page.get_by_label("Mixta").check()
    page.get_by_label("20", exact=True).check()
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#summary-rows tr")).to_have_count(1)
    expect(page.locator("#summary-meta")).to_contain_text("Mixta")
    results.append("single objective M07: 1 row, 20 questions")

    # Several objectives
    page.get_by_label("Varios objetivos").check()
    expect(page.get_by_role("button", name="Generar práctica")).to_be_disabled()
    for code in ("M01", "M14", "M22"):
        page.locator(f'input[name="objective"][value="{code}"]').check()
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#summary-rows tr")).to_have_count(3)
    results.append("selected objectives: 3 rows")

    # All objectives with fewer questions than objectives
    page.get_by_label("Ciencias").check()
    page.get_by_label("Todos los objetivos").check()
    page.get_by_label("5", exact=True).check()
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#summary-rows tr")).to_have_count(5)
    expect(page.locator("#summary-coverage")).to_contain_text("no se cubren todos")
    results.append("all Ciencias objectives, 5 questions: 5 covered, rest reported")

    page.screenshot(path=str(out / f"ui-{name}.png"), full_page=True)
    overflow_ok = no_horizontal_overflow(page)
    results.append(f"no horizontal overflow: {overflow_ok}")
    if not overflow_ok:
        raise AssertionError(f"{name}: horizontal overflow")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("."))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            for name, viewport in VIEWPORTS.items():
                context = browser.new_context(viewport=viewport, locale="es-CR",
                                              is_mobile=(name == "mobile"), has_touch=(name == "mobile"))
                page = context.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                for line in run_flow(page, args.out, name):
                    print(f"[{name}] {line}")
                if errors:
                    raise AssertionError(f"{name}: JavaScript errors {errors}")
                print(f"[{name}] no JavaScript errors")
                context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    print("UI_SMOKE=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
