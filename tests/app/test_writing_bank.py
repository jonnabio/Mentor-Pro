"""Approved writing bank transfer (T032, ADR-031): export, checks, dry run, idempotent import, student flow."""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.writing import bank
from app.writing.store import WritingStore
from conftest import SYNTHETIC

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "scripts" / "dev" / "fixtures"
L1 = json.loads((FIXTURES / "writing-exercises-L1-T023.json").read_text(encoding="utf-8"))[0]
L2 = json.loads((FIXTURES / "writing-exercise-T021.json").read_text(encoding="utf-8"))
QUARANTINED = json.loads((FIXTURES / "writing-exercises-L1-T023.json").read_text(encoding="utf-8"))[1]
REFERENCE = {"corrected_text_es": "REFERENCIA-SOLO-TUTOR: texto corregido.",
             "corrections": [{"error": "las niños", "correction": "los niños", "criterion": "EE07"}],
             "ambiguities_es": []}
TOKEN = "tutor-test-token-0123456789"
BASELINE = L1["provenance"]["baseline_version"]


def _attempt(conn, exercise, request_id, generator="gen/model:free", reviewer="rev/model:free"):
    conn.execute(
        """INSERT INTO writing.generation_attempt (request_id, level, difficulty, target_criteria, status, exercise_id,
               models_used, calls, tokens_in, tokens_out, cost_usd, cost_complete, prompt_version, checks, reasons)
           VALUES (%s, %s, 'medium', %s, 'accepted', %s, %s, 2, 10, 10, 0, true, 'test', '[]', '[]')""",
        (request_id, exercise["level"], exercise["target_criteria"], exercise["exercise_id"], [generator, reviewer]))
    for purpose, model in (("generation", generator), ("review", reviewer)):
        conn.execute(
            """INSERT INTO llm.usage_record (call_id, request_id, purpose, attempt, is_fallback, model_requested,
                   model_used, tier, cost_source, latency_ms, status, started_at)
               VALUES (%s, %s, %s, 1, false, %s, %s, 'free', 'missing', 1, 'ok', now())""",
            (f"call-{uuid.uuid4().hex}", request_id, purpose, model, model))


@pytest.fixture()
def env(synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    cat = f"bankcat_{uuid.uuid4().hex[:8]}"
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
        conn.execute(f"CREATE SCHEMA {cat}")
        conn.execute(f"CREATE TABLE {cat}.assertion (baseline_version TEXT)")
        conn.execute(f"INSERT INTO {cat}.assertion VALUES (%s)", (BASELINE,))
    store = WritingStore(url)
    from app.llm.usage import UsageStore
    UsageStore(url)
    store.add_exercise(L1, generation_request_id=f"wreq-l1-{tag}", reference=REFERENCE)
    store.add_exercise(L2, generation_request_id=f"wreq-l2-{tag}")
    store.add_exercise(QUARANTINED, generation_request_id=f"wreq-q-{tag}")
    with psycopg.connect(url, autocommit=True) as conn:
        _attempt(conn, L1, f"wreq-l1-{tag}")
        _attempt(conn, L2, f"wreq-l2-{tag}")
        _attempt(conn, QUARANTINED, f"wreq-q-{tag}", reviewer="gen/model:free")
    store.set_eligibility(QUARANTINED["exercise_id"], "quarantined", "self review", "RCA-004")
    exported = bank.export_bank(url)

    def reset_destination():
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
            conn.execute("DELETE FROM llm.usage_record WHERE request_id LIKE %s", (f"%{tag}",))
        return WritingStore(url)

    yield exported, reset_destination, url, schema, cat
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
        conn.execute(f"DROP SCHEMA IF EXISTS {cat} CASCADE")
        conn.execute("DELETE FROM llm.usage_record WHERE request_id LIKE %s", (f"%{tag}",))


def ids(items):
    return sorted(i["exercise_id"] if isinstance(i, dict) else i for i in items)


def test_export_leaves_out_quarantined_and_student_records(env):
    exported, *_ = env
    assert ids(i["exercise"] for i in exported["exercises"]) == ids([L1, L2])
    assert exported["skipped"] == [{"exercise_id": QUARANTINED["exercise_id"], "reason": "quarantined"}]
    text = json.dumps(exported)
    assert '"client_seq"' not in text and '"submission_id"' not in text
    l1 = next(i for i in exported["exercises"] if i["exercise"]["exercise_id"] == L1["exercise_id"])
    assert l1["reference_correction"]["corrected_text_es"] == REFERENCE["corrected_text_es"]
    assert {u["purpose"] for u in l1["usage"]} == {"generation", "review"}


def test_dry_run_writes_nothing_then_import_is_repeatable(env):
    exported, reset, url, _, cat = env
    store = reset()
    dry = bank.import_or_dry_run(url, exported, dry_run=True, catalog_schema=cat)
    assert ids(dry["imported"]) == ids([L1, L2]) and dry["rejected"] == []
    assert store.exercises(eligible_only=False) == []
    first = bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    assert ids(first["imported"]) == ids([L1, L2]) and first["student_records_untouched"]
    again = bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    assert again["imported"] == [] and ids(again["unchanged"]) == ids([L1, L2]) and again["rejected"] == []
    assert ids(r["exercise_id"] for r in store.exercises()) == ids([L1, L2])
    assert store.reference_correction(L1["exercise_id"])["corrected_text_es"] == REFERENCE["corrected_text_es"]
    from app.writing import revalidation
    assert revalidation.self_reviewed(url) == []  # RCA-004 evidence travelled with the exercises


def test_import_never_touches_existing_student_work(env):
    exported, reset, url, _, cat = env
    store = reset()
    store.add_exercise(L2, generation_request_id="local")
    store.save_draft(L2["exercise_id"], "Mi borrador.", client_seq=1)
    store.submit_typed(L2["exercise_id"], "Mi texto entregado.", "req-bank-0002")
    report = bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    assert ids(report["imported"]) == [L1["exercise_id"]] and ids(report["unchanged"]) == [L2["exercise_id"]]
    assert report["counts_before"]["submission"] == report["counts_after"]["submission"] == 1
    assert store.submission(L2["exercise_id"])["text_es"] == "Mi texto entregado."


def test_inconsistent_records_are_rejected(env):
    exported, reset, url, _, cat = env
    reset()
    bad = copy.deepcopy(exported)
    l1, l2 = sorted(bad["exercises"], key=lambda i: i["exercise"]["level"] != "writing_conventions")
    l1["reference_correction"] = None
    for u in l2["usage"]:
        u["model_used"] = "gen/model:free"  # reviewer == generator
    report = bank.import_or_dry_run(url, bad, dry_run=False, catalog_schema=cat)
    assert report["imported"] == []
    problems = {r["exercise_id"]: " ".join(r["problems"]) for r in report["rejected"]}
    assert "reference correction missing" in problems[L1["exercise_id"]]
    assert "no independent review" in problems[L2["exercise_id"]]
    changed = copy.deepcopy(exported)
    bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    changed["exercises"][0]["exercise"]["record"]["topic_es"] = "Otro tema"
    report = bank.import_or_dry_run(url, changed, dry_run=False, catalog_schema=cat)
    assert "never overwritten" in report["rejected"][0]["problems"][0]


def test_missing_baseline_is_rejected(env):
    exported, reset, url, _, cat = env
    reset()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"DELETE FROM {cat}.assertion")
    report = bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    assert report["imported"] == [] and all("baseline" in " ".join(r["problems"]) for r in report["rejected"])


