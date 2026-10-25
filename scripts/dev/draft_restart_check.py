"""T030 live check: real uvicorn on mentor_pro_test (port 8010); outage, retry, restart recovery.

Usage: .venv/Scripts/python.exe scripts/dev/draft_restart_check.py <screenshot folder>
"""
import os, subprocess, sys, time, urllib.request
from pathlib import Path
REPO = str(Path(__file__).resolve().parents[2])
sys.path.insert(0, REPO)
from curriculum import db
from playwright.sync_api import sync_playwright, expect
import psycopg
url = db.require_test_database(db.test_database_url())
env = {**os.environ, "DATABASE_URL": url, "MENTOR_PRO_TUTOR_TOKEN": ""}
BASE = "http://127.0.0.1:8010/"
SHOTS = sys.argv[1]  # usage: draft_restart_check.py <screenshot folder>; uses mentor_pro_test only

def start():
    proc = subprocess.Popen([rf"{REPO}\.venv\Scripts\python.exe", "-m", "uvicorn", "app.main:app", "--port", "8010"],
                            cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE, timeout=1); return proc
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server did not start")

def stored(eid):
    with psycopg.connect(url) as c:
        r = c.execute("SELECT text_es FROM writing.draft WHERE exercise_id=%s", (eid,)).fetchone()
    return r[0] if r else None

with psycopg.connect(url) as c:
    eid = c.execute("SELECT exercise_id FROM writing.exercise e WHERE level='paragraph_writing' AND NOT EXISTS "
                    "(SELECT 1 FROM writing.submission s WHERE s.exercise_id=e.exercise_id) ORDER BY 1 LIMIT 1").fetchone()[0]
results = []
def check(ok, msg): results.append(ok); print("PASS" if ok else "FAIL", msg)

server = start()
with sync_playwright() as p:
    page = p.chromium.launch(channel="chrome", headless=True).new_page(viewport={"width": 1280, "height": 900}, locale="es-CR")
    page.on("dialog", lambda d: d.accept())
    page.goto(BASE); page.evaluate("sessionStorage.clear()"); page.goto(BASE)
    page.get_by_role("button", name="Abrir Producción escrita").click()
    page.locator('.level-choice[data-level="paragraph_writing"]').click()
    page.locator(f'.exercise-choice[data-exercise="{eid}"]').click()
    page.locator("#writing-text").fill("Primer párrafo guardado antes del corte.")
    expect(page.locator("#writing-saved")).to_contain_text("Guardado", timeout=6000)
    check(stored(eid) == "Primer párrafo guardado antes del corte.", "autosave reached PostgreSQL")
    server.terminate(); server.wait()
    page.locator("#writing-text").fill("Texto escrito con el servidor apagado.")
    page.get_by_role("button", name="Guardar borrador").click()
    expect(page.locator("#writing-saved")).to_contain_text("No se pudo guardar")
    check(page.locator("#writing-text").input_value() == "Texto escrito con el servidor apagado."
          and page.locator("#writing-retry").is_visible()
          and stored(eid) == "Primer párrafo guardado antes del corte.",
          "server down: «No se pudo guardar», text kept, earlier draft intact, retry offered")
    page.screenshot(path=SHOTS + r"\live-server-down.png", full_page=True)
    server = start()
    page.get_by_role("button", name="Reintentar").click()
    expect(page.locator("#writing-saved")).to_contain_text("Guardado")
    check(stored(eid) == "Texto escrito con el servidor apagado.", "after restart: retry saves the text")
    server.terminate(); server.wait(); server = start()
    page.reload()
    expect(page.locator("#writing-editor")).to_be_visible()
    check(page.locator("#writing-text").input_value() == "Texto escrito con el servidor apagado.",
          "after another restart: reload restores the latest saved draft")
    page.screenshot(path=SHOTS + r"\live-restored.png", full_page=True)
server.terminate(); server.wait()
print("LIVE", "pass" if all(results) else "fail", f"({sum(results)}/{len(results)})")
