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


WRITING_FIXTURES = (db.REPO_ROOT / "scripts" / "dev" / "fixtures" / "writing-exercises-L2L3-T025.json",
                    db.REPO_ROOT / "scripts" / "dev" / "fixtures" / "writing-exercises-L1-T023.json",
                    db.REPO_ROOT / ".ace" / "schemas" / "writing" / "examples" / "exercises.json")
HEALTHY = "PE-L2-alimentacion-saludable-rendimiento-19a72a"  # generated in T021
L1_TITLES = ["El fútbol en mi comunidad", "Corrección de texto expositivo: El manglar de Térraba",
             "Corrección de un texto expositivo: La feria de la ciencia"]  # generated in T023
REFERENCE_TUTOR_ID = "PE-L1-futbol-comunidad-f136a4"
REFERENCE_SECRET = "Los entrenadores voluntarios enseñan"  # test-only tutor reference text (seeded below)
TUTOR_TOKEN = "e2e-tutor-token-" + uuid.uuid4().hex  # T026: tutor review is enabled only for this run
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
            # T024: the editor starts with a copy of the text; viewing alone saves nothing.
            report.check(editor.input_value() == source, f"[{name}] L1 editor starts with the text to correct")
            page.get_by_role("button", name="Volver a los ejercicios").click()
            page.locator(".exercise-choice").nth(index).click()
            expect(page.locator("#writing-editor")).to_be_visible()
            drafts = writing_rows(url, "SELECT COUNT(*) FROM writing.draft WHERE exercise_id = %s", REFERENCE_TUTOR_ID)
            report.check(drafts[0][0] == 0, f"[{name}] opening and leaving an unchanged copy saves no draft")
            edited = source.replace("las niños", "los niños")
            editor.fill(edited)
            page.get_by_role("button", name="Guardar borrador").click()
            expect(page.locator("#writing-saved")).to_contain_text("Guardado")
            page.screenshot(path=str(out / f"{name}-l1.png"), full_page=True)
            page.reload()
            expect(page.locator("#writing-editor")).to_be_visible()
            report.check(editor.input_value() == edited and page.locator("#writing-source-text").inner_text() == source,
                         f"[{name}] L1 edits resumed after reload; the original text is unchanged")
            page.get_by_role("button", name="Restaurar texto original").click()
            expect(page.locator("#writing-restore-dialog")).to_be_visible()
            page.get_by_role("button", name="Conservar mis correcciones").click()
            report.check(editor.input_value() == edited, f"[{name}] restore asks first; 'Conservar' keeps the edits")
            page.get_by_role("button", name="Restaurar texto original").click()
            page.locator("#writing-restore-confirm").click()
            stored = writing_rows(url, "SELECT text_es FROM writing.draft WHERE exercise_id = %s", REFERENCE_TUTOR_ID)
            report.check(editor.input_value() == source and stored == [(edited,)],
                         f"[{name}] restore resets the editor only; the saved draft stays until saved again")
            editor.fill(edited)
            page.get_by_role("button", name="Entregar texto").click()
            page.get_by_role("button", name="Entregar", exact=True).click()
            expect(page.locator("#writing-pending")).to_be_visible()
            after = page.content()
            report.check(REFERENCE_SECRET not in after and REFERENCE_SECRET not in page.evaluate(
                "JSON.stringify(sessionStorage)"), f"[{name}] reference not revealed after submission")
        page.get_by_role("button", name="Volver a los ejercicios").click()
    page.get_by_role("button", name="Volver a los niveles").click()

    usage_before = writing_rows(url, "SELECT COUNT(*) FROM llm.usage_record")[0][0] \
        if writing_rows(url, "SELECT to_regclass('llm.usage_record') IS NOT NULL")[0][0] else 0
    # T025: Nivel 2 and 3 lists; L3 has development and conclusion exercises; editors start empty.
    page.locator('.level-choice[data-level="idea_development"]').click()
    expect(page.locator(".exercise-choice").first).to_be_visible()
    report.check(page.locator(".exercise-choice").count() >= 3, f"[{name}] Nivel 2 lists at least 3 exercises")
    page.get_by_role("button", name="Volver a los niveles").click()
    page.locator('.level-choice[data-level="paragraph_writing"]').click()
    expect(page.locator(".exercise-choice").first).to_be_visible()
    l3 = page.locator(".exercise-choice .level-label").all_inner_texts()
    report.check(len(l3) == 3, f"[{name}] Nivel 3 lists 3 exercises {l3}")
    kinds = []
    for index in range(len(l3)):
        page.locator(".exercise-choice").nth(index).click()
        expect(page.locator("#writing-editor")).to_be_visible()
        deliverable = page.locator("#writing-ex-deliverable").inner_text()
        kinds.append("conclusión" if "conclusión" in deliverable else "desarrollo" if "desarrollo" in deliverable else "?")
        report.check(page.locator("#writing-text").input_value() == "" and page.locator("#writing-restore").is_hidden()
                     and page.locator("#writing-source").is_hidden(),
                     f"[{name}] L3 #{index + 1} ({kinds[-1]}): empty editor, no text to correct")
        if index == 0:
            page.locator("#writing-text").fill("Primer párrafo sobre las causas.\n\nSegundo párrafo sobre las consecuencias.")
            page.get_by_role("button", name="Guardar borrador").click()
            expect(page.locator("#writing-saved")).to_contain_text("Guardado")
            page.reload()
            expect(page.locator("#writing-editor")).to_be_visible()
            report.check("Segundo párrafo" in page.locator("#writing-text").input_value(),
                         f"[{name}] L3 draft resumed after reload")
        page.get_by_role("button", name="Volver a los ejercicios").click()
    report.check(sorted(set(kinds)) == ["conclusión", "desarrollo"], f"[{name}] L3 has development and conclusion "
                                                                     f"exercises {kinds}")
    page.get_by_role("button", name="Volver a los niveles").click()
    page.locator('.level-choice[data-level="guided_composition"]').click()
    expect(page.locator("#writing-empty")).to_be_visible()
    report.check("Todavía no hay ejercicios" in page.locator("#writing-empty").inner_text(),
                 f"[{name}] empty state for a level without exercises")
    page.get_by_role("button", name="Volver a los niveles").click()
    usage_after = writing_rows(url, "SELECT COUNT(*) FROM llm.usage_record")[0][0] \
        if writing_rows(url, "SELECT to_regclass('llm.usage_record') IS NOT NULL")[0][0] else 0
    report.check(usage_after == usage_before, f"[{name}] opening levels and exercises made no OpenRouter call")

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
    report.check(page.locator("#writing-text").input_value() == ""
                 and page.locator("#writing-restore").is_hidden(),
                 f"[{name}] L2 editor starts empty, no restore action")
    page.locator("#writing-text").fill(WRITING_TEXT)
    words = len(WRITING_TEXT.split())
    report.check(page.locator("#writing-words").inner_text() == f"{words} palabras",
                 f"[{name}] word counter {page.locator('#writing-words').inner_text()}")
    page.get_by_role("button", name="Guardar borrador").click()
    expect(page.locator("#writing-saved")).to_contain_text("Guardado")
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
    kept = writing_rows(url, "SELECT text_es FROM writing.draft WHERE text_es = %s",
                        "Borrador sin guardar sobre el ambiente.")
    report.check(kept == [("Borrador sin guardar sobre el ambiente.",)],
                 f"[{name}] leaving to the main menu kept the draft {kept}")
    report.check(no_overflow(page) and not errors, f"[{name}] no overflow, no JavaScript errors {errors}")


