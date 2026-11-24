"""T071 enhancement: "Seleccionar todas las pendientes" approves every pending question of the applied filters.

Frontend only: the selection spans every page of `GET /api/tutor/review/queue` (page_size 50), is revalidated against
the live queue when the tutor confirms, and is sent to the existing `POST /api/tutor/review/bulk-approve` in
sequential batches of at most BULK_MAX IDs. Two browser regressions (opt-in, MENTOR_PRO_BROWSER=1, as in CI):

- against the real tutor app and database (six seeded questions): cross-page selection, filters, cancellation,
  revalidation and the audit rows;
- against a scripted queue (Playwright routes in front of the same page): queue sizes 0, 10, 33, 50, 51 and 120,
  batch bounds, a failed batch that is never resent, and questions added after the selection.
"""

from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlparse

import pytest

from app.practice import seeding
from app.practice.tutor_review import BULK_MAX
from test_bank_seeding import url  # noqa: F401  (fixture)
from test_generation import catalog_conn  # noqa: F401  (fixture)
from test_tutor_bulk_approve import all_reviews, server, six  # noqa: F401  (fixtures)
from test_tutor_review import TOKEN

browser_only = pytest.mark.skipif(not os.environ.get("MENTOR_PRO_BROWSER"), reason="set MENTOR_PRO_BROWSER=1")


def enter(page, base):
    page.goto(base)
    page.fill("#tutor-token", TOKEN)
    page.click("#tutor-enter")
    page.click("#tutor-nav-review")


def test_the_frontend_batch_size_matches_the_api_limit():
    js = open(os.path.join(os.path.dirname(__file__), "..", "..", "app", "static", "tutor.js"), encoding="utf-8").read()
    assert f"const BULK_MAX = {BULK_MAX};" in js


# ---------------------------------------------------------------- real tutor app and database


@browser_only
def test_select_all_pending_across_pages_with_the_real_queue(server, url):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, batch_id = server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.add_init_script("window.__bulkPageSize = 4")
        posts = []
        page.on("request", lambda r: posts.append(r.post_data) if r.url.endswith("/bulk-approve") else None)
        enter(page, base)
        expect(page.locator("#bulk-page")).to_contain_text("Página 1 de 2 · 6 por revisar")
        expect(page.locator("#bulk-select-all")).to_have_text("Seleccionar todas las pendientes (6)")

        page.click("#bulk-select-all")                                       # all pages, nothing sent
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (6)")
        expect(page.locator("#bulk-scope")).to_contain_text("todas las materias, sin filtros")
        page.click("#bulk-next")                                             # the selection spans pages
        expect(page.locator("#bulk-list .bulk-row")).to_have_count(2)
        expect(page.locator("#bulk-list .bulk-check:checked")).to_have_count(2)
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (6)")
        page.locator("#bulk-list .bulk-check").nth(0).uncheck()              # individual changes still apply
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (5)")
        page.locator("#bulk-list .bulk-check").nth(0).check()
        page.click("#bulk-prev")
        expect(page.locator("#bulk-list .bulk-check:checked")).to_have_count(4)

        page.click("#bulk-approve")                                          # cancelled: nothing recorded
        expect(page.locator("#bulk-dialog")).to_be_visible()
        expect(page.locator("#bulk-dialog-message")).to_have_text("¿Aprobar 6 preguntas?")
        expect(page.locator("#bulk-dialog-subjects")).to_contain_text("Matemáticas")
        expect(page.locator("#bulk-dialog")).to_contain_text("decisiones reales de aprobación del tutor")
        page.click("#bulk-dialog-cancel")
        expect(page.locator("#bulk-dialog")).to_be_hidden()
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog")).to_be_visible()                 # after the revalidation
        page.keyboard.press("Escape")                                        # Escape cancels too
        expect(page.locator("#bulk-dialog")).to_be_hidden()
        assert all_reviews(url) == [] and posts == []
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (6)")

        page.select_option("#rf-difficulty", "hard")                         # filters bound the selection
        page.click("#review-filters button[type=submit]")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        expect(page.locator("#bulk-select-all")).to_have_text("Seleccionar todas las pendientes (2)")
        page.click("#bulk-select-all")
        expect(page.locator("#bulk-scope")).to_contain_text("solo las preguntas filtradas (dificultad Difícil)")
        page.click("#bulk-clear")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        expect(page.locator("#bulk-scope")).to_have_text("")
        page.click("#rf-clear")
        expect(page.locator("#bulk-select-all")).to_have_text("Seleccionar todas las pendientes (6)")

        page.click("#bulk-select-all")
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (6)")
        # Decided elsewhere after the selection: revalidation drops it before the dialog; nothing is resent.
        taken = page.locator("#bulk-list .bulk-row").nth(1).get_attribute("data-request")
        seeding.item_review_record(url, batch_id, [{"request_id": taken, "verdict": "approved"}])
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog-message")).to_have_text("¿Aprobar 5 preguntas?")
        expect(page.locator("#bulk-dialog-dropped")).to_have_text(
            "1 de las seleccionadas ya no están pendientes y no se enviarán.")
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_have_text("Se aprobaron 5 de 5 preguntas. Quedan 0 por revisar.",
                                                          timeout=60_000)  # five real locked transactions
        assert len(posts) == 1 and taken not in posts[0] and len(json.loads(posts[0])["request_ids"]) == 5
        rows = all_reviews(url)
        assert len(rows) == 6 and {(r[1], r[2], r[3]) for r in rows} == {("approved", "approved", "tutor")}
        browser.close()


