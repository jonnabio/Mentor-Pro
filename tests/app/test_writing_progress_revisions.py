"""Writing progress with revisions (T039, ADR-032): exercises counted once, improvements apart, comparison."""

from __future__ import annotations

import psycopg

from app.writing import contracts, progress
from test_writing_progress import rows
from test_writing_revision_api import L2, review, reviewed
from test_writing_tutor import HEADERS, L1, env, submit  # noqa: F401  (env is a fixture)
from test_writing_tutor_revision import revise

RUBRIC = {"rubric_id": contracts.rubric()["rubric_id"], "rubric_sha256": contracts.rubric()["source"]["file_sha256"]}


def evaluation(scores, at="2026-10-20T10:00:00-06:00", status="completed", **change):
    """scores: code -> points, or "ne" for not evaluable."""
    record = {**RUBRIC, "status": status, "evaluated_at": at, "criterion_scores": [
        {"criterion": c, "status": "not_evaluable"} if p == "ne" else {"criterion": c, "status": "scored", "points": p}
        for c, p in scores.items()]}
    record.update(change)
    return record


def version(scores, revision=1, **change):
    return {"exercise_revision": revision, "evaluation": None if scores is None else evaluation(scores, **change)}


def by_code(result):
    return {r["code"]: r for r in result["criteria"]}


# ---------------------------------------------------------------- compare (unit)

def test_changes_only_for_criteria_scored_in_both():
    result = progress.compare(version({"EE03": 2, "EE04": 3, "EE05": 2}),
                              version({"EE03": 3, "EE04": 3, "EE05": 1}, at="2026-10-22T10:00:00-06:00"))
    r = by_code(result)
    assert (r["EE03"]["change"], r["EE03"]["change_es"]) == (1, "+1 punto en EE03")
    assert (r["EE04"]["change"], r["EE04"]["change_es"]) == (0, "Igual en EE04")
    assert (r["EE05"]["change"], r["EE05"]["change_es"]) == (-1, "-1 punto en EE05")
    assert r["EE03"]["statement_es"] == contracts.criteria()["EE03"]["statement_es"]  # Spanish criterion text
    assert result["status"] == "completed" and result["comparable"] is True
    assert result["summary_es"] == "Mejoraste en 1, igual en 1 y bajaste en 1 de 3 criterios comparables."
    assert "total" not in result and "average" not in str(result.keys())  # no invented total or grade
    two = progress.compare(version({"EE07": 1}), version({"EE07": 3}))
    assert by_code(two)["EE07"]["change_es"] == "+2 puntos en EE07"


def test_pending_improvement_has_no_numbers():
    for improved in (version(None), version({"EE03": 4}, status="in_progress"), version({"EE03": 4}, status="voided")):
        result = progress.compare(version({"EE03": 2}), improved)
        assert result["status"] == "pending" and result["comparable"] is False
        assert result["summary_es"] == "Tu mejora está pendiente de revisión."
        assert all(r["change"] is None and r["change_es"] is None and r["improved_points"] is None
                   for r in result["criteria"])


def test_not_evaluable_and_missing_scores_are_not_compared():
    result = progress.compare(version({"EE03": 2, "EE19": "ne", "EE04": 2}),
                              version({"EE03": 3, "EE19": "ne", "EE05": 4}))
    r = by_code(result)
    assert (r["EE19"]["first_points"], r["EE19"]["change"], r["EE19"]["change_es"]) == (None, None, "No comparable")
    assert (r["EE04"]["improved_points"], r["EE04"]["change_es"]) == (None, "No comparable")  # missing later
    assert (r["EE05"]["first_points"], r["EE05"]["change_es"]) == (None, "No comparable")  # missing first
    assert [c for c, v in r.items() if v["change"] is not None] == ["EE03"]


def test_mismatched_rubric_or_exercise_revision_is_not_compared():
    for improved in (version({"EE03": 3}, rubric_sha256="0" * 64), version({"EE03": 3}, rubric_id="OTRA-RUBRICA"),
                     version({"EE03": 3}, revision=2)):
        result = progress.compare(version({"EE03": 2}), improved)
        assert result["status"] == "completed" and result["comparable"] is False
        assert by_code(result)["EE03"]["change_es"] == "No comparable"
        assert result["summary_es"] == "No hay criterios comparables entre las dos versiones."


def test_missing_first_evaluation_is_not_compared():
    result = progress.compare(version(None), version({"EE03": 3}))
    assert result["comparable"] is False and by_code(result)["EE03"]["change_es"] == "No comparable"