def tutor_complete(tutor: Page, scores: dict[str, int]) -> None:
    for code, points in scores.items():
        tutor.locator(f'fieldset[data-criterion="{code}"] input[value="{points}"]').check()
    tutor.locator("#tutor-improvements").fill("Revisá la idea complementaria del segundo párrafo.")
    tutor.get_by_role("button", name="Completar evaluación").click()
    tutor.get_by_role("button", name="Completar", exact=True).click()
    expect(tutor.locator("#tutor-locked")).to_be_visible()


def scenario_tutor(tutor: Page, student: Page, report: Report, viewport: str, out: Path, url: str) -> None:
    """T026: tutor review in its own browser context; the student sees scores and feedback, never the reference."""
    name = f"{viewport}-tutor"
    errors: list[str] = []
    tutor.on("pageerror", lambda exc: errors.append(str(exc)))
    l3 = writing_rows(url, "SELECT exercise_id FROM writing.exercise WHERE level = 'paragraph_writing' "
                           "ORDER BY created_at LIMIT 1")[0][0]
    student.goto(BASE)
    student.evaluate("async (id) => fetch(`/api/writing/exercises/${id}/submit`, {method: 'POST', headers: "
                     "{'Content-Type': 'application/json'}, body: JSON.stringify({text: 'Las causas son varias.\\n\\n"
                     "Las consecuencias también.', client_request_id: 'e2e-l3-' + Date.now()})})", l3)

    report.check(student.request.get(BASE + "api/tutor/queue").status == 403,
                 f"[{name}] tutor API refuses requests without the tutor code")
    tutor.goto(BASE + "tutor")
    tutor.locator("#tutor-token").fill("codigo-incorrecto-123456")
    tutor.get_by_role("button", name="Entrar").click()
    expect(tutor.locator("#tutor-error")).to_be_visible()
    report.check("incorrecto" in tutor.locator("#tutor-error").inner_text(), f"[{name}] wrong tutor code refused")
    tutor.locator("#tutor-token").fill(TUTOR_TOKEN)
    tutor.get_by_role("button", name="Entrar").click()
    expect(tutor.locator(".exercise-choice").first).to_be_visible()
    queue = tutor.locator(".exercise-choice").all_inner_texts()
    report.check(len(queue) == 3 and all("Pendiente" in q for q in queue),
                 f"[{name}] queue shows 3 pending submissions (L1, L2, L3)")
    tutor.screenshot(path=str(out / f"{name}-queue.png"), full_page=True)

    tutor.locator(".exercise-choice", has_text="El fútbol en mi comunidad").click()
    expect(tutor.locator("#tutor-reference-block")).to_be_visible()
    options = tutor.locator('fieldset[data-criterion="EE07"] .tutor-option').all_inner_texts()
    from app.writing import contracts
    official = contracts.criteria()["EE07"]["descriptors_es"]
    report.check(REFERENCE_SECRET in tutor.locator("#tutor-reference").inner_text()
                 and [o.split("\n", 1)[-1].strip() for o in options] == official,
                 f"[{name}] L1: reference correction and the five official EE07 descriptors shown")
    tutor.locator('fieldset[data-criterion="EE07"] input[value="3"]').check()
    tutor.locator("#tutor-strengths").fill("Corregiste bien «los niños».")
    tutor.get_by_role("button", name="Guardar evaluación parcial").click()
    expect(tutor.locator("#tutor-saved")).to_contain_text("Evaluación parcial guardada")
    tutor.reload()
    tutor.locator(".exercise-choice", has_text="El fútbol en mi comunidad").click()
    expect(tutor.locator("#tutor-detail")).to_be_visible()
    report.check(tutor.locator('fieldset[data-criterion="EE07"] input[value="3"]').is_checked()
                 and "los niños" in tutor.locator("#tutor-strengths").input_value(),
                 f"[{name}] partial evaluation resumed after reload")
    tutor.get_by_role("button", name="Completar evaluación").click()
    report.check("EE08" in tutor.locator("#tutor-error").inner_text() and tutor.locator("#tutor-dialog").is_hidden(),
                 f"[{name}] completion needs every criterion scored")
    tutor.screenshot(path=str(out / f"{name}-evaluation.png"), full_page=True)
    tutor_complete(tutor, {"EE08": 2})
    report.check(tutor.locator("#tutor-complete").is_disabled() and tutor.locator("#tutor-save").is_disabled(),
                 f"[{name}] completed evaluation is locked (no second completion)")
    duplicate = tutor.evaluate("async ([sid, token]) => (await fetch(`/api/tutor/submissions/${sid}/evaluation`, "
                               "{method: 'PUT', headers: {'Content-Type': 'application/json', 'X-Tutor-Token': token},"
                               " body: JSON.stringify({scores: {EE07: 4, EE08: 4}, complete: true})})).status",
                               [writing_rows(url, "SELECT submission_id FROM writing.submission WHERE exercise_id = %s",
                                             REFERENCE_TUTOR_ID)[0][0], TUTOR_TOKEN])
    report.check(duplicate == 409, f"[{name}] a second completion is refused by the server ({duplicate})")
    tutor.get_by_role("button", name="Volver a las entregas").click()

    for title, codes in (("La alimentación saludable", {"EE03": 3, "EE04": 2}), (None, None)):
        if title:
            tutor.locator(".exercise-choice", has_text=title).click()
        else:  # the L3 entry, by title; read its criteria only once its screen has loaded
            l3_title = writing_rows(url, "SELECT record->>'topic_es' FROM writing.exercise WHERE exercise_id = %s",
                                    l3)[0][0]
            tutor.locator(".exercise-choice", has_text=l3_title).click()
            expect(tutor.locator("#tutor-title")).to_have_text(l3_title)
            codes = {c: 2 for c in tutor.locator("#tutor-criteria fieldset").evaluate_all(
                "(nodes) => nodes.map((n) => n.dataset.criterion)")}
        expect(tutor.locator("#tutor-detail")).to_be_visible()
        report.check(tutor.locator("#tutor-reference-block").is_hidden(), f"[{name}] {list(codes)}: no reference block")
        tutor_complete(tutor, codes)
        tutor.get_by_role("button", name="Volver a las entregas").click()
    expect(tutor.locator(".tutor-badge", has_text="Completada")).to_have_count(3)  # refreshed queue
    statuses = tutor.locator(".tutor-badge").all_inner_texts()
    report.check(statuses == ["Completada"] * 3, f"[{name}] L1, L2 and L3 evaluations completed {statuses}")

    student.goto(BASE)
    student.get_by_role("button", name="Abrir Producción escrita").click()
    student.locator('.level-choice[data-level="writing_conventions"]').click()
    student.locator(".exercise-choice", has_text="El fútbol").click()
    expect(student.locator("#writing-feedback")).to_be_visible()
    fb = student.locator("#writing-feedback").inner_text()
    html = student.content() + student.evaluate("JSON.stringify(sessionStorage) + JSON.stringify(localStorage)")
    report.check("3 de 4" in fb and "2 de 4" in fb and "Corregiste bien" in fb and "Revisá la idea" in fb
                 and "Revisado el" in fb and "Revisado por el tutor" in student.locator("#writing-pending").inner_text(),
                 f"[{name}] student sees scores, feedback, improvements and date")
    report.check(REFERENCE_SECRET not in html and "corrected_text" not in html and TUTOR_TOKEN not in html,
                 f"[{name}] student page never contains the reference correction or the tutor code")
    student.screenshot(path=str(out / f"{name}-student-feedback.png"), full_page=True)
    report.check(no_overflow(tutor) and not errors, f"[{name}] tutor page: no overflow, no JavaScript errors {errors}")


