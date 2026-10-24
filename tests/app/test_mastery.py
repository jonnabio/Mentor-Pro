"""Repeat-aware learning status (T014, ADR-015): thresholds, first attempts, repeats, history."""

from __future__ import annotations

import uuid
from fractions import Fraction

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.practice.mastery import RECOMMENDATIONS_ES, STATUS_LABELS_ES, Thresholds, classify
from app.practice.store import PracticeStore
from conftest import SYNTHETIC

# ---------------------------------------------------------------- classification (exact, unrounded)


@pytest.mark.parametrize("distinct,correct,status", [
    (0, 0, "unpracticed"),
    (1, 1, "insufficient_evidence"),
    (4, 4, "insufficient_evidence"),             # fewer than 5 distinct questions, even at 100 %
    (5, 2, "needs_reinforcement"),               # 40 %
    (1000, 599, "needs_reinforcement"),          # 59.9 %: would round to 60 %, but is below it
    (5, 3, "in_progress"),                       # exactly 60 %
    (1000, 799, "in_progress"),                  # 79.9 %
    (5, 4, "good_proficiency"),                  # exactly 80 %
    (10, 9, "good_proficiency"),                 # exactly 90 % (inclusive)
    (1000, 900, "good_proficiency"),
    (1000, 901, "consolidated_mastery"),         # 90.1 %: strictly above 90 %
    (20, 19, "consolidated_mastery"),            # 95 %
    (5, 5, "consolidated_mastery"),              # 100 %
])
def test_status_boundaries(distinct, correct, status):
    assert classify(distinct, correct) == status


def test_labels_and_recommendation_are_spanish():
    assert list(STATUS_LABELS_ES.values()) == ["Sin practicar", "Evidencia insuficiente", "Necesita refuerzo",
                                               "En progreso", "Buen dominio", "Dominio consolidado"]
    assert RECOMMENDATIONS_ES["consolidated_mastery"] == (
        "¡Excelente dominio! Practicá de vez en cuando para mantener lo aprendido.")
    assert RECOMMENDATIONS_ES["needs_reinforcement"].startswith("Prioridad de repaso")  # T019
    assert RECOMMENDATIONS_ES["in_progress"].startswith("Vas por buen camino")
    assert set(RECOMMENDATIONS_ES) <= set(STATUS_LABELS_ES)


def test_thresholds_are_configurable():
    custom = Thresholds.from_env({"MENTOR_PRO_MASTERY_MIN_DISTINCT": "3",
                                  "MENTOR_PRO_MASTERY_REINFORCEMENT_BELOW_PCT": "50",
                                  "MENTOR_PRO_MASTERY_PROGRESS_BELOW_PCT": "75",
                                  "MENTOR_PRO_MASTERY_GOOD_UP_TO_PCT": "87.5"})
    assert custom == Thresholds(3, Fraction(1, 2), Fraction(3, 4), Fraction(7, 8))
    assert classify(3, 2, custom) == "in_progress" and classify(8, 7, custom) == "good_proficiency"
    assert Thresholds.from_env({}) == Thresholds()
    for bad in ({"MENTOR_PRO_MASTERY_PROGRESS_BELOW_PCT": "50"}, {"MENTOR_PRO_MASTERY_GOOD_UP_TO_PCT": "100"},
                {"MENTOR_PRO_MASTERY_MIN_DISTINCT": "0"}):
        with pytest.raises(ValueError):
            Thresholds.from_env(bad)


# ---------------------------------------------------------------- metrics from recorded answers

EVIDENCE = "M02-E1"  # synthetic M02 has one evidencia