# ---------------------------------------------------------------- summary (unit)

def sub(sid, exercise, attempt, at, status="completed", scores=None, level="paragraph_writing"):
    return {"submission_id": sid, "submitted_at": at, "level": level, "evaluation_status": status,
            "exercise_id": exercise, "attempt_number": attempt, "exercise_revision": 1, "title_es": exercise,
            "scorable_criteria": ["EE03", "EE04"],
            "evaluation": evaluation(scores, at=at) | {"exercise_id": exercise} if status == "completed" else None}


def test_historical_single_attempt_output_is_unchanged_in_existing_fields():
    subs = [sub("S1", "E1", 1, "2026-10-20T10:00:00-06:00", scores={"EE03": 2, "EE04": 3}),
            sub("S2", "E2", 1, "2026-10-21T10:00:00-06:00", status="pending")]
    evaluations = [s["evaluation"] for s in subs if s["evaluation"]]
    # Inputs as before T039 (no exercise or attempt fields) give the same existing fields.
    legacy = [{k: v for k, v in s.items() if k in ("submission_id", "submitted_at", "level", "evaluation_status",
                                                     "scorable_criteria")} for s in subs]
    new, old = progress.summary(evaluations, subs), progress.summary(evaluations, legacy)
    for key in ("submitted", "evaluations_completed", "evaluations_pending", "last_practice_at"):
        assert new["activity"][key] == old["activity"][key]
    assert [(lv["submitted"], lv["evaluated"]) for lv in new["activity"]["levels"]] == \
        [(lv["submitted"], lv["evaluated"]) for lv in old["activity"]["levels"]]
    assert new["criteria"] == old["criteria"] and new["dimensions"] == old["dimensions"]
    assert new["coverage"] == old["coverage"]
    a = new["activity"]
    assert (a["exercises_submitted"], a["exercises_evaluated"], a["first_attempts"], a["improvements"]) == (2, 1, 2, 0)
    assert new["revisions"] == [] and old["revisions"] == []


def test_revision_counts_one_exercise_and_one_improvement():
    first = sub("S1", "E1", 1, "2026-10-20T10:00:00-06:00", scores={"EE03": 2, "EE04": 2})
    pending = sub("S2", "E1", 2, "2026-10-21T10:00:00-06:00", status="pending")
    data = progress.summary([first["evaluation"]], [first, pending])
    a = data["activity"]
    assert (a["submitted"], a["exercises_submitted"], a["exercises_evaluated"]) == (2, 1, 1)
    assert (a["first_attempts"], a["improvements"], a["improvements_pending"], a["evaluations_pending"]) == (1, 1, 1, 1)
    level = next(lv for lv in a["levels"] if lv["code"] == "paragraph_writing")
    assert (level["exercises_submitted"], level["exercises_evaluated"], level["submitted"]) == (1, 1, 2)
    r = rows(data)
    assert r["EE03"]["status"] == "evaluated" and r["EE03"]["latest_points"] == 2  # pending never replaces latest
    assert (r["EE03"]["pending"], r["EE03"]["improvements_pending"], r["EE03"]["exercises"]) == (1, 1, 1)
    (comparison,) = data["revisions"]
    assert comparison["status"] == "pending" and comparison["exercise_id"] == "E1"

    improved = sub("S2", "E1", 2, "2026-10-21T10:00:00-06:00", scores={"EE03": 3, "EE04": 2})
    improved["evaluation"]["evaluated_at"] = "2026-10-22T10:00:00-06:00"
    data = progress.summary([first["evaluation"], improved["evaluation"]], [first, improved])
    r = rows(data)
    assert (r["EE03"]["latest_points"], r["EE03"]["best_points"], r["EE03"]["evaluations"],
            r["EE03"]["exercises"]) == (3, 3, 2, 1)
    assert data["coverage"]["evaluated"] == 2  # coverage by criterion, not by attempt
    a = data["activity"]
    assert (a["exercises_evaluated"], a["evaluations_completed"], a["improvements_pending"]) == (1, 2, 0)
    (comparison,) = data["revisions"]
    assert [c["change_es"] for c in comparison["criteria"]] == ["+1 punto en EE03", "Igual en EE04"]