L4_FIXTURE = db.REPO_ROOT / "scripts" / "dev" / "fixtures" / "writing-exercise-L4-T028.json"  # generated in T028
GUIDED_TEXT = {"plan": "Ideas: qué es, por qué pasa, qué provoca y qué podemos hacer.",
               "introduction": "Este tema es importante para toda la comunidad escolar.",
               "development_1": "Una causa es que muchas personas no conocen el problema.",
               "development_2": "Una consecuencia es que la convivencia en la escuela empeora.",
               "conclusion": "Podemos organizar campañas y conversar en clase para mejorar."}


def scenario_guided(student: Page, tutor: Page, report: Report, viewport: str, out: Path, url: str) -> None:
    """T028: Nivel 4 in five stages; drafts survive reload and navigation; tutor review; dashboard."""
    name = f"{viewport}-guided"
    from app.writing import contracts
    errors: list[str] = []
    student.on("pageerror", lambda exc: errors.append(str(exc)))
    record = json.loads(L4_FIXTURE.read_text(encoding="utf-8"))
    WritingStore(url).add_exercise(record)  # after scenario_writing, which checks that Nivel 4 starts empty
    eid = record["exercise_id"]
    student.goto(BASE)
    student.evaluate("sessionStorage.clear()")
    student.goto(BASE)
    student.get_by_role("button", name="Abrir Producción escrita").click()
    student.locator('.level-choice[data-level="guided_composition"]').click()
    student.locator(f'.exercise-choice[data-exercise="{eid}"]').click()
    expect(student.locator("#writing-guided")).to_be_visible()
    steps = student.locator(".guided-step").all_inner_texts()
    report.check(len(steps) == 5 and student.locator("#writing-editor").is_hidden(),
                 f"[{name}] five stages, no single-text editor {steps}")
    view = student.locator("#writing-view").inner_text()
    report.check(not any(w in view for w in ("EE0", "EE1", "rúbrica", "El texto evidencia")),
                 f"[{name}] no criteria codes, rubric or descriptors shown to the student")
    visible = lambda: [s for s in GUIDED_TEXT if student.locator(f'.guided-field[data-section="{s}"]').is_visible()]  # noqa: E731
    report.check(visible() == ["plan"] and all(not student.locator(f"#guided-{k}").input_value()
                                               for k in ("plan-text", "introduction")),
                 f"[{name}] stage 1 shows only the planning notes, empty (nothing generated) {visible()}")
    student.locator("#guided-plan-text").fill(GUIDED_TEXT["plan"])
    student.screenshot(path=str(out / f"{name}-stage1.png"), full_page=True)
    student.get_by_role("button", name="Siguiente etapa").click()
    expect(student.locator("#guided-introduction")).to_be_visible()
    report.check(student.locator("#guided-plan").inner_text().strip() == record["scaffolding_es"][0],
                 f"[{name}] stage 2 shows the exercise's own plan hint for the introduction")
    student.locator("#guided-introduction").fill(GUIDED_TEXT["introduction"])
    expect(student.locator("#guided-saved")).to_contain_text("Guardado", timeout=10000)  # autosave
    student.reload()
    expect(student.locator("#guided-introduction")).to_be_visible()
    report.check(student.locator("#guided-introduction").input_value() == GUIDED_TEXT["introduction"]
                 and student.locator("#guided-plan-text").input_value() == GUIDED_TEXT["plan"],
                 f"[{name}] reload resumes stage 2 with the plan and introduction")
    student.get_by_role("button", name="Siguiente etapa").click()
    report.check(visible() == ["development_1", "development_2"], f"[{name}] stage 3 has two text areas {visible()}")
    student.locator("#guided-development-1").fill(GUIDED_TEXT["development_1"])
    student.locator("#guided-development-2").fill(GUIDED_TEXT["development_2"])
    student.screenshot(path=str(out / f"{name}-stage3.png"), full_page=True)
    student.locator('.guided-step[data-stage="introduction"]').click()
    expect(student.locator("#guided-introduction")).to_be_visible()
    report.check(student.locator("#guided-introduction").input_value() == GUIDED_TEXT["introduction"],
                 f"[{name}] going back keeps the introduction")
    student.get_by_role("button", name="Volver al menú principal").click()
    expect(student.locator("#practice-form")).to_be_visible()
    stored = writing_rows(url, "SELECT sections FROM writing.draft WHERE exercise_id = %s", eid)[0][0]
    report.check({k: stored[k] for k in ("plan", "introduction", "development_1", "development_2")}
                 == {k: GUIDED_TEXT[k] for k in ("plan", "introduction", "development_1", "development_2")},
                 f"[{name}] leaving to the main menu saved every section in PostgreSQL")
    student.get_by_role("button", name="Abrir Producción escrita").click()
    student.locator('.level-choice[data-level="guided_composition"]').click()
    student.locator(f'.exercise-choice[data-exercise="{eid}"]').click()
    student.locator('.guided-step[data-stage="conclusion"]').click()
    student.locator("#guided-conclusion").fill(GUIDED_TEXT["conclusion"])
    student.get_by_role("button", name="Siguiente etapa").click()
    expect(student.locator("#guided-review")).to_be_visible()
    paragraphs = student.locator("#guided-preview p").all_inner_texts()
    order = ["introduction", "development_1", "development_2", "conclusion"]
    expected_words = sum(len(GUIDED_TEXT[k].split()) for k in order)
    report.check(paragraphs == [GUIDED_TEXT[k] for k in order]
                 and student.locator("#guided-words").inner_text() == f"{expected_words} palabras",
                 f"[{name}] review shows the four paragraphs in order and {expected_words} words")
    report.check(no_overflow(student), f"[{name}] no horizontal overflow")
    student.screenshot(path=str(out / f"{name}-review.png"), full_page=True)
    student.get_by_role("button", name="Entregar composición").click()
    student.locator("#writing-dialog-confirm").click()
    expect(student.locator("#writing-pending")).to_contain_text("Pendiente de revisión del tutor")
    sub = writing_rows(url, "SELECT text_es, sections, paragraph_count, exercise_revision, "
                            "(SELECT COUNT(*) FROM writing.submission WHERE exercise_id = %s) "
                            "FROM writing.submission WHERE exercise_id = %s", eid, eid)[0]
    report.check(sub[0] == "\n\n".join(GUIDED_TEXT[k] for k in order) and sub[1]["plan"] == GUIDED_TEXT["plan"]
                 and GUIDED_TEXT["plan"] not in sub[0] and sub[2:] == (4, 1, 1),
                 f"[{name}] one submission: four paragraphs assembled, plan kept apart, revision {sub[3]}")
    student.screenshot(path=str(out / f"{name}-submitted.png"), full_page=True)

    tutor.goto(BASE + "tutor")
    tutor.locator("#tutor-token").fill(TUTOR_TOKEN)
    tutor.get_by_role("button", name="Entrar").click()
    tutor.locator(".exercise-choice", has_text=record["topic_es"]).click()
    expect(tutor.locator("#tutor-sections-block")).to_be_visible()
    sections = tutor.locator(".tutor-section p").all_inner_texts()
    report.check(sections == [GUIDED_TEXT[k] for k in ["plan"] + order]
                 and tutor.locator("#tutor-plan li").count() == 4
                 and "\n\n" in tutor.locator("#tutor-student").inner_text(),
                 f"[{name}] tutor sees plan hints, planning notes, four paragraphs and the composition")
    official = contracts.criteria()
    labels = tutor.locator('fieldset[data-criterion="EE04"] .tutor-option').all_inner_texts()
    report.check([x.split("\n", 1)[-1].strip() for x in labels] == official["EE04"]["descriptors_es"]
                 and tutor.locator(".tutor-optional-title").is_visible(),
                 f"[{name}] EE04 with official descriptors; conventions shown as optional")
    for code in ("EE01", "EE02", "EE03", "EE04", "EE05", "EE06"):
        tutor.locator(f'fieldset[data-criterion="{code}"] input[value="3"]').check()
    tutor.locator('fieldset[data-criterion="EE09"] input[value="4"]').check()
    tutor.locator("#tutor-strengths").fill("Tu plan ordenó muy bien las ideas.")
    tutor.screenshot(path=str(out / f"{name}-tutor.png"), full_page=True)
    tutor.get_by_role("button", name="Completar evaluación").click()
    tutor.get_by_role("button", name="Completar", exact=True).click()
    expect(tutor.locator("#tutor-locked")).to_be_visible()
    codes = [r[0] for r in writing_rows(url, "SELECT c.criterion_code FROM writing.criterion_score c JOIN "
                                             "writing.evaluation v USING (evaluation_id) JOIN writing.submission s "
                                             "USING (submission_id) WHERE s.exercise_id = %s ORDER BY 1", eid)]
    report.check(codes == ["EE01", "EE02", "EE03", "EE04", "EE05", "EE06", "EE09"],
                 f"[{name}] completed with EE01-EE06 and the optional EE09 only {codes}")

    student.reload()
    expect(student.locator("#writing-feedback")).to_be_visible()
    feedback = student.locator("#writing-feedback").inner_text()
    report.check(feedback.count("3 de 4") == 6 and "4 de 4" in feedback and "Tu plan ordenó" in feedback,
                 f"[{name}] student sees the completed evaluation")
    student.screenshot(path=str(out / f"{name}-feedback.png"), full_page=True)
    student.get_by_role("button", name="Volver al menú principal").click()
    student.get_by_role("button", name="Ver mi progreso").click()
    student.locator("#dashboard-subjects label", has_text="Producción escrita").click()
    expect(student.locator('#dw-levels li[data-level="guided_composition"]')).to_contain_text("1 evaluado")
    ee09 = student.locator('li.dw-criterion[data-code="EE09"]').inner_text()
    report.check("Última calificación: 4 de 4" in ee09
                 and "1 entregado" in student.locator('#dw-levels li[data-level="guided_composition"]').inner_text(),
                 f"[{name}] dashboard: L4 evaluated, EE09 latest 4 de 4")
    student.screenshot(path=str(out / f"{name}-dashboard.png"), full_page=True)
    report.check(not errors, f"[{name}] no JavaScript errors {errors}")