@pytest.fixture()
def history(synthetic_client):
    """A clean practice history for the synthetic baseline, and a helper to record practices."""
    url, schema = synthetic_client.app.state.catalog_target
    store = PracticeStore(url)

    def clean():
        with psycopg.connect(url, autocommit=True) as conn:
            sessions = "SELECT session_id FROM practice.session WHERE baseline_version = %s"
            for table in ("classification_audit", "session_classification", "answer"):
                conn.execute(f"DELETE FROM practice.{table} WHERE session_id IN ({sessions})", (SYNTHETIC,))
            conn.execute(f"DELETE FROM practice.item WHERE session_id IN ({sessions})", (SYNTHETIC,))
            conn.execute("DELETE FROM practice.session WHERE baseline_version = %s", (SYNTHETIC,))

    def record(questions, answers, browser=None):
        """questions: [(objective, question_id, key)]; answers: {slot: label} (unanswered slots allowed)."""
        session, _ = store.create_or_get(str(uuid.uuid4()), SYNTHETIC, {
            "subject": "matematicas", "scope": "selected_objectives", "objective_codes": [str(uuid.uuid4())],
            "difficulty": "medium", "question_count": 5}, [], browser)
        items = [{"slot": n, "objective_code": code, "evidence_id": f"{code}-E1",
                  "item": {"item_id": qid, "answer_key": key, "source_refs": [{"excerpt": "Evidencia"}]}}
                 for n, (code, qid, key) in enumerate(questions, start=1)]
        store.finish(session["session_id"], "complete", None, None, items)
        for slot, label in answers.items():
            store.answer(session["session_id"], slot, label, label == questions[slot - 1][2])
        return session["session_id"]

    clean()
    client = TestClient(create_app(url, schema, SYNTHETIC))

    def objective(code="M02"):
        subject = next(s for s in client.get("/api/dashboard").json()["subjects"] if s["subject"] == "matematicas")
        return subject, next(o for o in subject["objectives"] if o["code"] == code)

    yield record, objective, url
    clean()


def test_same_question_five_times_does_not_establish_mastery(history):
    record, objective, _ = history
    for n in range(5):  # five practices, five browser tabs, the same canonical question
        record([("M02", "Q-same", "A")], {1: "A"}, browser=f"hash-{n}")
    _, m02 = objective()
    assert (m02["total_answers"], m02["distinct_questions"], m02["repeat_answers"]) == (5, 1, 4)
    assert m02["status"] == "insufficient_evidence" and m02["status_es"] == "Evidencia insuficiente"
    assert m02["repeat_exposure_rate"] == pytest.approx(0.8) and m02["repeat_accuracy"] == 1.0


def test_five_distinct_questions_qualify(history):
    record, objective, _ = history
    record([("M02", f"Q-{n}", "A") for n in range(5)], {1: "A", 2: "A", 3: "A", 4: "A", 5: "B"})
    subject, m02 = objective()
    assert m02["distinct_questions"] == 5 and m02["mastery_accuracy"] == pytest.approx(0.8)
    assert m02["status"] == "good_proficiency" and m02["distinct_evidences"] == 1
    assert subject["status_counts"]["good_proficiency"] == 1
    assert sum(subject["status_counts"].values()) == subject["objective_count"]


def test_repeated_correct_answers_do_not_raise_mastery(history):
    record, objective, _ = history
    record([("M02", f"Q-{n}", "A") for n in range(5)], {1: "B", 2: "B", 3: "A", 4: "A", 5: "A"})  # 60 %
    for _ in range(3):
        record([("M02", "Q-0", "A"), ("M02", "Q-1", "A")], {1: "A", 2: "A"})  # later correct repeats
    _, m02 = objective()
    assert m02["mastery_accuracy"] == pytest.approx(0.6) and m02["status"] == "in_progress"
    assert m02["practice_accuracy"] == pytest.approx(9 / 11) and m02["repeat_accuracy"] == 1.0


def test_repeated_wrong_answers_keep_the_first_attempt_and_history(history):
    record, objective, url = history
    record([("M02", f"Q-{n}", "A") for n in range(5)], {n: "A" for n in range(1, 6)})  # 100 %
    record([("M02", "Q-0", "A")], {1: "D"})
    record([("M02", "Q-0", "A")], {1: "C"})
    _, m02 = objective()
    assert m02["mastery_accuracy"] == 1.0 and m02["status"] == "consolidated_mastery"
    assert m02["recommendation_es"].startswith("¡Excelente dominio!")
    assert m02["total_answers"] == 7 and m02["repeat_accuracy"] == 0.0
    with psycopg.connect(url) as conn:  # every attempt is still stored
        assert conn.execute("SELECT COUNT(*) FROM practice.answer a JOIN practice.item i USING (session_id, slot) "
                            "WHERE i.item->>'item_id' = 'Q-0'").fetchone()[0] == 3