# ---------------------------------------------------------------- scripted queue


class FakeQueue:
    """The queue and bulk-approve contract (tutor_review.py), in memory, recording every approval request."""

    SUBJECTS = ("matematicas", "ciencias", "espanol")
    NAMES = {"matematicas": "Matemáticas", "ciencias": "Ciencias", "espanol": "Español"}

    def __init__(self, n, fail_batch=None):
        self.pending = [self.question(i) for i in range(n)]
        self.posts, self.fail_batch, self.next_id = [], fail_batch, n

    def question(self, i):
        return {"request_id": f"req-{i:04d}", "subject": self.SUBJECTS[i % 3], "batch_id": "bb-1", "cell": i + 1,
                "objective_code": "M01", "objective_es": "Objetivo", "evidencia_es": "", "difficulty": "easy",
                "stimulus": {"type": "none"}, "stem": f"Pregunta {i}", "answer_key": "A", "explanation": "",
                "options": [{"label": "A", "text": "1"}, {"label": "B", "text": "2"}]}

    def add(self, k):
        self.pending += [self.question(self.next_id + j) for j in range(k)]
        self.next_id += k

    def handle(self, route):
        req = route.request
        if req.method == "POST":
            ids = json.loads(req.post_data)["request_ids"]
            self.posts.append(ids)
            assert len(ids) <= BULK_MAX and len(set(ids)) == len(ids)
            if self.fail_batch == len(self.posts):
                return route.fulfill(status=500, content_type="application/json",
                                     body=json.dumps({"error": {"message": "fallo simulado"}}))
            live = {q["request_id"] for q in self.pending}
            results = [{"request_id": i, "status": "approved" if i in live else "not_pending"} for i in ids]
            self.pending = [q for q in self.pending if q["request_id"] not in ids]
            ok = sum(r["status"] == "approved" for r in results)
            body = {"requested": len(ids), "approved": ok, "failed": len(ids) - ok, "results": results,
                    "counts": self.counts()}
            return route.fulfill(content_type="application/json", body=json.dumps(body))
        q = parse_qs(urlparse(req.url).query)
        rows = [r for r in self.pending if r["subject"] == q["subject"][0]] if "subject" in q else list(self.pending)
        body = {"counts": self.counts(), "reasons": list(seeding.REASONS), "total": len(rows),
                "auto_eligibility": False}
        if "page" in q or "page_size" in q:
            size = int(q.get("page_size", ["10"])[0])
            assert size <= BULK_MAX
            pages = max(1, -(-len(rows) // size))
            current = min(int(q.get("page", ["1"])[0]), pages)
            rows = rows[(current - 1) * size:current * size]
            body["pagination"] = {"page": current, "page_size": size, "pages": pages}
        route.fulfill(content_type="application/json", body=json.dumps({"questions": rows, **body}))

    def counts(self):
        return [{"subject": s, "name_es": self.NAMES[s], "pending": sum(q["subject"] == s for q in self.pending),
                 "approved": 0, "quarantined": 0} for s in self.SUBJECTS]


def scripted(p, base, fake):
    browser = p.chromium.launch()
    page = browser.new_page()
    page.route("**/api/tutor/review/queue*", fake.handle)
    page.route("**/api/tutor/review/bulk-approve", fake.handle)
    enter(page, base)
    return browser, page


@browser_only
@pytest.mark.parametrize("n", [0, 10, 33, 50, 51, 120])
def test_approve_all_queue_sizes_in_bounded_batches(server, n):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    fake = FakeQueue(n)
    with sync_playwright() as p:
        browser, page = scripted(p, base, fake)
        if n == 0:
            expect(page.locator("#bulk")).to_be_hidden()
            assert fake.posts == []
            return browser.close()
        expect(page.locator("#bulk-select-all")).to_have_text(f"Seleccionar todas las pendientes ({n})")
        page.click("#bulk-select-all")
        expect(page.locator("#bulk-approve")).to_have_text(f"Aprobar seleccionadas ({n})")
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog-message")).to_have_text(f"¿Aprobar {n} preguntas?")
        expect(page.locator("#bulk-dialog-subjects")).to_have_text("Materias: Matemáticas, Ciencias, Español.")
        assert fake.posts == []                                              # nothing before the confirmation
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_have_text(f"Se aprobaron {n} de {n} preguntas. Quedan 0 por revisar.")
        assert [len(b) for b in fake.posts] == [min(BULK_MAX, n - i) for i in range(0, n, BULK_MAX)]
        sent = [i for b in fake.posts for i in b]
        assert len(sent) == len(set(sent)) == n and fake.pending == []
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (0)")
        browser.close()


@browser_only
def test_a_failed_batch_stops_without_resending_and_reports_what_remains(server):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    fake = FakeQueue(120, fail_batch=2)
    with sync_playwright() as p:
        browser, page = scripted(p, base, fake)
        page.click("#bulk-select-all")
        page.click("#bulk-approve")
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_contain_text("Se aprobaron 50 de 120 preguntas.")
        expect(page.locator("#bulk-result")).to_contain_text("): 50; pudieron aprobarse o no")
        expect(page.locator("#bulk-result")).to_contain_text("no se reintentaron")
        expect(page.locator("#bulk-result")).to_contain_text(
            "Sin enviar: 20; no se intentaron y siguen pendientes. Quedan 70 por revisar.")
        assert [len(b) for b in fake.posts] == [50, 50]                      # the third batch is never sent
        assert len(fake.pending) == 70
        page.click("#bulk-select-all")                                       # a retry sends only what is left
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog-message")).to_have_text("¿Aprobar 70 preguntas?")
        fake.fail_batch = None
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_have_text("Se aprobaron 70 de 70 preguntas. Quedan 0 por revisar.")
        sent = [i for b in fake.posts[2:] for i in b]
        assert set(sent).isdisjoint(fake.posts[0]) and len(sent) == 70
        browser.close()


@browser_only
def test_a_failed_last_batch_is_unconfirmed_with_nothing_unsent(server):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    fake = FakeQueue(60, fail_batch=2)
    with sync_playwright() as p:
        browser, page = scripted(p, base, fake)
        page.click("#bulk-select-all")
        page.click("#bulk-approve")
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_contain_text("Se aprobaron 50 de 60 preguntas.")
        expect(page.locator("#bulk-result")).to_contain_text("): 10; pudieron aprobarse o no")
        expect(page.locator("#bulk-result")).not_to_contain_text("Sin enviar")
        expect(page.locator("#bulk-result")).to_contain_text("Quedan 10 por revisar.")  # the queue was refreshed
        assert [len(b) for b in fake.posts] == [50, 10]                      # the failed batch is not retried
        browser.close()


@browser_only
def test_questions_added_after_the_selection_are_not_approved(server):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    fake = FakeQueue(33)
    with sync_playwright() as p:
        browser, page = scripted(p, base, fake)
        page.click("#bulk-select-all")
        fake.add(5)                                                          # new pending questions arrive
        fake.pending = fake.pending[2:]                                      # two are decided elsewhere
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog-message")).to_have_text("¿Aprobar 31 preguntas?")
        expect(page.locator("#bulk-dialog-dropped")).to_contain_text("2 de las seleccionadas ya no están pendientes")
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_have_text("Se aprobaron 31 de 31 preguntas. Quedan 5 por revisar.")
        assert {q["request_id"] for q in fake.pending} == {f"req-{i:04d}" for i in range(33, 38)}
        browser.close()


@browser_only
def test_filtered_selection_and_page_selection_stay_bounded(server):  # noqa: F811
    from playwright.sync_api import expect, sync_playwright

    base, _ = server
    fake = FakeQueue(33)
    with sync_playwright() as p:
        browser, page = scripted(p, base, fake)
        page.select_option("#rf-subject", "ciencias")
        page.click("#review-filters button[type=submit]")
        expect(page.locator("#bulk-select-all")).to_have_text("Seleccionar todas las pendientes (11)")
        page.click("#bulk-select-all")
        page.click("#bulk-approve")
        expect(page.locator("#bulk-dialog-subjects")).to_have_text("Materias: Ciencias.")
        expect(page.locator("#bulk-dialog-scope")).to_contain_text("solo las preguntas filtradas (materia Ciencias)")
        page.click("#bulk-dialog-confirm")
        expect(page.locator("#bulk-result")).to_contain_text("Se aprobaron 11 de 11 preguntas.")
        assert {q["subject"] for q in fake.pending} == {"matematicas", "espanol"} and len(fake.pending) == 22
        page.click("#rf-clear")
        page.click("#bulk-select-page")                                      # the page selection is unchanged
        expect(page.locator("#bulk-approve")).to_have_text("Aprobar seleccionadas (10)")
        page.once("dialog", lambda d: d.accept())
        page.click("#bulk-approve")
        expect(page.locator("#bulk-result")).to_contain_text("Se aprobaron 10 de 10 preguntas. Quedan 12 por revisar.")
        assert [len(b) for b in fake.posts] == [11, 10]
        browser.close()
