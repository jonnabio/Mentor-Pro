"""T072 (ADR-038): automatic eligibility behind a flag, student reports and the tutor's resolution (mentor_pro_test).

Pending questions come from a real seeding run with a fake model (six cells, all awaiting review). A practice
session is stored directly with bank items pointing at those questions, as the composer would. API tests always
run; the browser tests are opt-in (MENTOR_PRO_BROWSER=1) like the other browser regressions.
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app.generation.validation import CHECKER_VERSION
from app.main import STATIC_DIR
from app.practice import question_reports, replenishment, seeding
from app.practice import replenish_schedule as rs
from app.practice.bank import auto_eligibility
from app.practice.replenish_schedule import ScheduleError, ScheduleSettings
from app.practice.store import PracticeStore
from app.tutor_main import create_tutor_app
from conftest import SYNTHETIC
from test_bank_seeding import eligible, seed_run, url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_replenish_schedule import FakeRun, clean_schedule
from test_tutor_review import GATEWAY, TOKEN, call, review_app

REPORTS = "/api/tutor/reports"
AUTO = "MENTOR_PRO_AUTO_ELIGIBILITY"


# ---------------------------------------------------------------- fixtures and helpers


def _clean_sessions(url):  # noqa: F811
    with psycopg.connect(url, autocommit=True) as conn:  # synthetic test database only
        conn.execute("DELETE FROM generation.question_report")
        sessions = "SELECT session_id FROM practice.session WHERE client_request_id LIKE 't072-%%'"
        conn.execute(f"DELETE FROM practice.answer WHERE session_id IN ({sessions})")
        conn.execute(f"DELETE FROM practice.item WHERE session_id IN ({sessions})")
        conn.execute("DELETE FROM practice.session WHERE client_request_id LIKE 't072-%%'")


@pytest.fixture()
def bank(url, catalog_conn, synthetic_client, monkeypatch):  # noqa: F811
    monkeypatch.delenv(AUTO, raising=False)
    _clean_sessions(url)
    batch_id = seed_run(url, catalog_conn)["batch_id"]  # six generated questions, cells 1..6, all pending
    _, schema = synthetic_client.app.state.catalog_target
    app = review_app(url, schema)
    yield app, batch_id
    _clean_sessions(url)


def by_cell(url, batch_id):  # noqa: F811
    return {r["cell"]: r["request_id"] for r in seeding.links(url, batch_id) if r["active"]}


def practice(url, request_ids):  # noqa: F811
    """A complete bank practice serving `request_ids` in slots 1..n (what the composer stores)."""
    store = PracticeStore(url)
    with psycopg.connect(url) as conn:
        rows = {r[0]: r[1:] for r in conn.execute(
            "SELECT request_id, item, objective_code, evidence_id FROM generation.question_attempt "
            "WHERE request_id = ANY(%s)", (list(request_ids),))}
    slots = [{"slot": i + 1} for i in range(len(request_ids))]
    config = {"subject": "matematicas", "scope": "subject_simulation", "objective_codes": [], "difficulty": "mixed",
              "question_count": len(request_ids), "t072": uuid.uuid4().hex}
    allocation = [{"workbook_code": "M01", "text_es": "", "questions": len(slots), "slots": slots}]
    session, _ = store.create_or_get(f"t072-{uuid.uuid4().hex[:12]}", SYNTHETIC, config, allocation)
    picks = [{"slot": i + 1, "objective_code": rows[rid][1], "evidence_id": rows[rid][2], "item": rows[rid][0],
              "source": "bank", "source_request_id": rid} for i, rid in enumerate(request_ids)]
    store.add_bank_items(session["session_id"], picks, complete=True)
    return session["session_id"]


def report(client, session_id, slot=1, reason="wrong_answer", comment=None):
    return client.post(f"/api/practice/sessions/{session_id}/reports",
                       json={"slot": slot, "reason": reason, "comment": comment})


def verdicts(url):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT request_id, verdict, reason, reviewer FROM generation.bank_item_review "
                            "ORDER BY review_id").fetchall()


def report_rows(url):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT request_id, status, resolver FROM generation.question_report "
                            "ORDER BY report_id").fetchall()


def fingerprint(url):  # noqa: F811
    """Student history, verdicts and batch links: what reporting and resolving must never rewrite."""
    with psycopg.connect(url) as conn:
        return {
            "items": conn.execute("SELECT session_id, slot, item::text, source_request_id FROM practice.item "
                                  "ORDER BY 1, 2").fetchall(),
            "answers": conn.execute("SELECT session_id, slot, chosen_label, is_correct FROM practice.answer "
                                    "ORDER BY 1, 2").fetchall(),
            "sessions": conn.execute("SELECT session_id, status, slots_done FROM practice.session ORDER BY 1").fetchall(),
            "links": conn.execute("SELECT batch_id, cell, request_id, active FROM generation.bank_batch_item "
                                  "ORDER BY 1, 2, 3").fetchall()}


# ---------------------------------------------------------------- eligibility (ADR-038 D2)


def test_flag_parsing_defaults_off_and_refuses_unknown_values():
    assert auto_eligibility({}) is False
    assert auto_eligibility({AUTO: "on"}) is True and auto_eligibility({AUTO: " OFF "}) is False
    with pytest.raises(ValueError):
        auto_eligibility({AUTO: "yes"})


def test_flag_off_keeps_human_approval_required(bank, url, catalog_conn):  # noqa: F811
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    assert all(eligible(url, catalog_conn, c) == [] for c in cells)               # pending: never served
    seeding.item_review_record(url, batch_id, [{"request_id": cells[2], "verdict": "approved"}])
    assert [r["request_id"] for r in eligible(url, catalog_conn, 2)] == [cells[2]]


def test_flag_on_serves_validated_questions_without_a_verdict(bank, url, catalog_conn, monkeypatch):  # noqa: F811
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    before = verdicts(url)
    monkeypatch.setenv(AUTO, "on")
    assert all([r["request_id"] for r in eligible(url, catalog_conn, c)] == [cells[c]] for c in cells)
    assert verdicts(url) == before == []                                         # no approval was manufactured


def test_flag_on_still_excludes_quarantine_failed_batch_and_failed_validation(bank, url, catalog_conn,  # noqa: F811
                                                                              monkeypatch):
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    seeding.item_review_record(url, batch_id, [{"request_id": cells[1], "verdict": "approved"}])
    seeding.item_review_record(url, batch_id, [{"request_id": cells[2], "verdict": "quarantined",
                                                "reason": "wrong_key"}])
    with psycopg.connect(url) as conn:  # cell 3: outdated checker and no recorded rubric (missing evidence)
        conn.execute("UPDATE generation.question_attempt SET checker_version = 'checker-old', validation = '{}' "
                     "WHERE request_id = %s", (cells[3],))
        conn.execute("DELETE FROM generation.bank_revalidation WHERE request_id = %s", (cells[3],))
    monkeypatch.setenv(AUTO, "on")
    assert [r["request_id"] for r in eligible(url, catalog_conn, 1)] == [cells[1]]  # approved stays eligible
    assert eligible(url, catalog_conn, 2) == []                                     # quarantined
    assert eligible(url, catalog_conn, 3) == []                                     # validation gate not bypassed
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT eligible FROM generation.bank_revalidation WHERE request_id = %s AND "
                            "checker_version = %s", (cells[3], CHECKER_VERSION)).fetchone()[0] is False
        conn.execute("UPDATE generation.bank_batch SET review_status = 'failed' WHERE batch_id = %s", (batch_id,))
    assert all(eligible(url, catalog_conn, c) == [] for c in (4, 5, 6))             # failed batch review


def test_inventory_and_coverage_count_eligible_questions_once(bank, url, catalog_conn, monkeypatch):  # noqa: F811
    def totals():
        rows = replenishment.inventory(url, catalog_conn, SYNTHETIC, "matematicas")
        return sum(r["eligible"] for r in rows), sum(r["pending_review"] for r in rows)

    assert totals() == (0, 6)                                                    # flag off: held stock
    monkeypatch.setenv(AUTO, "on")
    assert totals() == (6, 0)                                                    # flag on: eligible, not pending


# ---------------------------------------------------------------- student reports (D3, D4)


def test_report_holds_the_question_and_leaks_nothing(bank, url, catalog_conn, synthetic_client,  # noqa: F811
                                                     monkeypatch):
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    monkeypatch.setenv(AUTO, "on")
    sid = practice(url, [cells[1], cells[2]])
    before = fingerprint(url)
    r = report(synthetic_client, sid, 1, "confusing", "  No entiendo el enunciado.  ")
    assert r.status_code == 200
    body = r.json()
    assert body == {"slot": 1, "reported": True, "already_reported": False,
                    "message_es": "Gracias. Tu tutor revisará esta pregunta.", "summary": None}  # slot 2 open
    assert eligible(url, catalog_conn, 1) == []                                  # held from new practices
    assert [x["request_id"] for x in eligible(url, catalog_conn, 2)] == [cells[2]]
    with psycopg.connect(url) as conn:
        row = conn.execute("SELECT request_id, item_id, content_sha256, session_id, slot, reason, comment, status "
                           "FROM generation.question_report").fetchone()
        item = conn.execute("SELECT item FROM practice.item WHERE session_id = %s AND slot = 1", (sid,)).fetchone()[0]
    assert row == (cells[1], item["item_id"], question_reports.content_sha256(item), sid, 1, "confusing",
                   "No entiendo el enunciado.", "open")
    assert fingerprint(url) == before                                            # practice and links unchanged
    assert synthetic_client.get(f"/api/practice/sessions/{sid}").status_code == 200  # the practice still works


def test_duplicate_and_concurrent_reports_store_one_row(bank, url, synthetic_client):  # noqa: F811
    _, batch_id = bank
    sid = practice(url, [by_cell(url, batch_id)[1]])
    assert report(synthetic_client, sid).json()["already_reported"] is False
    again = report(synthetic_client, sid, reason="other")
    assert again.status_code == 200 and again.json()["already_reported"] is True
    with ThreadPoolExecutor(4) as pool:
        codes = list(pool.map(lambda _: report(synthetic_client, sid).status_code, range(4)))
    assert codes == [200] * 4 and len(report_rows(url)) == 1


def answer(client, url, session_id, slot, correct=True):  # noqa: F811
    with psycopg.connect(url) as conn:
        key = conn.execute("SELECT item->>'answer_key' FROM practice.item WHERE session_id = %s AND slot = %s",
                           (session_id, slot)).fetchone()[0]
    label = key if correct else next(x for x in "ABCD" if x != key)
    r = client.post(f"/api/practice/sessions/{session_id}/answers", json={"slot": slot, "label": label})
    assert r.status_code == 200
    return r.json()


def test_a_question_reported_before_answering_is_skipped_and_not_scored(bank, url, synthetic_client):  # noqa: F811
    """T073 (RCA-009): reporting an unanswered question must not block the practice."""
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    sid = practice(url, [cells[1], cells[2]])
    report(synthetic_client, sid, 1)
    session = synthetic_client.get(f"/api/practice/sessions/{sid}").json()
    assert [(q["reported"], q["answered"]) for q in session["questions"]] == [(True, False), (False, False)]
    assert session["summary"] is None                                            # slot 2 still open
    result = answer(synthetic_client, url, sid, 2)["summary"]
    assert (result["answered"], result["correct"], result["skipped"], result["percentage"]) == (1, 1, 1, 100)
    assert synthetic_client.get(f"/api/practice/sessions/{sid}").json()["summary"] == result  # after a reload


def test_reporting_the_last_open_question_returns_the_result(bank, url, synthetic_client):  # noqa: F811
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    sid = practice(url, [cells[1], cells[2]])
    answer(synthetic_client, url, sid, 1, correct=False)
    result = report(synthetic_client, sid, 2).json()["summary"]
    assert (result["answered"], result["correct"], result["skipped"], result["percentage"]) == (1, 0, 1, 0)
    sid = practice(url, [cells[3]])
    result = report(synthetic_client, sid, 1).json()["summary"]                  # nothing answered at all
    assert (result["answered"], result["skipped"], result["percentage"], result["objectives"]) == (0, 1, None, [])


def test_a_question_reported_after_answering_keeps_its_score(bank, url, synthetic_client):  # noqa: F811
    _, batch_id = bank
    sid = practice(url, [by_cell(url, batch_id)[1]])
    scored = answer(synthetic_client, url, sid, 1)["summary"]
    assert report(synthetic_client, sid, 1).json()["summary"] == scored          # ADR-038: scores aren't rewritten
    assert scored["skipped"] == 0


def test_invalid_reports_are_refused(bank, url, synthetic_client, monkeypatch):  # noqa: F811
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    sid = practice(url, [cells[1], cells[2]])
    assert report(synthetic_client, "0" * 32).status_code == 404                  # unknown session
    assert report(synthetic_client, sid, slot=3).status_code == 404               # slot not in this practice
    assert report(synthetic_client, "not-a-session").status_code == 422           # malformed id
    assert report(synthetic_client, sid, slot=0).status_code == 422
    assert report(synthetic_client, sid, reason="spam").status_code == 422
    assert report(synthetic_client, sid, comment="x" * 301).status_code == 422    # oversized
    assert synthetic_client.post(f"/api/practice/sessions/{sid}/reports", content=b"{").status_code == 422
    assert report_rows(url) == []
    monkeypatch.setattr(question_reports, "DAILY_CAP", 1)                         # abuse bound
    assert report(synthetic_client, sid, 1).status_code == 200
    assert report(synthetic_client, sid, 2).status_code == 429 and len(report_rows(url)) == 1


def test_student_service_cannot_reach_tutor_operations(bank, url, synthetic_client):  # noqa: F811
    _, batch_id = bank
    rid = by_cell(url, batch_id)[1]
    assert synthetic_client.get(REPORTS).status_code == 404
    assert synthetic_client.post(f"{REPORTS}/{rid}/resolve", json={"action": "retain"}).status_code == 404
    assert synthetic_client.post("/api/tutor/review/bulk-approve", json={"request_ids": [rid]}).status_code == 404
    student = (STATIC_DIR / "index.html").read_text(encoding="utf-8") + (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "/api/tutor/reports" not in student


# ---------------------------------------------------------------- tutor resolution (D4)


def test_tutor_sees_reports_without_student_identity(bank, url, synthetic_client):  # noqa: F811
    app, batch_id = bank
    rid = by_cell(url, batch_id)[1]
    sid = practice(url, [rid])
    report(synthetic_client, sid, 1, "wrong_answer", "La B no da.")
    assert call(app, REPORTS, headers={}).status_code == 403                     # tutor token required
    out = call(app, REPORTS).json()
    assert out["open"] == 1 and out["auto_eligibility"] is False
    q = out["questions"][0]
    assert q["request_id"] == rid and q["answer_key"] and q["options"] and q["explanation"]
    assert q["validation"]["checker_verdict"] == "accept" and q["batch_id"] == batch_id
    assert q["used_in"] == {"sessions": 1, "answered": 0, "correct": 0}
    assert [(r["reason"], r["comment"], r["same_content"]) for r in q["reports"]] == [("wrong_answer", "La B no da.",
                                                                                       True)]
    assert sid not in str(out)                                                   # no student or session identity


def test_retain_clears_the_hold_without_a_verdict(bank, url, catalog_conn, synthetic_client,  # noqa: F811
                                                  monkeypatch):
    app, batch_id = bank
    rid = by_cell(url, batch_id)[1]
    monkeypatch.setenv(AUTO, "on")
    report(synthetic_client, practice(url, [rid]))
    report(synthetic_client, practice(url, [rid]), reason="display")             # two reports, one question
    assert eligible(url, catalog_conn, 1) == []
    before = fingerprint(url)
    out = call(app, f"{REPORTS}/{rid}/resolve", "POST", {"action": "retain", "comment": "Está bien."}).json()
    assert out == {"request_id": rid, "status": "retained", "reports": 2, "verdict_recorded": False, "open": 0}
    assert [r["request_id"] for r in eligible(url, catalog_conn, 1)] == [rid]    # eligible again
    assert verdicts(url) == []                                                   # no approval manufactured
    assert {(r[1], r[2]) for r in report_rows(url)} == {("retained", "tutor")}
    assert fingerprint(url) == before
    again = call(app, f"{REPORTS}/{rid}/resolve", "POST", {"action": "retain"})
    assert again.status_code == 409 and again.json()["error"] == "not_open"


def test_quarantine_records_one_verdict_and_reopens_the_cell(bank, url, catalog_conn,  # noqa: F811
                                                             synthetic_client, monkeypatch):
    app, batch_id = bank
    rid = by_cell(url, batch_id)[4]
    monkeypatch.setenv(AUTO, "on")
    report(synthetic_client, practice(url, [rid]))
    assert call(app, f"{REPORTS}/{rid}/resolve", "POST", {"action": "quarantine"}).status_code == 422  # reason needed
    out = call(app, f"{REPORTS}/{rid}/resolve", "POST",
               {"action": "quarantine", "reason": "wrong_key", "comment": "Clave equivocada."}).json()
    assert out["status"] == "quarantined" and out["verdict_recorded"] is True
    assert verdicts(url) == [(rid, "quarantined", "wrong_key", "tutor")]
    assert eligible(url, catalog_conn, 4) == []
    assert rid not in by_cell(url, batch_id).values()                            # link deactivated, cell reopens
    assert report_rows(url)[0][1] == "quarantined"


def test_simultaneous_resolutions_apply_once(bank, url, synthetic_client):  # noqa: F811
    app, batch_id = bank
    rid = by_cell(url, batch_id)[5]
    report(synthetic_client, practice(url, [rid]))
    body = {"action": "quarantine", "reason": "ambiguous"}
    with ThreadPoolExecutor(4) as pool:
        codes = sorted(pool.map(lambda _: call(app, f"{REPORTS}/{rid}/resolve", "POST", body).status_code, range(4)))
    assert codes == [200, 409, 409, 409]
    assert verdicts(url) == [(rid, "quarantined", "ambiguous", "tutor")]


def test_quarantine_of_an_already_quarantined_question_adds_no_second_verdict(bank, url,  # noqa: F811
                                                                              synthetic_client):
    app, batch_id = bank
    rid = by_cell(url, batch_id)[6]
    report(synthetic_client, practice(url, [rid]))
    seeding.quarantine(url, rid, "level")                                        # decided in the review first
    out = call(app, f"{REPORTS}/{rid}/resolve", "POST", {"action": "quarantine", "reason": "other"}).json()
    assert out["verdict_recorded"] is False and len(verdicts(url)) == 1


def test_tutor_app_mounts_the_reports_router():
    paths = {r.path for r in create_tutor_app("postgresql://unused/x", TOKEN, GATEWAY).routes}
    assert {REPORTS, f"{REPORTS}/{{request_id}}/resolve"} <= paths


# ---------------------------------------------------------------- workload bound (D5)


def test_schedule_settings_report_pause():
    assert ScheduleSettings.from_env({}).report_pause == 10
    assert ScheduleSettings.from_env({"MENTOR_PRO_REPORT_PAUSE": "3"}).report_pause == 3
    for bad in ("0", "1001", "x"):
        with pytest.raises(ScheduleError):
            ScheduleSettings.from_env({"MENTOR_PRO_REPORT_PAUSE": bad})


def test_ticks_skip_while_open_reports_reach_the_threshold(bank, url, synthetic_client):  # noqa: F811
    _, batch_id = bank
    cells = by_cell(url, batch_id)
    clean_schedule(url)
    settings = ScheduleSettings(enabled=True, tick_calls=10, report_pause=2)
    try:
        report(synthetic_client, practice(url, [cells[1]]))
        run = FakeRun()
        assert rs.tick(url, None, SYNTHETIC, lambda: None, replenishment.Policy(), settings, ("matematicas",), run=run)["status"] == "ok"
        report(synthetic_client, practice(url, [cells[2]]))
        run = FakeRun()
        out = rs.tick(url, None, SYNTHETIC, lambda: None, replenishment.Policy(), settings, ("matematicas",), run=run)
        assert (out["status"], out["reason"], run.seen) == ("skipped", "reports_open", [])
        status = rs.status(url, settings)
        assert (status["open_reports"], status["report_pause"]) == (2, 2)
        rs.set_paused(url, True, "manual")                                       # the manual pause still wins
        out = rs.tick(url, None, SYNTHETIC, lambda: None, replenishment.Policy(), settings, ("matematicas",), run=FakeRun())
        assert out["reason"] == "paused"
    finally:
        clean_schedule(url)


# ---------------------------------------------------------------- browser (opt-in)


def _serve(app):
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    return srv, thread, f"http://127.0.0.1:{port}"


@pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")
def test_student_reports_and_tutor_resolves_in_the_browser(bank, url, synthetic_client):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    tutor_app, batch_id = bank
    cells = by_cell(url, batch_id)
    sid = practice(url, [cells[1], cells[2]])
    shots = os.environ.get("MENTOR_PRO_SCREENSHOTS")
    student_srv, student_thread, student = _serve(synthetic_client.app)
    tutor_srv, tutor_thread, tutor = _serve(tutor_app)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.add_init_script(f"sessionStorage.setItem('mentorpro.session', '{sid}')")
            page.goto(student + "/")
            expect(page.locator("#quiz-position")).to_have_text("Pregunta 1 de 2")
            page.click("#report-open")
            expect(page.locator("#report-dialog")).to_be_visible()
            expect(page.locator("#report-send")).to_be_disabled()
            page.check("input[name=reason][value=missing_info]")
            page.fill("#report-comment", "Falta un dato.")
            page.click("#report-send")
            expect(page.locator("#report-done")).to_have_text("Gracias. Tu tutor revisará esta pregunta.")
            expect(page.locator("#report-open")).to_be_hidden()
            expect(page.locator("#quiz-stem")).to_be_visible()                   # practice not interrupted
            page.locator("#quiz-options .option").first.click()
            page.click("#answer-submit")
            expect(page.locator("#feedback")).to_be_visible()
            if shots:
                page.screenshot(path=os.path.join(shots, "student-report.png"), full_page=True)
            expect(page.locator("#report-skip")).to_be_hidden()                  # answered: "next" is the way on
            page.click("#next")                                                  # next question: can be reported
            expect(page.locator("#report-open")).to_be_visible()
            page.click("#report-open")                                           # T073: report without answering
            page.check("input[name=reason][value=confusing]")
            page.click("#report-send")
            expect(page.locator("#report-skip")).to_have_text("Ver resultados")
            page.click("#report-skip")
            expect(page.locator("#result-view")).to_be_visible()
            expect(page.locator("#result-skipped")).to_have_text("1 pregunta reportada no se calificó.")

            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(tutor + "/tutor")
            page.fill("#tutor-token", TOKEN)
            page.click("#tutor-enter")
            page.click("#tutor-nav-review")
            expect(page.locator("#reports-list .report-item")).to_have_count(2)  # T073 added the second report
            item = page.locator("#reports-list .report-item").filter(has_text="Falta información")
            expect(item).to_have_count(1)
            expect(item).to_contain_text("Falta información")
            expect(item).to_contain_text("«Falta un dato.»")
            expect(item.locator("li.review-key")).to_contain_text("Respuesta propuesta")
            expect(page.locator("#bulk-list .bulk-row")).to_have_count(6)       # T071 bulk review still there
            if shots:
                page.screenshot(path=os.path.join(shots, "tutor-reports.png"), full_page=True)
            item.locator(".report-retain").click()
            expect(page.locator("#reports-result")).to_contain_text("Pregunta mantenida")
            expect(page.locator("#reports-list .report-item")).to_have_count(1)
            browser.close()
        assert [(r[1], r[2]) for r in report_rows(url)] == [("retained", "tutor"), ("open", None)]
        assert verdicts(url) == []
    finally:
        student_srv.should_exit = tutor_srv.should_exit = True
        student_thread.join(timeout=10)
        tutor_thread.join(timeout=10)
