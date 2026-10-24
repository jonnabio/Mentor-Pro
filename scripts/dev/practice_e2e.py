"""Browser end-to-end test of the student practice (T010) with Playwright and installed Chrome.

Mock mode (default) replaces only the set generator with a scripted runner, so the
real API, PostgreSQL sessions, server-side evaluation and UI are exercised for all
four subjects and the failure paths without OpenRouter calls. Live mode runs the
Matemáticas acceptance practice with the real validated generator.

Both modes use only TEST_DATABASE_URL (ADR-016): the run refuses to start, without
connecting, unless that database ends in "_test" and is not the student database.
The baseline catalog is imported there if missing; mock mode seeds labelled
synthetic bank items (`e2e-bank-…`).

Usage:
    .venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR            # mocked scenarios
    .venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR --live     # live acceptance
"""

from __future__ import annotations

import argparse
import hashlib
import psycopg
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from playwright.sync_api import Page, expect, sync_playwright
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.generation.practice_set import PracticeSetResult, SlotResult  # noqa: E402
from app.generation.store import GenerationStore  # noqa: E402
from app.generation.validation import CHECKER_VERSION  # noqa: E402
from app.main import BASELINE_VERSION, create_app  # noqa: E402
from app.practice.bank import QuestionBank  # noqa: E402
from app.practice.mastery import RECOMMENDATIONS_ES  # noqa: E402
from app.writing.store import WritingStore  # noqa: E402
from curriculum import db, importer  # noqa: E402
from curriculum.catalog import list_objectives  # noqa: E402

PORT = 8766
BASE = f"http://127.0.0.1:{PORT}/"
DESKTOP = {"width": 1280, "height": 900}
MOBILE = {"width": 390, "height": 844}
KEYS = "BCDAB"
# Mocked-generator scenarios use objectives and a difficulty ("Difícil") with no bank inventory, so the
# scripted runner, not the real question bank, supplies their questions.
SUBJECTS = {  # label, objective codes
    "matematicas": ("Matemáticas", ["M10", "M11", "M12"]),
    "espanol": ("Español", ["EL01", "EL02"]),
    "ciencias": ("Ciencias", ["C01", "C02"]),
    "estudios_sociales": ("Estudios Sociales", ["ES01", "ES02"]),
}


BANK_OBJECTIVES = ("M02", "M04", "M05")  # scenario_bank_only, "Intermedia"
WORDS = ("río", "mesa", "nube", "faro", "trigo", "lápiz", "volcán", "puente", "cacao", "brújula", "ciprés",
         "tambor", "arena", "colmena", "linterna", "marea", "piedra", "sendero", "tucán", "vasija", "yuca",
         "zafiro", "bosque", "carreta", "delfín", "espiga", "flauta", "girasol", "hamaca", "iglesia")


WRITING_FIXTURES = (db.REPO_ROOT / "scripts" / "dev" / "fixtures" / "writing-exercise-T021.json",
                    db.REPO_ROOT / "scripts" / "dev" / "fixtures" / "writing-exercises-L1-T023.json",
                    db.REPO_ROOT / ".ace" / "schemas" / "writing" / "examples" / "exercises.json")
HEALTHY = "PE-L2-alimentacion-saludable-rendimiento-19a72a"  # generated in T021
L1_TITLES = ["El fútbol en mi comunidad", "Corrección de texto expositivo: El manglar de Térraba",
             "Corrección de un texto expositivo: La feria de la ciencia"]  # generated in T023
REFERENCE_TUTOR_ID = "PE-L1-futbol-comunidad-f136a4"
REFERENCE_SECRET = "Los entrenadores voluntarios enseñan"  # test-only tutor reference text (seeded below)
WRITING_TEXT = ("La alimentación saludable es muy importante para los estudiantes. Cuando comemos frutas, verduras "
                "y granos tenemos más energía para aprender. Además, una buena alimentación ayuda a concentrarse en "
                "clase y a convivir mejor con los compañeros.")


