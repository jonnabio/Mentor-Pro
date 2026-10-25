"""Producción escrita in "Mi progreso" (T027, ADR-025): scores only from completed tutor evaluations."""

from __future__ import annotations

import copy

import psycopg
from fastapi.testclient import TestClient

from app.main import create_app
from app.writing import contracts, progress
from conftest import SYNTHETIC
from test_writing_tutor import HEADERS, L1, L23, TOKEN, env, sid_for, submit  # noqa: F401  (env is a fixture)

ALL = [f"EE{n:02d}" for n in range(1, 21)]


def complete(student, sid, scores):
    response = student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": scores, "complete": True},
                           headers=HEADERS)
    assert response.json()["status"] == "completed"


def rows(data):
    return {r["code"]: r for r in data["criteria"]}


def dims(data):
    return {d["ordinal"]: d for d in data["dimensions"]}


def typed_guided(store):
    """A typed L4 exercise whose EE19 is not evaluable (handwriting)."""
    guided = copy.deepcopy(L23["introduction_paragraph"])
    codes = ["EE01", "EE02", "EE03", "EE04", "EE05", "EE06", "EE19"]
    guided.update(exercise_id="PE-L4-guiada-prueba-0001", level="guided_composition",
                  exercise_type="guided_composition", target_criteria=codes)
    guided["deliverable"].update(unit="paragraphs", min=4, max=4, words_target=200, evidence_mode="typed")
    guided["evaluation"]["parameters"] = [
        {"criterion": c, "rubric_ref": f"MEP-RUBRICA-PE-2026#{c}", "applicability": "scored"} if c != "EE19" else
        {"criterion": c, "rubric_ref": f"MEP-RUBRICA-PE-2026#{c}", "applicability": "not_evaluable",
         "not_evaluable_reason": "handwritten_evidence_required"} for c in codes]
    rubric = contracts.criteria()
    guided["provenance"]["curriculum_records"] = [
        {"workbook_code": c,
         "assertion_id": f"PNE2026-PRI-ESP-PE-B{rubric[c]['dimension']}-A{rubric[c]['rubric_number']}"}
        for c in codes]
    store.add_exercise(guided)
    return guided


def test_empty_progress_lists_all_twenty_criteria_unassessed(env):
    student, _, _ = env
    data = student.get("/api/writing/progress").json()
    assert [r["code"] for r in data["criteria"]] == ALL
    for r in data["criteria"]:
        official = contracts.criteria()[r["code"]]
        assert r["statement_es"] == official["statement_es"] and r["dimension"] == official["dimension"]
        assert (r["status"], r["status_es"], r["latest_points"], r["best_points"]) == ("unassessed", "Sin evaluar",
                                                                                       None, None)
    assert data["coverage"] == {"total": 20, "evaluated": 0, "pending": 0, "unassessed": 20}
    assert [d["average_latest_points"] for d in data["dimensions"]] == [None] * 5
    assert [d["criteria_codes"] for d in data["dimensions"]] == [
        ["EE01", "EE02"], ["EE03"], ["EE04", "EE05", "EE06"], [f"EE{n:02d}" for n in range(7, 19)], ["EE19", "EE20"]]
    activity = data["activity"]
    assert (activity["submitted"], activity["evaluations_completed"], activity["evaluations_pending"],
            activity["last_practice_at"]) == (0, 0, 0, None)
    assert [lv["ordinal"] for lv in activity["levels"]] == [1, 2, 3, 4, 5]
    assert "no son una calificación oficial" in data["notice_es"]


def test_pending_then_completed_l1_updates_only_its_criteria(env):
    student, _, _ = env
    sid = sid_for(submit(student, L1["exercise_id"]), L1["exercise_id"])
    pending = student.get("/api/writing/progress").json()
    r = rows(pending)
    assert {c for c, v in r.items() if v["status"] == "pending"} == {"EE07", "EE08"}
    assert all(v["latest_points"] is None and v["evaluations"] == 0 for v in r.values())
    assert pending["coverage"] == {"total": 20, "evaluated": 0, "pending": 2, "unassessed": 18}
    assert (pending["activity"]["submitted"], pending["activity"]["evaluations_pending"]) == (1, 1)
    assert pending["activity"]["last_practice_at"] is not None
    assert dims(pending)[4]["average_latest_points"] is None  # pending evaluations give no score

    # A partial (in_progress) evaluation is still not a score.
    student.put(f"/api/tutor/submissions/{sid}/evaluation", json={"scores": {"EE07": 4}}, headers=HEADERS)
    assert rows(student.get("/api/writing/progress").json())["EE07"]["latest_points"] is None

    complete(student, sid, {"EE07": 3, "EE08": 2})
    data = student.get("/api/writing/progress").json()
    r = rows(data)
    assert {c for c, v in r.items() if v["status"] == "evaluated"} == {"EE07", "EE08"}
    assert (r["EE07"]["latest_points"], r["EE07"]["best_points"], r["EE07"]["evaluations"]) == (3, 3, 1)
    assert (r["EE08"]["latest_points"], r["EE08"]["best_points"]) == (2, 2) and r["EE08"]["status_es"] == "Evaluado"
    assert r["EE07"]["latest_at"] and all(v["status"] == "unassessed" for c, v in r.items() if c not in ("EE07", "EE08"))
    d = dims(data)
    assert (d[4]["average_latest_points"], d[4]["criteria_with_evidence"], d[4]["criteria"]) == (2.5, 2, 12)
    assert all(d[n]["average_latest_points"] is None for n in (1, 2, 3, 5))
    level1 = data["activity"]["levels"][0]
    assert (level1["submitted"], level1["evaluated"]) == (1, 1)
    assert (data["activity"]["evaluations_completed"], data["activity"]["evaluations_pending"]) == (1, 0)


