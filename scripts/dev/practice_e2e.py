"""Browser end-to-end test of the student practice (T010) with Playwright and installed Chrome.

Mock mode (default) replaces only the set generator with a scripted runner, so the
real API, PostgreSQL sessions, server-side evaluation and UI are exercised for all
four subjects and the failure paths without OpenRouter calls. Live mode runs the
Matemáticas acceptance practice with the real validated generator.

Usage:
    .venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR            # mocked scenarios
    .venv/Scripts/python.exe scripts/dev/practice_e2e.py --out DIR --live     # live acceptance
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import uvicorn
from playwright.sync_api import Page, expect, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.generation.practice_set import PracticeSetResult, SlotResult  # noqa: E402
from app.main import create_app  # noqa: E402

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


def run_mock(out: Path) -> Report:
    runner = ScriptedRunner()
    report = Report()
    with serve(create_app(practice_runner=runner)), sync_playwright() as p:
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
            scenario_dashboard(page, report, viewport, out)
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


def run_live(out: Path) -> Report:
    """T013 acceptance: a bank-only practice (no OpenRouter), then one where only missing slots are generated."""
    report = Report()
    with serve(create_app()), sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(viewport=DESKTOP, locale="es-CR").new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        leaks: list[str] = []
        watch_disclosure(page, leaks)

        configure(page, "matematicas", ["M02", "M04", "M05"], difficulty="Intermedia")
        bank = run_practice(page, report, "live-bank", out)
        report.check(bank["info"]["status"] == "complete" and bank["info"]["composition"]["bank"] == 5,
                     "[live-bank] all 5 questions from the bank")
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
    report = run_live(args.out) if args.live else run_mock(args.out)
    (args.out / ("live.txt" if args.live else "mock.txt")).write_text("\n".join(report.lines) + "\n",
                                                                      encoding="utf-8")
    print(f"E2E={'pass' if not report.failures else 'fail'} ({len(report.lines)} checks, "
          f"{len(report.failures)} failed)")
    return 0 if not report.failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