def prepare_writing(url: str) -> None:
    """Reset the test database's writing schema and load the T021 exercise and the T020 examples (ADR-016)."""
    with psycopg.connect(db.require_test_database(url), autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    store = WritingStore(url)
    for path in WRITING_FIXTURES:
        data = json.loads(path.read_text(encoding="utf-8"))
        for exercise in data if isinstance(data, list) else [data]:
            reference = None
            if exercise["exercise_id"] == REFERENCE_TUTOR_ID:  # a tutor-only reference that must never be shown
                reference = {"corrected_text_es": f"{REFERENCE_SECRET} técnicas básicas.", "corrections": [],
                             "ambiguities_es": []}
            store.add_exercise(exercise, reference=reference)


def test_database() -> str:
    """TEST_DATABASE_URL after the safety gate; DATABASE_URL is redirected to it for this process."""
    url = db.require_test_database(db.test_database_url())
    os.environ["DATABASE_URL"] = url
    return url


def prepare_database(url: str, seed_bank: bool) -> None:
    """Import the baseline catalog if missing; optionally seed synthetic bank items for the mock run."""
    manifest = importer.DEFAULT_MANIFEST
    registered = {line.split()[0] for line in manifest.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")}
    workbooks = [w for w in sorted((db.REPO_ROOT / "references" / "original").glob("[!~]*.xlsx"))
                 if hashlib.sha256(w.read_bytes()).hexdigest() in registered]
    if not workbooks:
        raise SystemExit("baseline workbook not found in references/original (see references/MANIFEST.sha256)")
    importer.import_workbook(workbooks[0], url, BASELINE_VERSION, manifest)
    if not seed_bank:  # live mode: only real validated questions may be served from the test bank
        GenerationStore(url), QuestionBank(url)  # create the generation tables if missing
        with db.connect(url) as conn:
            conn.execute("DELETE FROM generation.bank_revalidation WHERE request_id LIKE 'e2e-bank-%'")
            conn.execute("DELETE FROM generation.question_attempt WHERE request_id LIKE 'e2e-bank-%'")
            conn.commit()
        return
    with db.connect(url, read_only=True) as catalog:
        evidences = [(o["workbook_code"], e["id"])
                     for o in list_objectives(catalog, BASELINE_VERSION, "matematicas")
                     if o["workbook_code"] in BANK_OBJECTIVES for e in o["evidences"]]
    GenerationStore(url)  # creates the generation schema
    with db.connect(url) as conn:
        for index, (code, evidence_id) in enumerate(evidences):
            words = [WORDS[(index * 7 + k) % len(WORDS)] for k in range(5)]
            item = {
                "item_id": f"Q-e2e-bank-{index:02d}", "subject": "matematicas",
                "stimulus": {"type": "text", "text": f"Banco de prueba {index}: {' '.join(words)}."},
                "stem": f"¿Qué palabra aparece primero en la lista {' '.join(words[:3])} número {index}?",
                "options": [{"label": lbl, "text": f"{words[k]} {index}"} for k, lbl in enumerate("ABCD")],
                "answer_key": "A",
                "explanation": f"EXPLICACION-OCULTA-banco-{index}: la primera palabra es {words[0]}.",
                "source_refs": [{"record_id": evidence_id, "excerpt": f"Evidencia {evidence_id}"}],
            }
            conn.execute(
                """INSERT INTO generation.question_attempt (request_id, baseline_version, objective_code,
                       evidence_id, difficulty, status, verdict, item_id, models_used, calls, tokens_in, tokens_out,
                       cost_usd, cost_complete, checker_version, prompt_version, validation, item, reasons)
                   VALUES (%s, %s, %s, %s, 'medium', 'accepted', 'accept', %s, %s, 0, 0, 0, 0, true, %s, 'e2e-seed',
                           %s, %s, %s) ON CONFLICT (request_id) DO NOTHING""",
                (f"e2e-bank-{index:02d}", BASELINE_VERSION, code, evidence_id, item["item_id"], ["e2e-seed"],
                 CHECKER_VERSION, Jsonb({"verdict": "accept", "checker_version": CHECKER_VERSION}), Jsonb(item),
                 Jsonb([])))
        conn.commit()


class ScriptedRunner:
    """Scenario-controlled stand-in for generate_set: ok | slow | llm_down | budget."""

    def __init__(self):
        self.mode, self.delay, self.calls = "ok", 0.2, 0

    def __call__(self, session, on_slot_done):
        self.calls += 1
        slots = [SlotResult(s["slot"], row["workbook_code"], s["evidence_id"], s["evidence_ordinal"], s["difficulty"])
                 for row in session["allocation"] for s in row["slots"]]
        accepted = {"ok": 5, "slow": 5, "llm_down": 0, "budget": 2}[self.mode]
        for index, slot in enumerate(slots):
            time.sleep(self.delay)
            if index < accepted:
                slot.status, slot.request_id = "accepted", f"req-mock-{index}"
                slot.item = {
                    "item_id": f"Q-mock-{uuid.uuid4().hex[:8]}",
                    "stimulus": {"type": "text", "text": f"Situación simulada {slot.slot} para {slot.objective_code}."},
                    "stem": f"¿Cuál opción es correcta en la pregunta simulada {slot.slot}?",
                    "options": [{"label": lbl, "text": f"Respuesta {lbl} de la pregunta {slot.slot}"} for lbl in "ABCD"],
                    "answer_key": KEYS[index],
                    "explanation": f"EXPLICACION-OCULTA-{slot.slot}: la opción {KEYS[index]} es la correcta.",
                    "source_refs": [{"record_id": slot.evidence_id, "excerpt": f"Evidencia {slot.evidence_id}"}],
                }
            else:
                slot.status = "failed"
            on_slot_done(slot)
        stop = {"llm_down": "llm_unavailable", "budget": "daily_budget"}.get(self.mode)
        return PracticeSetResult(f"set-mock-{uuid.uuid4().hex[:8]}", session["subject"],
                                 "partial" if stop else "complete", stop, slots, [], 1)


class Report:
    def __init__(self):
        self.lines: list[str] = []
        self.failures: list[str] = []

    def check(self, condition: bool, text: str) -> None:
        self.lines.append(f"{'PASS' if condition else 'FAIL'} {text}")
        print(self.lines[-1], flush=True)
        if not condition:
            self.failures.append(text)


def no_overflow(page: Page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def configure(page: Page, subject: str, codes: list[str], difficulty: str = "Difícil") -> None:
    """Mocked-generator scenarios use "Difícil", where the real bank has no inventory."""
    page.goto(BASE)
    page.locator(f'input[name="subject"][value="{subject}"]').check()
    page.get_by_label("Varios objetivos").check()
    for code in codes:
        page.locator(f'input[name="objective"][value="{code}"]').check()
    page.get_by_label(difficulty).check()
    page.get_by_label("5", exact=True).check()


def watch_disclosure(page: Page, leaks: list[str]) -> None:
    """Record any session GET response that reveals a key or explanation of an unanswered question."""
    def on_response(response):
        if "/api/practice/sessions/" in response.url and response.request.method == "GET":
            try:
                body = response.json()
            except Exception:  # noqa: BLE001
                return
            for q in body.get("questions", []):
                if not q.get("answered") and ({"correct_label", "explanation", "answer_key"} & set(q)):
                    leaks.append(f"slot {q['slot']}")
            if "answer_key" in json.dumps(body):
                leaks.append("answer_key field")
    page.on("response", on_response)


def answer_all(page: Page, report: Report, name: str, labels: list[str], known_keys: str | None,
               shots: Path | None = None) -> dict:
    counts = {"correct": 0, "incorrect": 0}
    for index, label in enumerate(labels):
        expect(page.locator("#quiz-position")).to_contain_text(f"Pregunta {index + 1} de")
        hidden_before = "EXPLICACION-OCULTA" not in page.locator("body").inner_text()
        if index == 0:
            report.check(hidden_before, f"[{name}] explanation not in the page before answering")
            if shots:
                page.screenshot(path=str(shots / f"{name}-question.png"), full_page=True)
        page.locator(f'.option[data-label="{label}"]').click()
        page.get_by_role("button", name="Responder").click()
        expect(page.locator("#feedback")).to_be_visible()
        result = page.locator("#feedback-result").inner_text()
        is_correct = result.startswith("¡Correcto")
        counts["correct" if is_correct else "incorrect"] += 1
        if known_keys:
            report.check(is_correct == (label == known_keys[index]),
                         f"[{name}] Q{index + 1} answered {label}: shown '{result}'")
        if index == 0 and shots:
            page.screenshot(path=str(shots / f"{name}-feedback.png"), full_page=True)
        page.locator("#next").click()
    expect(page.locator("#result-view")).to_be_visible()
    return counts


def scenario_subject(page: Page, runner: ScriptedRunner, report: Report, subject: str, viewport: str,
                     shots: Path) -> None:
    runner.mode, runner.delay = "ok", 0.2
    leaks: list[str] = []
    watch_disclosure(page, leaks)
    configure(page, subject, SUBJECTS[subject][1])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#progress-view")).to_be_visible()
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    labels = ["A", "C", "D", "A", "B"]  # Q1 wrong, the rest right (keys BCDAB)
    counts = answer_all(page, report, f"{viewport}-{subject}", labels, KEYS, shots)
    report.check(counts == {"correct": 4, "incorrect": 1}, f"[{viewport}-{subject}] 4 correct, 1 incorrect")
    report.check(page.locator("#result-correct").inner_text() == "4"
                 and page.locator("#result-incorrect").inner_text() == "1"
                 and page.locator("#result-percentage").inner_text() == "80 %",
                 f"[{viewport}-{subject}] summary 4 / 1 / 80 %")
    codes = page.locator("#result-objectives > li > .code").all_inner_texts()
    report.check(sorted(codes) == sorted(SUBJECTS[subject][1]),
                 f"[{viewport}-{subject}] practiced objectives listed: {codes}")
    report.check(not leaks, f"[{viewport}-{subject}] no key or explanation before submission ({leaks})")
    report.check(no_overflow(page), f"[{viewport}-{subject}] no horizontal overflow")
    page.screenshot(path=str(shots / f"{viewport}-{subject}-result.png"), full_page=True)
    # Alternate the two exits from the results screen across subjects (T012).
    action = "menu" if subject in ("matematicas", "ciencias") else "new"
    leave_practice(page, runner, report, f"{viewport}-{subject}", action, subject)


def leave_practice(page: Page, runner: ScriptedRunner, report: Report, name: str, action: str,
                   subject: str | None) -> None:
    """Leave a finished or failed practice; check the form state, no new job and the stored result."""
    session_id = page.evaluate("sessionStorage.getItem('mentorpro.session')")
    calls = runner.calls
    label = "Volver al menú principal" if action == "menu" else "Nueva práctica"
    page.get_by_role("button", name=label).click()
    expect(page.locator("#practice-form")).to_be_visible()
    page.wait_for_timeout(300)
    checked = page.evaluate("document.querySelector('input[name=\"subject\"]:checked')?.value || null")
    if action == "menu":
        # Playwright's is_disabled() ignores <fieldset disabled>, so read the DOM property.
        ok = (checked is None and page.evaluate("document.getElementById('objectives-card').disabled")
              and page.locator('input[name="objective"]').count() == 0)
        report.check(ok, f"[{name}] 'Volver al menú principal' shows the initial selection screen")
    else:
        report.check(checked == subject, f"[{name}] 'Nueva práctica' keeps the previous subject ({checked})")
    report.check(page.locator("#submit").inner_text() == "Generar práctica",
                 f"[{name}] generate button ready on the form")
    report.check(runner.calls == calls, f"[{name}] no generation job started by navigation")
    report.check(page.evaluate("sessionStorage.getItem('mentorpro.session')") is None,
                 f"[{name}] stored session cleared (reload does not resume it)")
    if session_id:
        stored = page.evaluate("async (sid) => (await fetch(`/api/practice/sessions/${sid}`)).json()", session_id)
        kept = stored.get("summary") is not None if stored["status"] != "failed" else stored["status"] == "failed"
        report.check(kept, f"[{name}] practice still stored in PostgreSQL ({stored['status']})")
    report.check(no_overflow(page), f"[{name}] no horizontal overflow after navigation")


def scenario_duplicate_clicks(page: Page, runner: ScriptedRunner, report: Report) -> None:
    runner.mode, runner.delay = "ok", 0.3
    before = runner.calls
    configure(page, "matematicas", ["M10", "M12"])
    # Five clicks in the same tick, then a "second tab" posting the same configuration with its own request id.
    page.evaluate("""() => { const b = document.getElementById('submit');
                             for (let i = 0; i < 5; i++) b.click(); }""")
    expect(page.locator("#progress-view")).to_be_visible()
    page.wait_for_function("sessionStorage.getItem('mentorpro.session') !== null")  # first POST answered
    other = page.evaluate("""async () => (await fetch('/api/practice/sessions', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({subject: 'matematicas', scope: 'selected_objectives', objective_codes: ['M12', 'M10'],
                              difficulty: 'hard', question_count: 5, client_request_id: crypto.randomUUID()})
        })).json()""")
    own = page.evaluate("sessionStorage.getItem('mentorpro.session')")
    report.check(other["session_id"] == own and other["created"] is False,
                 "[dup] second tab with the same configuration reuses the running session")
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    report.check(runner.calls - before == 1, f"[dup] 5 clicks + second tab started {runner.calls - before} job(s)")


def scenario_refresh_and_resubmit(page: Page, runner: ScriptedRunner, report: Report, shots: Path) -> None:
    runner.mode, runner.delay = "slow", 1.2
    before = runner.calls
    configure(page, "ciencias", ["C01", "C02"])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#progress-count")).to_contain_text("de 5")
    report.check(page.locator("#progress-actions").is_hidden(),
                 "[refresh] leave-practice buttons hidden while generation runs")
    page.screenshot(path=str(shots / "progress.png"), full_page=True)
    page.reload()
    expect(page.locator("#progress-view")).to_be_visible()
    report.check(True, "[refresh] progress view restored after reload during generation")
    expect(page.locator("#quiz-view")).to_be_visible(timeout=30000)
    report.check(runner.calls - before == 1, "[refresh] reload did not start a second job")

    page.locator('.option[data-label="A"]').click()
    page.get_by_role("button", name="Responder").click()
    expect(page.locator("#feedback")).to_be_visible()
    session_id = page.evaluate("sessionStorage.getItem('mentorpro.session')")
    again = page.evaluate("""async (sid) => (await fetch(`/api/practice/sessions/${sid}/answers`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({slot: 1, label: 'B'})})).json()""", session_id)
    report.check(again["already_answered"] and again["chosen_label"] == "A" and not again["correct"],
                 "[resubmit] second answer to Q1 ignored; first (A, incorrect) kept")
    report.check(page.locator("#answer-submit").is_hidden(), "[resubmit] answer button hidden after answering")
    page.reload()
    expect(page.locator("#quiz-view")).to_be_visible()
    report.check(page.locator("#quiz-position").inner_text().startswith("Pregunta 2"),
                 "[resubmit] reload resumes at the first unanswered question")
    page.evaluate("sessionStorage.clear()")


def scenario_failures(page: Page, runner: ScriptedRunner, report: Report, shots: Path) -> None:
    runner.mode, runner.delay = "llm_down", 0.1
    configure(page, "estudios_sociales", ["ES01", "ES02"])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#progress-error")).to_be_visible(timeout=20000)
    text = page.locator("#progress-error").inner_text()
    report.check("no respondió" in text and "ninguna pregunta" in text, f"[llm-down] failure shown: '{text}'")
    report.check(page.locator("#progress-title").inner_text() == "No se pudo preparar la práctica"
                 and page.locator(".progress").is_hidden() and page.locator("#progress-hint").is_hidden(),
                 "[llm-down] failed state has its own title and no progress bar or wait hint")
    page.screenshot(path=str(shots / "failure-llm.png"), full_page=True)
    leave_practice(page, runner, report, "llm-down", "menu", None)

    runner.mode = "budget"
    configure(page, "espanol", ["EL01", "EL02"])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    notice = page.locator("#quiz-notice").inner_text()
    report.check("límite diario" in notice and "2 de 5" in notice, f"[budget] partial notice: '{notice}'")
    report.check(page.locator("#quiz-position").inner_text() == "Pregunta 1 de 2", "[budget] 2 questions to practise")
    page.screenshot(path=str(shots / "partial-budget.png"), full_page=True)
    answer_all(page, report, "budget", ["B", "B"], KEYS[:2])
    report.check(page.locator("#result-percentage").inner_text() == "50 %", "[budget] summary 50 %")
    leave_practice(page, runner, report, "budget", "new", "espanol")
    page.evaluate("sessionStorage.clear()")


def math_answers(page: Page) -> int:
    data = page.evaluate("async () => (await fetch('/api/dashboard')).json()")
    return next(x for x in data["subjects"] if x["subject"] == "matematicas")["total_answers"]


def exit_practice(page: Page, runner: ScriptedRunner, report: Report, name: str, out: Path | None) -> dict:
    """Leave the active practice through the confirmation dialog; returns the stored session."""
    sid = page.evaluate("sessionStorage.getItem('mentorpro.session')")
    calls = runner.calls
    page.get_by_role("button", name="Salir de la práctica").click()
    dialog = page.locator("#exit-dialog")
    expect(dialog).to_be_visible()
    report.check(page.locator("#exit-title").inner_text() == "¿Querés salir de la práctica?"
                 and "se conservarán" in page.locator("#exit-message").inner_text(),
                 f"[{name}] confirmation dialog in Spanish")
    if out:
        page.screenshot(path=str(out / f"{name}-exit-dialog.png"), full_page=True)
    page.get_by_role("button", name="Salir al menú principal").click()
    expect(page.locator("#practice-form")).to_be_visible()
    stored = page.evaluate("async (sid) => (await fetch(`/api/practice/sessions/${sid}`)).json()", sid)
    report.check(stored["cancelled"] is True, f"[{name}] practice marked cancelled (status {stored['status']})")
    report.check(page.evaluate("sessionStorage.getItem('mentorpro.session')") is None
                 and page.evaluate("document.querySelector('input[name=\"subject\"]:checked')") is None,
                 f"[{name}] back on the initial screen, active practice cleared")
    report.check(runner.calls == calls, f"[{name}] no generation job started")
    page.reload()
    expect(page.locator("#practice-form")).to_be_visible()
    page.wait_for_timeout(300)
    report.check(page.locator("#quiz-view").is_hidden(), f"[{name}] reload does not resume the cancelled practice")
    report.check(no_overflow(page), f"[{name}] no horizontal overflow")
    return stored


def scenario_exit(page: Page, runner: ScriptedRunner, report: Report, viewport: str, out: Path) -> None:
    runner.mode, runner.delay = "ok", 0.05
    before = math_answers(page)
    configure(page, "matematicas", ["M10", "M11"])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    for label in ("A", "C"):  # Q1 wrong, Q2 right (keys BCDAB)
        page.locator(f'.option[data-label="{label}"]').click()
        page.get_by_role("button", name="Responder").click()
        page.locator("#next").click()
    page.get_by_role("button", name="Salir de la práctica").click()
    expect(page.locator("#exit-dialog")).to_be_visible()
    page.get_by_role("button", name="Seguir practicando").click()
    report.check(page.locator("#exit-dialog").is_hidden()
                 and page.locator("#quiz-position").inner_text() == "Pregunta 3 de 5",
                 f"[{viewport}-exit] 'Seguir practicando' closes the dialog and stays on question 3")
    stored = exit_practice(page, runner, report, f"{viewport}-exit-after-2", out)
    report.check([q["answered"] for q in stored["questions"]] == [True, True, False, False, False],
                 f"[{viewport}-exit-after-2] two answers kept, three left unanswered")
    report.check(math_answers(page) == before + 2,
                 f"[{viewport}-exit-after-2] dashboard counts only the 2 submitted answers")

    configure(page, "matematicas", ["M10", "M12"])
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    stored = exit_practice(page, runner, report, f"{viewport}-exit-before-answer", None)
    report.check(not any(q["answered"] for q in stored["questions"]), f"[{viewport}-exit-before-answer] no answers")

    if viewport == "desktop":
        runner.mode = "budget"
        configure(page, "matematicas", ["M11", "M12"])
        page.get_by_role("button", name="Generar práctica").click()
        expect(page.locator("#quiz-notice")).to_be_visible(timeout=20000)
        page.locator('.option[data-label="B"]').click()
        page.get_by_role("button", name="Responder").click()
        expect(page.locator("#feedback")).to_be_visible()  # the answer is stored before leaving (T019 race fix)
        stored = exit_practice(page, runner, report, "desktop-exit-partial", None)
        report.check(stored["status"] == "partial" and [q["answered"] for q in stored["questions"]] == [True, False],
                     f"[desktop-exit-partial] partial practice cancelled; 1 of 2 answered ({stored['status']}, "
                     f"{[q['answered'] for q in stored['questions']]})")
        runner.mode = "ok"


def scenario_dashboard_before_subjects_load(page: Page, report: Report) -> None:
    """T018 regression: "Ver mi progreso" clicked before /api/subjects answers must still open the dashboard."""
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    def slow(route):
        time.sleep(1.0)
        route.continue_()

    page.route("**/api/subjects", slow)
    page.goto(BASE, wait_until="domcontentloaded")
    loaded = page.evaluate("document.querySelectorAll('input[name=\"subject\"]').length")
    page.get_by_role("button", name="Ver mi progreso").click()
    expect(page.locator("#dashboard-view")).to_be_visible()
    page.unroute("**/api/subjects")
    report.check(loaded == 0 and not errors, f"[dashboard-early] opens before subjects load ({loaded} loaded, "
                                             f"errors {errors})")
    page.get_by_role("button", name="Volver al menú principal").click()
    expect(page.locator("#practice-form")).to_be_visible()


SIX = {"M01": "unpracticed", "M02": "insufficient_evidence", "M03": "needs_reinforcement", "M04": "in_progress",
       "M05": "good_proficiency", "M06": "consolidated_mastery"}


def form_state(page: Page) -> dict:
    return page.evaluate("""() => ({
        subject: document.querySelector('input[name="subject"]:checked')?.value,
        scope: document.querySelector('input[name="scope"]:checked')?.value,
        objectives: [...document.querySelectorAll('input[name="objective"]:checked')].map(i => i.value),
        difficulty: document.querySelector('input[name="difficulty"]:checked')?.value,
        count: document.querySelector('input[name="question_count"]:checked')?.value,
        submit: !document.getElementById('submit').disabled,
        notice: document.getElementById('dashboard-choice').hidden ? '' :
                document.getElementById('dashboard-choice').textContent})""")


def scenario_dashboard_practice(page: Page, runner: ScriptedRunner, report: Report, viewport: str, out: Path) -> None:
    """T019: every status offers an action that only fills the form; the practice starts on explicit confirmation."""
    name = f"{viewport}-dash-practice"
    posts: list[str] = []
    page.on("request", lambda r: r.method == "POST" and "/api/practice/sessions" in r.url and posts.append(r.url))

    def six_statuses(route):  # assign one status to each of six objectives to exercise every label
        data = route.fetch().json()
        labels = {s["code"]: s["label_es"] for s in data["statuses"]}
        for subject in data["subjects"]:
            for objective in subject["objectives"]:
                if objective["code"] in SIX:
                    objective["status"] = SIX[objective["code"]]
                    objective["status_es"] = labels[objective["status"]]
                    objective["recommendation_es"] = RECOMMENDATIONS_ES.get(objective["status"])
        route.fulfill(json=data)

    page.route("**/api/dashboard", six_statuses)
    calls = runner.calls
    for code, status in SIX.items():
        page.goto(BASE)
        page.get_by_role("button", name="Ver mi progreso").click()
        page.locator('input[name="dashboard-subject"][value="matematicas"]').check()
        item = page.locator(f'#dashboard-objectives li[data-code="{code}"]')
        expected = "Repasar este objetivo" if status == "consolidated_mastery" else "Practicar este objetivo"
        button = item.locator("button.dash-practice")
        report.check(button.inner_text() == expected, f"[{name}] {status}: action '{button.inner_text()}'")
        if status == "needs_reinforcement":
            report.check(item.locator(".priority-tag").inner_text().lower() == "prioridad"
                         and "Prioridad de repaso" in item.inner_text(), f"[{name}] needs_reinforcement highlighted")
        if status == "in_progress":
            report.check("Vas por buen camino" in item.inner_text(), f"[{name}] in_progress identified")
        if status == "consolidated_mastery":
            report.check("¡Excelente dominio!" in item.inner_text(), f"[{name}] maintenance recommendation shown")
        text = page.evaluate("(c) => document.querySelector(`#dashboard-objectives li[data-code='${c}'] "
                             ".objective-text`).textContent", code)
        button.click()
        expect(page.locator("#practice-form")).to_be_visible()
        expect(page.locator(f'input[name="objective"][value="{code}"]')).to_be_checked()
        state = form_state(page)
        label = page.locator(f'#obj-{code}').inner_text()
        report.check(state["subject"] == "matematicas" and state["scope"] == "single_objective"
                     and state["objectives"] == [code] and state["difficulty"] == "medium" and state["count"] == "5"
                     and state["submit"], f"[{name}] {status}: form preset {state}")
        report.check(text in label and code in state["notice"], f"[{name}] {code} keeps its code and text")
        report.check(no_overflow(page), f"[{name}] {code}: no horizontal overflow")
    page.unroute("**/api/dashboard")
    report.check(runner.calls == calls and not posts, f"[{name}] navigation started no job and sent no session")

    runner.mode, runner.delay = "ok", 0.05
    page.goto(BASE)
    page.get_by_role("button", name="Ver mi progreso").click()
    page.locator('input[name="dashboard-subject"][value="matematicas"]').check()
    before = {o["code"]: o["total_answers"] for o in page.evaluate(
        "async () => (await fetch('/api/dashboard')).json()")["subjects"][1]["objectives"]}
    page.locator('#dashboard-objectives li[data-code="M10"] button.dash-practice').click()
    expect(page.locator('input[name="objective"][value="M10"]')).to_be_checked()
    page.locator('input[name="difficulty"][value="hard"]').check()  # the student may adjust settings
    report.check(form_state(page)["difficulty"] == "hard" and runner.calls == calls, f"[{name}] difficulty adjustable")
    page.screenshot(path=str(out / f"{name}-form.png"), full_page=True)
    page.get_by_role("button", name="Generar práctica").click()
    expect(page.locator("#quiz-view")).to_be_visible(timeout=20000)
    report.check(runner.calls == calls + 1 and len(posts) == 1, f"[{name}] practice starts after confirmation")
    answer_all(page, report, name, ["B", "C", "D", "A", "B"], KEYS)
    page.get_by_role("button", name="Ver mi progreso").click()
    expect(page.locator("#dashboard-objectives li").first).to_be_visible()
    after = {o["code"]: o["total_answers"] for o in page.evaluate(
        "async () => (await fetch('/api/dashboard')).json()")["subjects"][1]["objectives"]}
    changed = {c: after[c] - before[c] for c in after if after[c] != before[c]}
    report.check(changed == {"M10": 5}, f"[{name}] results update only M10: {changed}")
    page.get_by_role("button", name="Volver al menú principal").click()
    expect(page.locator("#practice-form")).to_be_visible()
    report.check(page.locator("#dashboard-choice").is_hidden(), f"[{name}] notice cleared on the main menu")


def writing_rows(url: str, sql: str, *args) -> list[tuple]:
    with psycopg.connect(url) as conn:
        return conn.execute(sql, args or None).fetchall()


def scenario_writing(page: Page, report: Report, viewport: str, out: Path, url: str) -> None:
    """T022 acceptance: Producción escrita from the main menu to "Pendiente de revisión del tutor"."""
    name = f"{viewport}-writing"
    prepare_writing(url)
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(BASE)
    page.evaluate("sessionStorage.clear()")
    page.get_by_role("button", name="Abrir Producción escrita").click()
    expect(page.locator("#writing-levels .level-choice").first).to_be_visible()
    labels = page.locator("#writing-levels .level-label").all_inner_texts()
    report.check(labels == ["Nivel 1: Convenciones de escritura", "Nivel 2: Desarrollo de ideas",
                            "Nivel 3: Redacción de párrafos", "Nivel 4: Composición guiada",
                            "Nivel 5: Composición expositiva completa"], f"[{name}] five levels: {labels}")
    report.check(no_overflow(page), f"[{name}] levels: no horizontal overflow")
    page.screenshot(path=str(out / f"{name}-levels.png"), full_page=True)

    page.locator('.level-choice[data-level="writing_conventions"]').click()
    expect(page.locator(".exercise-choice").first).to_be_visible()
    titles = page.locator(".exercise-choice .level-label").all_inner_texts()
    report.check(titles == L1_TITLES, f"[{name}] Nivel 1 lists the three correction exercises {titles}")
    for index in range(3):
        page.locator(".exercise-choice").nth(index).click()
        expect(page.locator("#writing-source")).to_be_visible()
        source = page.locator("#writing-source-text").inner_text()
        panel = page.locator("#writing-exercise-panel").inner_text()
        html = page.content()
        state = page.evaluate("JSON.stringify(sessionStorage) + JSON.stringify(localStorage)")
        leaked = [w for w in (REFERENCE_SECRET, "EE0", "EE1", "El texto evidencia", "rúbrica", "corrected_text",
                              "corrections") if w in html or w in state]
        report.check(len(source.split()) >= 40 and "Corregí" in panel and "El texto completo, ya corregido" in panel
                     and not leaked, f"[{name}] L1 #{index + 1}: text to correct, instructions, no reference "
                                     f"or rubric ({leaked})")
        if index == 0:
            editor = page.locator("#writing-text")
            report.check(editor.get_attribute("spellcheck") == "false"
                         and page.locator("#writing-source").bounding_box()["y"] < editor.bounding_box()["y"],
                         f"[{name}] original text stays above the editor, spell check off")
            editor.fill(source.replace("las niños", "los niños"))
            page.get_by_role("button", name="Guardar borrador").click()
            expect(page.locator("#writing-saved")).to_contain_text("Borrador guardado")
            page.screenshot(path=str(out / f"{name}-l1.png"), full_page=True)
            page.reload()
            expect(page.locator("#writing-editor")).to_be_visible()
            report.check("los niños" in page.locator("#writing-text").input_value(),
                         f"[{name}] L1 draft resumed after reload")
            page.get_by_role("button", name="Entregar texto").click()
            page.get_by_role("button", name="Entregar", exact=True).click()
            expect(page.locator("#writing-pending")).to_be_visible()
            after = page.content()
            report.check(REFERENCE_SECRET not in after and REFERENCE_SECRET not in page.evaluate(
                "JSON.stringify(sessionStorage)"), f"[{name}] reference not revealed after submission")
        page.get_by_role("button", name="Volver a los ejercicios").click()
    page.get_by_role("button", name="Volver a los niveles").click()

    page.locator('.level-choice[data-level="paragraph_writing"]').click()
    expect(page.locator("#writing-empty")).to_be_visible()
    report.check("Todavía no hay ejercicios" in page.locator("#writing-empty").inner_text(),
                 f"[{name}] empty state for a level without exercises")
    page.get_by_role("button", name="Volver a los niveles").click()

    page.locator('.level-choice[data-level="full_composition"]').click()
    page.locator(".exercise-choice").first.click()
    expect(page.locator("#writing-handwritten")).to_be_visible()
    hand = page.locator("#writing-handwritten").inner_text()
    report.check("a mano" in hand and "bolígrafo" in hand and page.locator("#writing-editor").is_hidden()
                 and "90 minutos" in page.locator("#writing-ex-requirements").inner_text(),
                 f"[{name}] L5 shows handwritten conditions and no typed editor")
    page.screenshot(path=str(out / f"{name}-l5.png"), full_page=True)
    page.get_by_role("button", name="Volver a los ejercicios").click()
    page.get_by_role("button", name="Volver a los niveles").click()

    page.locator('.level-choice[data-level="idea_development"]').click()
    page.locator(f'.exercise-choice[data-exercise="{HEALTHY}"]').click()
    expect(page.locator("#writing-editor")).to_be_visible()
    body = page.locator("#writing-exercise-panel").inner_text()
    report.check(page.locator("#writing-ex-topic").inner_text() == "La alimentación saludable y el rendimiento escolar"
                 and "Situación comunicativa" in body and page.locator("#writing-ex-instructions li").count() == 5
                 and "Un solo párrafo de introducción" in body, f"[{name}] generated exercise shown in full")
    leaked = [w for w in ("EE03", "EE04", "El texto evidencia", "puntos", "rúbrica") if w in body]
    report.check(not leaked, f"[{name}] no rubric descriptors or criteria while composing ({leaked})")
    attrs = page.evaluate("""() => { const t = document.getElementById('writing-text');
        return [t.getAttribute('spellcheck'), t.getAttribute('autocorrect'), t.getAttribute('autocapitalize'),
                t.spellcheck]; }""")
    report.check(attrs == ["false", "off", "off", False], f"[{name}] spell checking and autocorrection off {attrs}")
    page.locator("#writing-text").fill(WRITING_TEXT)
    words = len(WRITING_TEXT.split())
    report.check(page.locator("#writing-words").inner_text() == f"{words} palabras",
                 f"[{name}] word counter {page.locator('#writing-words').inner_text()}")
    page.get_by_role("button", name="Guardar borrador").click()
    expect(page.locator("#writing-saved")).to_contain_text("Borrador guardado")
    page.screenshot(path=str(out / f"{name}-draft.png"), full_page=True)

    page.reload()
    expect(page.locator("#writing-editor")).to_be_visible()
    report.check(page.locator("#writing-text").input_value() == WRITING_TEXT,
                 f"[{name}] draft recovered after reload")

    page.get_by_role("button", name="Entregar texto").click()
    expect(page.locator("#writing-dialog")).to_be_visible()
    page.get_by_role("button", name="Seguir escribiendo").click()
    report.check(page.locator("#writing-dialog").is_hidden() and page.locator("#writing-editor").is_visible(),
                 f"[{name}] 'Seguir escribiendo' keeps the editor")
    page.get_by_role("button", name="Entregar texto").click()
    expect(page.locator("#writing-dialog-confirm")).to_be_visible()
    posts: list[str] = []
    page.on("request", lambda r: r.method == "POST" and "/api/writing/" in r.url and posts.append(r.url))
    page.evaluate("() => { const b = document.getElementById('writing-dialog-confirm'); b.click(); b.click(); }")
    expect(page.locator("#writing-pending")).to_be_visible()
    report.check(len(posts) == 1, f"[{name}] a double click sends one submission ({len(posts)})")
    pending = page.locator("#writing-pending").inner_text()
    report.check(pending.startswith("Pendiente de revisión del tutor") and page.locator("#writing-editor").is_hidden(),
                 f"[{name}] after submission: '{pending}'")
    page.screenshot(path=str(out / f"{name}-submitted.png"), full_page=True)
    stored = writing_rows(url, "SELECT evidence_mode, text_es, word_count FROM writing.submission "
                               "WHERE exercise_id = %s", HEALTHY)
    report.check(stored == [("typed", WRITING_TEXT, words)], f"[{name}] one submission stored: {stored}")
    report.check(writing_rows(url, "SELECT COUNT(*) FROM writing.evaluation")[0][0] == 0,
                 f"[{name}] no automatic evaluation")
    page.reload()
    expect(page.locator("#writing-pending")).to_be_visible()
    report.check(page.locator("#writing-editor").is_hidden(), f"[{name}] reload keeps the submitted state")

    page.get_by_role("button", name="Volver a los ejercicios").click()
    other = page.locator(".exercise-choice").filter(has_not_text="alimentación").first
    other.click()
    expect(page.locator("#writing-editor")).to_be_visible()
    page.locator("#writing-text").fill("Borrador sin guardar sobre el ambiente.")
    page.get_by_role("button", name="Volver al menú principal").click()
    expect(page.locator("#practice-form")).to_be_visible()
    report.check(page.locator("#subjects input").count() == 4, f"[{name}] main menu with the four subjects")
    kept = writing_rows(url, "SELECT text_es FROM writing.draft WHERE exercise_id NOT IN (%s, %s)", HEALTHY,
                        REFERENCE_TUTOR_ID)
    report.check(kept == [("Borrador sin guardar sobre el ambiente.",)],
                 f"[{name}] leaving to the main menu kept the draft {kept}")
    report.check(no_overflow(page) and not errors, f"[{name}] no overflow, no JavaScript errors {errors}")


def scenario_dashboard(page: Page, report: Report, name: str, out: Path) -> None:
    """T014: learning dashboard from the main menu; every subject, objective and status is shown."""
    page.goto(BASE)
    page.get_by_role("button", name="Ver mi progreso").click()
    expect(page.locator("#dashboard-view")).to_be_visible()
    expect(page.locator("#dashboard-objectives li").first).to_be_visible()
    report.check("no son niveles oficiales" in page.locator("#dashboard-notice").inner_text(),
                 f"[{name}] notice: indicators are not official MEP levels")
    tabs = page.locator('input[name="dashboard-subject"]')
    report.check(tabs.count() == 4, f"[{name}] four subjects")
    counts = {}
    for code, expected in (("espanol", 8), ("matematicas", 22), ("ciencias", 19), ("estudios_sociales", 29)):
        page.locator(f'input[name="dashboard-subject"][value="{code}"]').check()
        counts[code] = page.locator("#dashboard-objectives > li").count()
        chips = page.locator("#dashboard-counts li").all_inner_texts()
        labels_ok = [c.split("\n")[0] for c in chips] == ["Sin practicar", "Evidencia insuficiente",
                                                          "Necesita refuerzo", "En progreso", "Buen dominio",
                                                          "Dominio consolidado"]
        total = sum(int(c.split("\n")[-1]) for c in chips)
        report.check(counts[code] == expected and labels_ok and total == expected,
                     f"[{name}] {code}: {counts[code]} objectives, six status counts summing to {total}")
    page.locator('input[name="dashboard-subject"][value="matematicas"]').check()
    report.check(page.locator("#dash-mastery").inner_text() != "" and page.locator("#dash-practice").is_visible(),
                 f"[{name}] practice accuracy '{page.locator('#dash-practice').inner_text()}' and mastery "
                 f"'{page.locator('#dash-mastery').inner_text()}' shown")
    report.check(no_overflow(page), f"[{name}] dashboard has no horizontal overflow")
    page.screenshot(path=str(out / f"{name}-dashboard.png"), full_page=True)
    page.get_by_role("button", name="Volver al menú principal").click()
    expect(page.locator("#practice-form")).to_be_visible()
    report.check(True, f"[{name}] dashboard returns to the main menu")


def run_mock(out: Path, url: str) -> Report:
    runner = ScriptedRunner()
    report = Report()
    prepare_database(url, seed_bank=True)
    with serve(create_app(url, practice_runner=runner)), sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for viewport, size in (("desktop", DESKTOP), ("mobile", MOBILE)):
            context = browser.new_context(viewport=size, locale="es-CR", is_mobile=viewport == "mobile",
                                          has_touch=viewport == "mobile")
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            subjects = SUBJECTS if viewport == "desktop" else ["matematicas"]
            for subject in subjects:
                scenario_subject(page, runner, report, subject, viewport, out)
            if viewport == "desktop":
                scenario_duplicate_clicks(page, runner, report)
                page.evaluate("sessionStorage.clear()")
                scenario_refresh_and_resubmit(page, runner, report, out)
                scenario_failures(page, runner, report, out)
                scenario_bank_only(page, runner, report, out)
                scenario_dashboard_before_subjects_load(page, report)
            scenario_exit(page, runner, report, viewport, out)
            scenario_dashboard(page, report, viewport, out)
            scenario_dashboard_practice(page, runner, report, viewport, out)
            scenario_writing(page, report, viewport, out, url)
            report.check(not errors, f"[{viewport}] no JavaScript errors {errors}")
            context.close()
        browser.close()
    return report


def run_practice(page: Page, report: Report, name: str, out: Path) -> dict:
    """Generate (or retrieve) and complete the configured practice; returns timing and composition."""
    started = time.monotonic()
    page.get_by_role("button", name="Generar práctica").click()
    page.wait_for_selector("#quiz-view:not([hidden]), #progress-error:not([hidden])", timeout=45 * 60 * 1000)
    elapsed = time.monotonic() - started
    sid = page.evaluate("sessionStorage.getItem('mentorpro.session')")
    info = page.evaluate("async (sid) => (await fetch(`/api/practice/sessions/${sid}`)).json()", sid)
    report.check(True, f"[{name}] ready after {elapsed:.1f} s; status {info['status']}; "
                       f"composition {info['composition']}")
    if page.locator("#progress-error").is_visible():
        report.check(False, f"[{name}] generation failed: {page.locator('#progress-error').inner_text()}")
        return {"elapsed": elapsed, "info": info}
    total = int(page.locator("#quiz-position").inner_text().split(" de ")[1])
    counts = answer_all(page, report, name, ["A", "B", "C", "D", "A"][:total], None, out)
    report.check(counts["correct"] + counts["incorrect"] == total,
                 f"[{name}] answered {total}: {counts['correct']} correct, {counts['incorrect']} incorrect, "
                 f"result {page.locator('#result-percentage').inner_text()}")
    page.screenshot(path=str(out / f"{name}-result.png"), full_page=True)
    return {"elapsed": elapsed, "info": info, "session_id": sid}


def run_live(out: Path, url: str) -> Report:
    """T013 acceptance on the test database's own bank: a generated practice, the same configuration again
    from the bank (no OpenRouter), then one where only missing slots are generated."""
    report = Report()
    prepare_database(url, seed_bank=False)
    with serve(create_app(url)), sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(viewport=DESKTOP, locale="es-CR").new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        leaks: list[str] = []
        watch_disclosure(page, leaks)

        configure(page, "matematicas", ["M02", "M04", "M05"], difficulty="Intermedia")
        first = run_practice(page, report, "live-generated", out)
        stocked = first["info"]["composition"]["bank"] + first["info"]["composition"]["generated"]
        print(f"LIVE_GENERATED_SESSION={first.get('session_id')}", flush=True)
        page.get_by_role("button", name="Volver al menú principal").click()

        configure(page, "matematicas", ["M02", "M04", "M05"], difficulty="Intermedia")
        bank = run_practice(page, report, "live-bank", out)
        report.check(bank["info"]["composition"]["bank"] >= stocked,
                     f"[live-bank] repeat served from the test bank ({bank['info']['composition']}, "
                     f"{stocked} stocked)")
        if stocked == 5:
            report.check(bank["elapsed"] < 10, f"[live-bank] practice started immediately ({bank['elapsed']:.1f} s)")
        print(f"LIVE_BANK_SESSION={bank.get('session_id')}", flush=True)
        page.get_by_role("button", name="Volver al menú principal").click()

        configure(page, "matematicas", ["M02", "M06"], difficulty="Intermedia")
        page.get_by_role("button", name="Generar práctica").click()
        expect(page.locator("#progress-message")).to_contain_text("Generando preguntas adicionales", timeout=15000)
        page.screenshot(path=str(out / "live-mixed-progress.png"), full_page=True)
        report.check(True, f"[live-mixed] progress: '{page.locator('#progress-message').inner_text()}'")
        page.wait_for_selector("#quiz-view:not([hidden]), #progress-error:not([hidden])", timeout=45 * 60 * 1000)
        sid = page.evaluate("sessionStorage.getItem('mentorpro.session')")
        info = page.evaluate("async (sid) => (await fetch(`/api/practice/sessions/${sid}`)).json()", sid)
        report.check(info["status"] in ("complete", "partial"),
                     f"[live-mixed] {info['status']}; composition {info['composition']}")
        print(f"LIVE_MIXED_SESSION={sid}", flush=True)
        if page.locator("#quiz-view").is_visible():
            total = int(page.locator("#quiz-position").inner_text().split(" de ")[1])
            counts = answer_all(page, report, "live-mixed", ["A", "B", "C", "D", "A"][:total], None, out)
            report.check(sum(counts.values()) == total, f"[live-mixed] answered {total}")
            page.screenshot(path=str(out / "live-mixed-result.png"), full_page=True)
        report.check(not leaks, f"[live] no key or explanation before submission ({leaks})")
        report.check(not errors, f"[live] no JavaScript errors {errors}")
        browser.close()
    return report


def scenario_bank_only(page: Page, runner: ScriptedRunner, report: Report, out: Path) -> None:
    """Real bank inventory (Matemáticas M02, M04, M05, Intermedia): ready at once, no generation job."""
    before = runner.calls
    configure(page, "matematicas", ["M02", "M04", "M05"], difficulty="Intermedia")
    result = run_practice(page, report, "bank", out)
    report.check(result["info"]["composition"] == {"bank": 5, "generated": 0} and runner.calls == before,
                 "[bank] 5 bank questions, no generation job")
    leave_practice(page, runner, report, "bank", "menu", None)


class serve:
    def __init__(self, app):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)
        return self

    def __exit__(self, *_):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        url = test_database()
    except (db.ConfigurationError, db.UnsafeDatabaseError) as exc:
        print(f"E2E=refused: {exc}; set TEST_DATABASE_URL to a dedicated *_test database", flush=True)
        return 2
    print(f"E2E_DATABASE={db.database_name(url)}", flush=True)
    report = run_live(args.out, url) if args.live else run_mock(args.out, url)
    (args.out / ("live.txt" if args.live else "mock.txt")).write_text("\n".join(report.lines) + "\n",
                                                                      encoding="utf-8")
    print(f"E2E={'pass' if not report.failures else 'fail'} ({len(report.lines)} checks, "
          f"{len(report.failures)} failed)")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