def test_unanswered_questions_are_not_first_attempts(history):
    record, objective, _ = history
    record([("M02", f"Q-{n}", "A") for n in range(5)], {1: "A", 2: "A"})  # three left unanswered
    _, m02 = objective()
    assert (m02["total_answers"], m02["distinct_questions"]) == (2, 2)
    assert m02["status"] == "insufficient_evidence"
    record([("M02", "Q-4", "A")], {1: "B"})  # first real attempt at Q-4 happens later
    _, m02 = objective()
    assert m02["distinct_questions"] == 3 and m02["repeat_answers"] == 0


def test_untouched_objectives_are_unpracticed(history):
    record, objective, _ = history
    subject, m01 = objective("M01")
    assert m01["status"] == "unpracticed" and m01["status_es"] == "Sin practicar"
    assert subject["status_counts"]["unpracticed"] == subject["objective_count"]


def test_answers_from_cancelled_practices_count_and_unanswered_do_not(history):
    record, objective, url = history
    record([("M02", f"Q-{n}", "A") for n in range(5)], {1: "A", 2: "B"})   # two answered, three left open
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE practice.session SET cancelled_at = now() WHERE baseline_version = %s", (SYNTHETIC,))
    _, m02 = objective()
    assert (m02["total_answers"], m02["distinct_questions"], m02["first_attempt_correct"]) == (2, 2, 1)
    assert m02["status"] == "insufficient_evidence"


def test_generated_questions_without_answers_do_not_affect_progress(history):
    """T014.1: served-but-unanswered practices and bank inventory never count as attempts."""
    record, objective, _ = history
    for _ in range(3):
        record([("M02", f"Q-gen-{uuid.uuid4().hex[:6]}", "A") for _ in range(5)], {})
    subject, m02 = objective()
    assert (m02["total_answers"], m02["distinct_questions"], m02["status"]) == (0, 0, "unpracticed")
    assert subject["status_counts"]["unpracticed"] == subject["objective_count"]


def classify_session(url, session_id, classification):
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("""INSERT INTO practice.session_classification (session_id, classification, reason, audit_ref)
                        VALUES (%s, %s, 'test', 'test-ref')""", (session_id, classification))


@pytest.mark.parametrize("excluded", ["automated_test", "quarantined"])
def test_classified_sessions_are_excluded_and_first_attempts_recomputed(history, excluded):
    """T017: excluded sessions vanish before attempts are numbered; the student's later answer becomes first."""
    record, objective, url = history
    test_session = record([("M02", f"Q-{n}", "A") for n in range(5)], {n: "A" for n in range(1, 6)})
    record([("M02", "Q-0", "A")], {1: "B"})  # student, later, wrong
    _, m02 = objective()
    assert (m02["total_answers"], m02["repeat_answers"], m02["first_attempt_correct"]) == (6, 1, 5)
    classify_session(url, test_session, excluded)
    _, m02 = objective()
    assert (m02["total_answers"], m02["distinct_questions"], m02["first_attempt_correct"]) == (1, 1, 0)
    assert m02["repeat_answers"] == 0 and m02["status"] == "insufficient_evidence"


def test_student_classification_and_cancelled_student_practices_still_count(history):
    record, objective, url = history
    kept = record([("M02", f"Q-{n}", "A") for n in range(5)], {1: "A", 2: "B"})
    classify_session(url, kept, "student")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("UPDATE practice.session SET cancelled_at = now() WHERE session_id = %s", (kept,))
    subject, m02 = objective()
    assert (m02["total_answers"], m02["first_attempt_correct"]) == (2, 1)  # 3 unanswered: not incorrect
    assert len(subject["objectives"]) == subject["objective_count"]
    assert sum(subject["status_counts"].values()) == subject["objective_count"]


def test_exposure_history_ignores_classified_sessions(history):
    from app.practice.bank import QuestionBank

    record, _, url = history
    test_session = record([("M02", "Q-test-only", "A")], {1: "A"})
    record([("M02", "Q-student", "A")], {})
    bank = QuestionBank(url)
    assert {"Q-test-only", "Q-student"} <= bank.seen_questions()
    classify_session(url, test_session, "automated_test")
    seen = bank.seen_questions()
    assert "Q-student" in seen and "Q-test-only" not in seen