def test_imported_exercise_completes_the_student_and_tutor_workflow(env):
    exported, reset, url, schema, cat = env
    reset()
    bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    app = TestClient(create_app(url, schema, SYNTHETIC, tutor_token=TOKEN, tutor_hosts=frozenset({"testclient"})))
    levels = {lv["code"]: lv["exercise_count"] for lv in app.get("/api/writing/levels").json()["levels"]}
    assert levels["writing_conventions"] == 1 and levels["idea_development"] == 1
    l1 = L1["exercise_id"]
    view = app.get(f"/api/writing/exercises/{l1}").json()
    assert "REFERENCIA-SOLO-TUTOR" not in json.dumps(view, ensure_ascii=False)
    assert app.get(f"/api/writing/exercises/{QUARANTINED['exercise_id']}").status_code == 404
    assert app.put(f"/api/writing/exercises/{l1}/draft", json={"text": "Borrador", "client_seq": 1}).status_code == 200
    sub = app.post(f"/api/writing/exercises/{l1}/submit",
                   json={"text": "Los niños juegan.", "client_request_id": "req-bank-0001"})
    assert sub.status_code in (200, 201)
    assert app.get("/api/tutor/queue").status_code == 403
    queue = app.get("/api/tutor/queue", headers={"X-Tutor-Token": TOKEN}).json()["submissions"]
    scores = {c: 3 for c in L1["target_criteria"]}
    saved = app.put(f"/api/tutor/submissions/{queue[0]['submission_id']}/evaluation",
                    headers={"X-Tutor-Token": TOKEN},
                    json={"scores": scores, "strengths": ["Buena puntuación."], "complete": True})
    assert saved.json()["status"] == "completed"
    fresh = TestClient(create_app(url, schema, SYNTHETIC))  # a new process reads the same database
    feedback = json.dumps(fresh.get(f"/api/writing/exercises/{l1}").json(), ensure_ascii=False)
    assert "Buena puntuación." in feedback


def test_reinstated_exercise_keeps_its_history_and_validation(env, synthetic_client):
    """A self-reviewed exercise reinstated by a passed independent validation (ADR-027) travels with its events."""
    _, reset, url, _, cat = env
    store = reset()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DELETE FROM llm.usage_record WHERE request_id = 'wreq-re-x'")
    store.add_exercise(QUARANTINED, generation_request_id="wreq-re-x", reference=REFERENCE)
    with psycopg.connect(url, autocommit=True) as conn:
        _attempt(conn, QUARANTINED, "wreq-re-x", reviewer="gen/model:free")
    store.set_eligibility(QUARANTINED["exercise_id"], "quarantined", "self review", "RCA-004")
    store.add_validation({"validation_id": "IV-test-1", "exercise_id": QUARANTINED["exercise_id"],
                          "exercise_revision": 1, "version": "t", "status": "passed",
                          "generator_model": "gen/model:free", "reviewer_model": "rev/model:free", "checks": [],
                          "review": None, "reasons": [], "request_id": "wreq-re-v", "calls": 1, "tokens_in": 1,
                          "tokens_out": 1, "cost_usd": 0, "cost_complete": True})
    store.set_eligibility(QUARANTINED["exercise_id"], "eligible", "independent review passed", "RCA-004",
                          "IV-test-1")
    exported = bank.export_bank(url)
    reset()
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DELETE FROM llm.usage_record WHERE request_id = 'wreq-re-x'")
    report = bank.import_or_dry_run(url, exported, dry_run=False, catalog_schema=cat)
    assert ids(report["imported"]) == [QUARANTINED["exercise_id"]], report["rejected"]
    events = WritingStore(url).eligibility_events(QUARANTINED["exercise_id"])
    assert [e["status"] for e in events] == ["quarantined", "eligible"] and events[-1]["validation_id"] == "IV-test-1"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DELETE FROM llm.usage_record WHERE request_id = 'wreq-re-x'")
