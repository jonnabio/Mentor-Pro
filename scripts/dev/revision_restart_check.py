"""T038 live check: the full revision cycle across real process restarts, on mentor_pro_test only.

Student app (app.main, port 8010) and tutor service (app.tutor_main, port 8011, loopback, test token) run as
separate uvicorn processes. Write -> tutor review -> revise (draft survives a restart) -> resubmit -> tutor
re-evaluation -> both reviews still shown after another restart. Writes only the isolated test database.

Usage: .venv/Scripts/python.exe scripts/dev/revision_restart_check.py <screenshot folder>
"""
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import psycopg  # noqa: E402
from playwright.sync_api import expect, sync_playwright  # noqa: E402

from app.writing.store import WritingStore  # noqa: E402
from curriculum import db  # noqa: E402

url = db.require_test_database(db.test_database_url())
TOKEN = "live-" + secrets.token_hex(20)  # this run only; never printed
STUDENT, TUTOR = "http://127.0.0.1:8010", "http://127.0.0.1:8011"
PYTHON = str(REPO / ".venv" / "Scripts" / "python.exe")
SHOTS = sys.argv[1]
FIXTURE = REPO / "scripts" / "dev" / "fixtures" / "writing-exercises-L2L3-T025.json"
L2 = next(r for r in json.loads(FIXTURE.read_text(encoding="utf-8")) if r["exercise_type"] == "introduction_paragraph")
EID = L2["exercise_id"]
results = []


def check(ok, msg):
    results.append(bool(ok))
    print("PASS" if ok else "FAIL", msg, flush=True)


def call(base, path, method="GET", body=None, tutor=False):
    request = urllib.request.Request(base + path, method=method, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              **({"X-Tutor-Token": TOKEN} if tutor else {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def start():
    env = {**os.environ, "DATABASE_URL": url, "MENTOR_PRO_TUTOR_TOKEN": ""}
    student = subprocess.Popen([PYTHON, "-m", "uvicorn", "app.main:app", "--port", "8010"], cwd=REPO, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    tutor_env = {**env, "MENTOR_PRO_TUTOR_TOKEN": TOKEN, "MENTOR_PRO_TUTOR_ALLOWED_HOSTS": "127.0.0.1"}
    tutor = subprocess.Popen([PYTHON, "-c", "import uvicorn; from app.tutor_main import create_tutor_app; "
                              "uvicorn.run(create_tutor_app(), host='127.0.0.1', port=8011, proxy_headers=False)"],
                             cwd=REPO, env=tutor_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for base in (STUDENT, TUTOR + "/tutor"):
        for _ in range(150):
            try:
                urllib.request.urlopen(base, timeout=1)
                break
            except urllib.error.HTTPError:
                break  # answering
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError(f"{base} did not start")
    return [student, tutor]


def stop(procs):
    for proc in procs:
        proc.terminate()
        proc.wait()


def complete(submission_id, points, text):
    scores = {c: points for c in L2["target_criteria"]}
    return call(TUTOR, f"/api/tutor/submissions/{submission_id}/evaluation", "PUT",
                {"scores": scores, "complete": True, "strengths": [text]}, tutor=True)


with psycopg.connect(url, autocommit=True) as conn:
    conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
WritingStore(url).add_exercise(L2)

procs = start()
call(STUDENT, f"/api/writing/exercises/{EID}/submit", "POST",
     {"text": "Mi primer párrafo.", "client_request_id": str(uuid.uuid4())})
first_sid = call(TUTOR, "/api/tutor/queue", tutor=True)[1]["submissions"][0]["submission_id"]
check(complete(first_sid, 2, "Primera revisión.")[0] == 200, "tutor service completes the first review")
status, attempt = call(STUDENT, f"/api/writing/exercises/{EID}/revision", "POST")
check(status == 201, "student starts «Mejorar mi respuesta»")
call(STUDENT, f"/api/writing/attempts/{attempt['attempt_id']}/draft", "PUT",
     {"text": "Mi párrafo mejorado antes del reinicio.", "client_seq": 1})

stop(procs)
procs = start()
draft = call(STUDENT, f"/api/writing/exercises/{EID}")[1]["revision_attempt"]["attempt"]["draft"]
check(draft["text"] == "Mi párrafo mejorado antes del reinicio." and draft["client_seq"] == 1,
      "after restart: the revision draft and its client_seq are intact")
status, _ = call(STUDENT, f"/api/writing/attempts/{attempt['attempt_id']}/submit", "POST",
                 {"text": "Mi párrafo mejorado.", "client_request_id": str(uuid.uuid4())})
check(status == 200, "student resubmits the improved version")

stop(procs)
procs = start()
queue = call(TUTOR, "/api/tutor/queue", tutor=True)[1]["submissions"]
revision_sid = next(s["submission_id"] for s in queue if s["attempt_number"] == 2)
detail = call(TUTOR, f"/api/tutor/submissions/{revision_sid}", tutor=True)[1]
check(detail["attempt_number"] == 2 and detail["previous"]["student_text"] == "Mi primer párrafo."
      and detail["previous"]["evaluation"]["status"] == "completed",
      "after restart: tutor sees the improvement with the first response and its review")
check(call(TUTOR, f"/api/tutor/submissions/{revision_sid}")[0] == 403, "tutor service still requires the token")
check(complete(revision_sid, 3, "Segunda revisión.")[0] == 200, "tutor completes the re-evaluation")

stop(procs)
procs = start()
check(complete(first_sid, 4, "Cambio.")[0] == 409, "after restart: the first review stays locked")
data = call(STUDENT, f"/api/writing/exercises/{EID}")[1]
check([s["points"] for s in data["feedback"]["scores"]] == [2] * len(L2["target_criteria"])
      and [s["points"] for s in data["revision_attempt"]["attempt"]["feedback"]["scores"]]
      == [3] * len(L2["target_criteria"]),
      "after restart: student API returns both reviews unchanged")
with sync_playwright() as p:
    page = p.chromium.launch(channel="chrome", headless=True).new_page(viewport={"width": 1280, "height": 900},
                                                                      locale="es-CR")
    page.goto(STUDENT)
    page.evaluate(f"sessionStorage.setItem('mentorpro.writing', '{EID}')")
    page.reload()
    expect(page.locator("#writing-revision-feedback")).to_be_visible()
    check("Segunda revisión." in page.locator("#writing-revision-feedback").inner_text()
          and "Primera revisión." in page.locator("#writing-feedback").inner_text()
          and TOKEN not in page.content(),
          "after restart: the student page shows both reviews; no tutor code")
    page.screenshot(path=SHOTS + r"\live-revision-reviewed.png", full_page=True)
stop(procs)
print("LIVE", "pass" if all(results) else "fail", f"({sum(results)}/{len(results)})")
sys.exit(0 if all(results) else 1)