def scenario_drafts(page: Page, report: Report, out: Path, url: str) -> None:
    """T030 (ADR-028): saving indicator, retry, lifecycle flushes and ordering, on L2 and L1 exercises."""
    name = "desktop-drafts"
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("dialog", lambda dialog: dialog.accept())  # beforeunload: the student chooses to leave

    def free(level: str) -> str:
        return writing_rows(url, "SELECT exercise_id FROM writing.exercise e WHERE level = %s AND NOT EXISTS (SELECT "
                                 "1 FROM writing.submission s WHERE s.exercise_id = e.exercise_id) ORDER BY "
                                 "exercise_id LIMIT 1", level)[0][0]

    def stored(eid: str) -> str | None:
        rows = writing_rows(url, "SELECT text_es FROM writing.draft WHERE exercise_id = %s", eid)
        return rows[0][0] if rows else None

    def wait_stored(eid: str, text: str, ms: int, waiter: Page | None = None) -> bool:
        # After page.close, a second page keeps Playwright processing browser events (the closing page's
        # beforeunload dialog) while the database is polled; time.sleep alone would not.
        for _ in range(ms // 100):
            if stored(eid) == text:
                return True
            (waiter or page).wait_for_timeout(100)
        return stored(eid) == text

    def open_exercise(level: str, eid: str) -> None:
        page.goto(BASE)
        page.evaluate("sessionStorage.clear()")
        page.goto(BASE)
        page.get_by_role("button", name="Abrir Producción escrita").click()
        page.locator(f'.level-choice[data-level="{level}"]').click()
        page.locator(f'.exercise-choice[data-exercise="{eid}"]').click()
        expect(page.locator("#writing-editor")).to_be_visible()

    l2 = free("idea_development")
    open_exercise("idea_development", l2)
    text = page.locator("#writing-text")
    text.press_sequentially("Escribo rápido y salgo enseguida.", delay=5)
    page.get_by_role("button", name="Volver a los ejercicios").click()
    expect(page.locator("#writing-list-panel")).to_be_visible()
    report.check(stored(l2) == "Escribo rápido y salgo enseguida.",
                 f"[{name}] rapid typing then navigation: text saved before leaving")

    page.locator(f'.exercise-choice[data-exercise="{l2}"]').click()
    text.fill("Segunda versión del borrador.")
    report.check(page.locator("#writing-saved").inner_text().strip() == "· Cambios sin guardar",
                 f"[{name}] pending edits are shown as not saved yet")
    expect(page.locator("#writing-saved")).to_contain_text("Guardado", timeout=5000)
    report.check(stored(l2) == "Segunda versión del borrador.",
                 f"[{name}] autosave: «Guardado» only once the server stored the text")

    page.route("**/draft", lambda route: route.abort())
    text.fill("Versión escrita sin conexión.")
    page.get_by_role("button", name="Guardar borrador").click()
    expect(page.locator("#writing-saved")).to_contain_text("No se pudo guardar")
    page.get_by_role("button", name="Volver a los ejercicios").click()
    expect(page.locator("#writing-error")).to_contain_text("Reintentar")
    report.check(page.locator("#writing-retry").is_visible() and text.input_value() == "Versión escrita sin conexión."
                 and stored(l2) == "Segunda versión del borrador." and page.locator("#writing-editor").is_visible()
                 and "Reintentar" in page.locator("#writing-error").inner_text(),
                 f"[{name}] failed save: text kept, earlier draft untouched, student stays, retry offered")
    page.screenshot(path=str(out / f"{name}-failed.png"), full_page=True)
    page.unroute("**/draft")
    page.get_by_role("button", name="Reintentar").click()
    expect(page.locator("#writing-saved")).to_contain_text("Guardado")
    report.check(stored(l2) == "Versión escrita sin conexión." and page.locator("#writing-retry").is_hidden(),
                 f"[{name}] retry after the connection returns saves the text")

    text.fill("Texto antes de cambiar de pestaña.")
    page.evaluate("""() => { Object.defineProperty(document, 'visibilityState', {value: 'hidden', configurable: true});
                     document.dispatchEvent(new Event('visibilitychange')); }""")
    report.check(wait_stored(l2, "Texto antes de cambiar de pestaña.", 1500),
                 f"[{name}] hidden tab: pending edits sent at once (before the 2 s autosave)")
    page.evaluate("() => { delete document.visibilityState; }")

    held: list = []
    page.route("**/draft", lambda route: held.append(route))
    text.fill("Primera parte")
    page.get_by_role("button", name="Guardar borrador").click()
    expect(page.locator("#writing-saved")).to_contain_text("Guardando")
    text.fill("Primera parte y segunda parte, la más nueva.")
    page.unroute("**/draft")
    page.reload()  # beforeunload accepted; pagehide sends the newest text with keepalive
    expect(page.locator("#writing-editor")).to_be_visible()
    newest = "Primera parte y segunda parte, la más nueva."
    report.check(wait_stored(l2, newest, 3000), f"[{name}] reload during an outstanding save keeps the newest text")
    for route in held:  # the older request arrives late
        try:
            route.continue_()
        except Exception:  # noqa: BLE001 - the browser may already have cancelled it
            pass
    page.wait_for_timeout(500)
    page.reload()
    expect(page.locator("#writing-editor")).to_be_visible()
    report.check(stored(l2) == newest and text.input_value() == newest,
                 f"[{name}] the delayed older save did not overwrite it; reload restores it")

    l1 = free("writing_conventions")
    open_exercise("writing_conventions", l1)
    original = text.input_value()
    text.fill(original + " Corrección final antes de cerrar.")
    pump = page.context.new_page()
    page.close(run_before_unload=True)
    report.check(wait_stored(l1, original + " Corrección final antes de cerrar.", 3000, pump),
                 f"[{name}] L1: closing the tab sends the pending correction")
    report.check(not errors, f"[{name}] no JavaScript errors {errors}")
    pump.close()


def scenario_quarantine(page: Page, report: Report, viewport: str, url: str) -> None:
    """T029 (ADR-027): a quarantined exercise leaves the student list and cannot be opened; reinstated, it returns."""
    name = f"{viewport}-quarantine"
    store = WritingStore(url)
    eid = writing_rows(url, "SELECT exercise_id FROM writing.exercise e WHERE level = 'idea_development' AND NOT "
                            "EXISTS (SELECT 1 FROM writing.submission s WHERE s.exercise_id = e.exercise_id) "
                            "ORDER BY exercise_id LIMIT 1")[0][0]  # submitted work would stay readable
    store.set_eligibility(eid, "quarantined", "e2e: review not independent", "RCA-004")
    page.goto(BASE)
    page.evaluate("sessionStorage.clear()")
    page.goto(BASE)
    page.get_by_role("button", name="Abrir Producción escrita").click()
    page.locator('.level-choice[data-level="idea_development"]').click()
    expect(page.locator(".exercise-choice").first).to_be_visible()
    listed = page.locator(".exercise-choice").evaluate_all("(n) => n.map((x) => x.dataset.exercise)")
    status = page.request.get(BASE + f"api/writing/exercises/{eid}").status
    report.check(eid not in listed and status == 404, f"[{name}] quarantined exercise hidden ({len(listed)} listed) "
                                                      f"and not openable ({status})")
    store.set_eligibility(eid, "eligible", "e2e: independent review passed", "independent-review-1.1")
    page.get_by_role("button", name="Volver a los niveles").click()
    page.locator('.level-choice[data-level="idea_development"]').click()
    expect(page.locator(f'.exercise-choice[data-exercise="{eid}"]')).to_be_visible()
    report.check(True, f"[{name}] reinstated exercise listed again")


LATEST_SCORES_SQL = """SELECT DISTINCT ON (c.criterion_code) c.criterion_code, c.points
    FROM writing.criterion_score c JOIN writing.evaluation v USING (evaluation_id)
    WHERE v.status = 'completed' AND c.status = 'scored'
    ORDER BY c.criterion_code, v.evaluated_at DESC"""


def scenario_writing_dashboard(page: Page, report: Report, viewport: str, out: Path, url: str) -> None:
    """T027: Producción escrita in "Mi progreso", checked against the test database's evaluation rows."""
    name = f"{viewport}-writing-dashboard"
    from app.writing import contracts
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    # One more L1 submission that stays pending (after scenario_tutor completed L1, L2 and L3).
    pending_id = writing_rows(url, "SELECT exercise_id FROM writing.exercise e WHERE level = 'writing_conventions' "
                                   "AND NOT EXISTS (SELECT 1 FROM writing.submission s WHERE s.exercise_id = "
                                   "e.exercise_id) ORDER BY exercise_id LIMIT 1")[0][0]
    page.goto(BASE)
    page.evaluate("async (id) => fetch(`/api/writing/exercises/${id}/submit`, {method: 'POST', headers: "
                  "{'Content-Type': 'application/json'}, body: JSON.stringify({text: 'Texto pendiente de revisión.', "
                  "client_request_id: 'e2e-dash-' + Date.now()})})", pending_id)
    latest = dict(writing_rows(url, LATEST_SCORES_SQL))
    counts = writing_rows(url, "SELECT COUNT(*), COUNT(v.evaluation_id) FILTER (WHERE v.status = 'completed') "
                               "FROM writing.submission s LEFT JOIN writing.evaluation v USING (submission_id)")[0]
    pending_codes = {r[0] for r in writing_rows(url, "SELECT unnest(target_criteria) FROM writing.exercise "
                                                     "WHERE exercise_id = %s", pending_id)} - set(latest)
    l1 = writing_rows(url, "SELECT COUNT(*), COUNT(v.evaluation_id) FILTER (WHERE v.status = 'completed') "
                           "FROM writing.submission s JOIN writing.exercise e USING (exercise_id) "
                           "LEFT JOIN writing.evaluation v USING (submission_id) "
                           "WHERE e.level = 'writing_conventions'")[0]

    def open_writing_tab() -> None:
        page.evaluate("sessionStorage.clear()")  # scenario_tutor left an exercise open; start at the main menu
        page.goto(BASE)
        page.get_by_role("button", name="Ver mi progreso").click()
        expect(page.locator("#dashboard-view")).to_be_visible()
        page.locator("#dashboard-subjects label", has_text="Producción escrita").click()
        expect(page.locator("#dashboard-writing li.dw-criterion")).to_have_count(20)

    open_writing_tab()
    report.check(page.locator("#dashboard-mc").is_hidden() and page.locator("#dashboard-notice").is_hidden(),
                 f"[{name}] writing tab hides the multiple-choice metrics and statuses")
    codes = page.locator("li.dw-criterion").evaluate_all("(n) => n.map((x) => x.dataset.code)")
    texts = {c: page.locator(f'li.dw-criterion[data-code="{c}"]').inner_text() for c in codes}
    criteria = contracts.criteria()
    report.check(codes == [f"EE{n:02d}" for n in range(1, 21)]
                 and all(criteria[c]["statement_es"] in texts[c] for c in codes),
                 f"[{name}] all 20 EE criteria with their official wording")
    total, completed = counts
    shown = [page.locator(f"#dw-{k}").inner_text() for k in ("submitted", "completed", "pending")]
    report.check(shown == [str(total), str(completed), str(total - completed)],
                 f"[{name}] submitted / completed / pending {shown} match the database ({total}, {completed})")
    report.check(page.locator("#dw-last").inner_text() not in ("", "Todavía no hay práctica"),
                 f"[{name}] last practice date '{page.locator('#dw-last').inner_text()}'")
    wrong = [c for c in codes if (c in latest) != (f"Última calificación: {latest.get(c)} de 4" in texts[c])
             or (c not in latest and "Última calificación" in texts[c])]
    report.check(latest and not wrong, f"[{name}] latest score shown exactly for the {len(latest)} evaluated "
                                       f"criteria {sorted(latest)} {wrong}")
    report.check(all("Evaluación pendiente" in texts[c] and "calificación" not in texts[c] for c in pending_codes)
                 and pending_codes, f"[{name}] pending submission marks {sorted(pending_codes)} without a score")
    report.check("Sin evaluar" in texts["EE19"] and "de 4" not in texts["EE19"],
                 f"[{name}] EE19 (handwriting) stays without a score")
    for dim in contracts.rubric()["dimensions"]:
        scored = [latest[c] for c, v in criteria.items() if v["dimension"] == dim["ordinal"] and c in latest]
        summary = page.locator(f'.dw-dimension[data-dimension="{dim["ordinal"]}"] .dw-dimension-summary').inner_text()
        expected = (f"Promedio {('%g' % round(sum(scored) / len(scored), 1)).replace('.', ',')} de 4 · {len(scored)} de"
                    if scored else "Sin evaluar")
        report.check(summary.startswith(expected), f"[{name}] dimension {dim['ordinal']}: '{summary}' "
                                                   f"(SQL: {scored})")
    levels = page.locator("#dw-levels li").all_inner_texts()
    report.check(len(levels) == 5 and f"{l1[1]} evaluado" in levels[0] and f"{l1[0]} entregado" in levels[0],
                 f"[{name}] per level L1–L5: {[lv.replace(chr(10), ' ') for lv in levels]}")
    report.check(no_overflow(page), f"[{name}] no horizontal overflow")
    page.screenshot(path=str(out / f"{name}.png"), full_page=True)

    page.reload()
    open_writing_tab()
    report.check(f"Última calificación: {latest['EE07']} de 4"
                 in page.locator('li.dw-criterion[data-code="EE07"]').inner_text(),
                 f"[{name}] completed evaluation still shown after reload")
    page.locator('input[name="dashboard-subject"][value="matematicas"]').check()
    report.check(page.locator("#dashboard-mc").is_visible() and page.locator("#dashboard-writing").is_hidden()
                 and page.locator("#dashboard-objectives > li").count() == 22,
                 f"[{name}] Matemáticas tab still shows the multiple-choice progress")
    page.locator("#dashboard-subjects label", has_text="Producción escrita").click()
    page.get_by_role("button", name="Ir a Producción escrita").click()
    expect(page.locator("#writing-levels .level-choice").first).to_be_visible()
    report.check(page.locator("#writing-view").is_visible(), f"[{name}] button opens the writing exercise list")
    report.check(not errors, f"[{name}] no JavaScript errors {errors}")


def scenario_dashboard(page: Page, report: Report, name: str, out: Path) -> None:
    """T014: learning dashboard from the main menu; every subject, objective and status is shown."""
    page.goto(BASE)
    page.get_by_role("button", name="Ver mi progreso").click()
    expect(page.locator("#dashboard-view")).to_be_visible()
    expect(page.locator("#dashboard-objectives li").first).to_be_visible()
    report.check("no son niveles oficiales" in page.locator("#dashboard-notice").inner_text(),
                 f"[{name}] notice: indicators are not official MEP levels")
    tabs = page.locator('input[name="dashboard-subject"]')
    report.check(tabs.count() == 5, f"[{name}] four subjects and Producción escrita")
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
    with serve(create_app(url, practice_runner=runner, tutor_token=TUTOR_TOKEN)), sync_playwright() as p:
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
            tutor_context = browser.new_context(viewport=size, locale="es-CR", is_mobile=viewport == "mobile",
                                                has_touch=viewport == "mobile")
            scenario_tutor(tutor_context.new_page(), page, report, viewport, out, url)
            tutor_context.close()
            scenario_writing_dashboard(page, report, viewport, out, url)
            tutor_context = browser.new_context(viewport=size, locale="es-CR", is_mobile=viewport == "mobile",
                                                has_touch=viewport == "mobile")
            scenario_guided(page, tutor_context.new_page(), report, viewport, out, url)
            tutor_context.close()
            scenario_quarantine(page, report, viewport, url)
            if viewport == "desktop":
                scenario_drafts(context.new_page(), report, out, url)  # closes its own page
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