def test_latest_and_best_scores_follow_evaluation_dates():
    base = {"status": "completed", "criterion_scores": []}
    evaluations = [
        {**base, "evaluated_at": "2026-10-20T10:00:00-06:00",
         "criterion_scores": [{"criterion": "EE07", "status": "scored", "points": 4}]},
        {**base, "evaluated_at": "2026-10-24T10:00:00-06:00",
         "criterion_scores": [{"criterion": "EE07", "status": "scored", "points": 1},
                              {"criterion": "EE09", "status": "scored", "points": 2}]},
        {**base, "evaluated_at": "2026-10-22T10:00:00-06:00",
         "criterion_scores": [{"criterion": "EE07", "status": "scored", "points": 3}]},
        {**base, "status": "in_progress", "evaluated_at": None,
         "criterion_scores": [{"criterion": "EE07", "status": "scored", "points": 0}]},
    ]
    data = progress.summary(evaluations)
    r = rows(data)
    assert (r["EE07"]["latest_points"], r["EE07"]["best_points"], r["EE07"]["evaluations"],
            r["EE07"]["latest_at"]) == (1, 4, 3, "2026-10-24T10:00:00-06:00")
    assert dims(data)[4]["average_latest_points"] == 1.5  # (1 + 2) / 2 evaluated criteria, not / 12


def test_dimension_average_excludes_unassessed_and_not_evaluable_criteria(env):
    student, store, _ = env
    guided = typed_guided(store)
    sid = sid_for(submit(student, guided["exercise_id"]), guided["exercise_id"])
    r = rows(student.get("/api/writing/progress").json())
    assert r["EE19"]["status"] == "unassessed" and r["EE19"]["pending"] == 0  # not scorable on typed work
    complete(student, sid, {"EE01": 4, "EE02": 2, "EE03": 3, "EE04": 1, "EE05": 2, "EE06": 3})
    data = student.get("/api/writing/progress").json()
    r, d = rows(data), dims(data)
    assert (r["EE19"]["status"], r["EE19"]["latest_points"], r["EE19"]["not_evaluable"]) == ("unassessed", None, 1)
    assert r["EE20"]["not_evaluable"] == 0 and r["EE20"]["status"] == "unassessed"
    assert d[1]["average_latest_points"] == 3 and d[3]["average_latest_points"] == 2
    assert d[5]["average_latest_points"] is None and d[5]["criteria_with_evidence"] == 0
    assert data["coverage"] == {"total": 20, "evaluated": 6, "pending": 0, "unassessed": 14}
    assert data["activity"]["levels"][3]["evaluated"] == 1


def test_completed_evaluation_survives_a_new_app_and_reads_write_nothing(env, synthetic_client):
    student, _, url = env
    complete(student, sid_for(submit(student, L1["exercise_id"]), L1["exercise_id"]), {"EE07": 4, "EE08": 4})
    first = student.get("/api/writing/progress").json()
    url_, schema = synthetic_client.app.state.catalog_target
    fresh = TestClient(create_app(url_, schema, SYNTHETIC, tutor_token=TOKEN))
    assert fresh.get("/api/writing/progress").json() == first
    with psycopg.connect(url) as conn:
        counts = [conn.execute(f"SELECT COUNT(*) FROM writing.{t}").fetchone()[0]
                  for t in ("draft", "submission", "evaluation", "criterion_score")]
    assert counts == [1, 1, 1, 2]  # history kept; the progress reads changed nothing


def test_multiple_choice_dashboard_is_unchanged_by_writing(env):
    student, _, _ = env
    before = student.get("/api/dashboard").json()
    complete(student, sid_for(submit(student, L1["exercise_id"]), L1["exercise_id"]), {"EE07": 1, "EE08": 1})
    after = student.get("/api/dashboard").json()
    assert after == before
    assert [s["subject"] for s in after["subjects"]] == ["espanol", "matematicas", "ciencias", "estudios_sociales"]
    assert "EE07" not in str(after)