def test_several_exercises_mixed_levels_one_revised():
    subs = [sub("A1", "EA", 1, "2026-10-20T10:00:00-06:00", scores={"EE03": 1, "EE04": 1}),
            sub("B1", "EB", 1, "2026-10-20T11:00:00-06:00", scores={"EE07": 2}, level="writing_conventions"),
            sub("A2", "EA", 2, "2026-10-21T10:00:00-06:00", scores={"EE03": 2, "EE04": 1}),
            sub("C1", "EC", 1, "2026-10-21T11:00:00-06:00", status="in_progress", level="writing_conventions")]
    data = progress.summary([s["evaluation"] for s in subs if s["evaluation"]], subs)
    levels = {lv["code"]: lv for lv in data["activity"]["levels"]}
    paragraph, conventions = levels["paragraph_writing"], levels["writing_conventions"]
    assert (paragraph["exercises_submitted"], paragraph["submitted"]) == (1, 2)
    assert (conventions["exercises_submitted"], conventions["exercises_evaluated"]) == (2, 1)
    assert data["activity"]["exercises_submitted"] == 3 and [r["exercise_id"] for r in data["revisions"]] == ["EA"]


# ---------------------------------------------------------------- API and store (synthetic mentor_pro_test)

def test_api_progress_with_a_pending_then_completed_revision(env):
    student, _, url = env
    eid = L2["exercise_id"]
    reviewed(student, L2, "Mi primer párrafo.")
    submit(student, L1["exercise_id"])  # another exercise, pending
    data = student.get("/api/writing/progress").json()
    assert (data["activity"]["submitted"], data["activity"]["exercises_submitted"]) == (2, 2)
    assert data["revisions"] == []

    sid = revise(student, eid, "Mi párrafo mejorado.")
    data = student.get("/api/writing/progress").json()
    a = data["activity"]
    assert (a["submitted"], a["exercises_submitted"], a["improvements"], a["improvements_pending"]) == (3, 2, 1, 1)
    (comparison,) = data["revisions"]
    assert comparison["status"] == "pending" and comparison["title_es"]
    assert student.get(f"/api/writing/exercises/{eid}").json()["revision_attempt"]["attempt"]["comparison"] is None
    assert student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()["comparison"] is None

    review(student, sid, {c: 3 for c in L2["target_criteria"]})
    data = student.get("/api/writing/progress").json()
    (comparison,) = data["revisions"]
    assert comparison["comparable"] and all(c["change"] == 1 for c in comparison["criteria"])
    assert data["activity"]["exercises_evaluated"] == 1 and data["activity"]["evaluations_completed"] == 2
    view = student.get(f"/api/writing/exercises/{eid}").json()["revision_attempt"]["attempt"]["comparison"]
    assert view == {k: comparison[k] for k in view}
    tutor = student.get(f"/api/tutor/submissions/{sid}", headers=HEADERS).json()["comparison"]
    assert tutor["criteria"] == comparison["criteria"]
    with psycopg.connect(url) as conn:
        first = conn.execute("SELECT s.submission_id FROM writing.submission s JOIN writing.student_attempt a "
                             "USING (attempt_id) WHERE s.exercise_id = %s AND a.attempt_number = 1",
                             (eid,)).fetchone()[0]
    assert student.get(f"/api/tutor/submissions/{first}", headers=HEADERS).json()["comparison"] is None


def test_progress_reads_write_nothing_with_revisions(env):
    student, _, url = env
    eid = L2["exercise_id"]
    reviewed(student, L2)
    review(student, revise(student, eid, "Mejorado."), {c: 1 for c in L2["target_criteria"]})

    def snapshot():
        with psycopg.connect(url) as conn:
            return [conn.execute(f"SELECT to_jsonb(t) FROM writing.{t} t ORDER BY 1").fetchall()
                    for t in ("submission", "evaluation", "criterion_score", "student_attempt", "draft")]

    before = snapshot()
    data = student.get("/api/writing/progress").json()
    student.get(f"/api/writing/exercises/{eid}")
    assert snapshot() == before
    (comparison,) = data["revisions"]
    assert all(c["change"] == -1 and c["change_es"].startswith("-1 punto") for c in comparison["criteria"])


def test_student_comparison_never_carries_tutor_only_fields(env):
    student, _, _ = env
    eid = L2["exercise_id"]
    reviewed(student, L2)
    review(student, revise(student, eid, "Mejorado."), {c: 3 for c in L2["target_criteria"]})
    text = str(student.get("/api/writing/progress").json()) + str(student.get(f"/api/writing/exercises/{eid}").json())
    for forbidden in ("corrected_text_es", "reference", "evaluator", "token"):
        assert forbidden not in text

