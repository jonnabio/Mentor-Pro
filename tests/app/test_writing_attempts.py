"""Student attempts (T036, ADR-032): migration 0001, attempt integrity and attempt-scoped persistence.

Test database only (TEST_DATABASE_URL). Historical rows are synthetic fixtures written with the pre-T036 schema.
"""

from __future__ import annotations

import copy
import os
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.writing import migrations
from app.writing.store import SCHEMA_SQL, RevisionNotAllowed, WritingStore
from test_writing_guided import SECTIONS, guided_exercise
from test_writing_tutor import L1, L23

URL = os.environ["TEST_DATABASE_URL"]
L2 = L23["introduction_paragraph"]
L3 = next(r for k, r in L23.items() if k != "introduction_paragraph")
L4 = guided_exercise()
L1_CORRECTED = "Los niños juegan al fútbol en la cancha de la comunidad."


def sql(query, *params):
    with psycopg.connect(URL) as conn:
        return conn.execute(query, params).fetchall()


def drop():
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")


def unchecked_store() -> WritingStore:
    """A store over the legacy schema without the startup check (to add exercises the pre-T036 way)."""
    store = WritingStore.__new__(WritingStore)
    store.url = URL
    return store


def complete(submission_id, evaluation_id=None):
    """A completed tutor evaluation with two criterion scores (rows as T026 stores them)."""
    eid = evaluation_id or f"EVAL-{submission_id}"
    record = {"evaluation_id": eid, "feedback_es": {"strengths": ["Bien."], "improvements": ["Revisá tildes."]}}
    with psycopg.connect(URL) as conn:
        conn.execute("""INSERT INTO writing.evaluation (evaluation_id, submission_id, status, evaluator_role, rubric_id,
                            rubric_sha256, evaluated_at, feedback, record, exercise_revision)
                        VALUES (%s, %s, 'completed', 'parent', 'MEP-PE-2026', 'abc123', '2026-10-20T10:00:00Z',
                                %s, %s, 1)""",
                     (eid, submission_id, Jsonb(record["feedback_es"]), Jsonb(record)))
        for code, points in (("EE07", 3), ("EE08", 2)):
            conn.execute("""INSERT INTO writing.criterion_score (evaluation_id, criterion_code, status, points,
                                descriptor_ref) VALUES (%s, %s, 'scored', %s, %s)""",
                         (eid, code, points, f"MEP-PE-2026#{code}@{points}"))
    return eid


@pytest.fixture()
def legacy():
    """A pre-T036 database: draft keyed by exercise, one submission per exercise, with mixed history."""
    drop()
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL)
        conn.execute("CREATE UNIQUE INDEX uq_submission_exercise ON writing.submission (exercise_id)")
    store = unchecked_store()
    for record in (L1, L2, L3, L4):
        store.add_exercise(copy.deepcopy(record))
    with psycopg.connect(URL) as conn:
        # L2: draft only, saved before T030 (no client_seq, no revision)
        conn.execute("INSERT INTO writing.draft (exercise_id, text_es, word_count, updated_at) "
                     "VALUES (%s, 'Mi borrador.', 2, '2026-10-01T08:00:00Z')", (L2["exercise_id"],))
        # L3: submission only (no draft row), revision 1
        conn.execute("""INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count,
                            paragraph_count, submitted_at, client_request_id)
                        VALUES ('SUB-L3-hist-0001', %s, 'typed', 'Párrafo entregado.', 2, 1,
                                '2026-10-02T09:00:00Z', 'req-hist-3')""", (L3["exercise_id"],))
        # L1: draft + submission (correction) with a completed evaluation; draft saved against revision 1
        conn.execute("""INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count,
                            paragraph_count, submitted_at, client_request_id, exercise_revision)
                        VALUES ('SUB-L1-hist-0001', %s, 'typed', %s, 10, 1, '2026-10-03T10:00:00Z', 'req-hist-1', 1)""",
                     (L1["exercise_id"], L1_CORRECTED))
        conn.execute("INSERT INTO writing.draft (exercise_id, text_es, word_count, client_seq, exercise_revision, "
                     "updated_at) VALUES (%s, %s, 10, 7, 1, '2026-10-03T10:00:00Z')", (L1["exercise_id"], L1_CORRECTED))
        # L4: five sections, draft and submission
        text = "\n\n".join(SECTIONS[k] for k in ("introduction", "development_1", "development_2", "conclusion"))
        conn.execute("""INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count,
                            paragraph_count, submitted_at, client_request_id, sections)
                        VALUES ('SUB-L4-hist-0001', %s, 'typed', %s, 40, 4, '2026-10-04T11:00:00Z', 'req-hist-4', %s)""",
                     (L4["exercise_id"], text, Jsonb(SECTIONS)))
        conn.execute("INSERT INTO writing.draft (exercise_id, text_es, word_count, sections, client_seq, "
                     "exercise_revision, updated_at) VALUES (%s, %s, 40, %s, 12, 1, '2026-10-04T10:59:00Z')",
                     (L4["exercise_id"], text, Jsonb(SECTIONS)))
    complete("SUB-L1-hist-0001", "EVAL-L1-hist-0001")
    yield store
    drop()


@pytest.fixture()
def fresh():
    drop()
    store = WritingStore(URL)
    for record in (L1, L2, L4):
        store.add_exercise(copy.deepcopy(record))
    yield store
    drop()


def snapshot():
    return {
        "draft": sql("SELECT exercise_id, text_es, word_count, sections, client_seq, exercise_revision, updated_at "
                     "FROM writing.draft ORDER BY exercise_id"),
        "submission": sql("SELECT submission_id, exercise_id, text_es, sections, exercise_revision, submitted_at, "
                          "client_request_id FROM writing.submission ORDER BY submission_id"),
        "evaluation": sql("SELECT * FROM writing.evaluation ORDER BY evaluation_id"),
        "criterion_score": sql("SELECT * FROM writing.criterion_score ORDER BY evaluation_id, criterion_code"),
    }


def indexes():
    return {r[0] for r in sql("SELECT indexname FROM pg_indexes WHERE schemaname = 'writing'")}


# ---------------------------------------------------------------- startup and empty database


def test_empty_database_is_created_at_the_current_version(fresh):
    with psycopg.connect(URL) as conn:
        assert migrations.state(conn) == "current"
    assert sql("SELECT migration_id, mode FROM writing.schema_migration") == [("0001_student_attempts", "fresh")]
    assert sql("SELECT count(*) FROM writing.student_attempt") == [(0,)]
    assert "uq_submission_attempt" in indexes() and "uq_submission_exercise" not in indexes()
    assert sql("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid "
               "AND a.attnum = ANY(i.indkey) WHERE i.indrelid = 'writing.draft'::regclass AND i.indisprimary") \
        == [("attempt_id",)]
    WritingStore(URL)  # a second start on the current schema changes nothing and does not recreate the old index
    assert "uq_submission_exercise" not in indexes()


def test_startup_refuses_an_unmigrated_database_and_changes_nothing(legacy):
    before = snapshot()
    with pytest.raises(migrations.SchemaMigrationRequired, match="app.writing.migrate apply"):
        WritingStore(URL)
    assert sql("SELECT to_regclass('writing.student_attempt')") == [(None,)]
    assert snapshot() == before and "uq_submission_exercise" in indexes()


# ---------------------------------------------------------------- migration of historical records


def test_migration_backfills_attempt_one_and_preserves_every_record(legacy):
    progress_before = legacy.progress_inputs()
    before = snapshot()
    report = migrations.apply(URL)
    assert report["status"] == "applied" and report["attempts_created"] == 4
    assert report["before"] == report["after"]
    assert report["drafts_with_other_revision_than_submission"] == 0
    assert snapshot() == before  # ids, texts, sections, revisions, timestamps, scores and feedback byte-identical
    attempts = {r[0]: r[1:] for r in sql("SELECT exercise_id, attempt_number, previous_attempt_id, exercise_revision "
                                         "FROM writing.student_attempt")}
    assert attempts == {e["exercise_id"]: (1, None, 1) for e in (L1, L2, L3, L4)}
    # every draft and submission points at its exercise's attempt 1
    assert sql("SELECT count(*) FROM writing.draft d JOIN writing.student_attempt a USING (attempt_id, exercise_id)") \
        == [(3,)]
    assert sql("SELECT count(*) FROM writing.submission s JOIN writing.student_attempt a "
               "USING (attempt_id, exercise_id)") == [(3,)]
    # attempt created_at: the earliest recorded timestamp of that work
    assert sql("SELECT created_at = '2026-10-04T10:59:00Z' FROM writing.student_attempt WHERE exercise_id = %s",
               L4["exercise_id"]) == [(True,)]
    store = WritingStore(URL)  # the application now starts
    assert store.progress_inputs() == progress_before
    assert store.submission(L1["exercise_id"])["submission_id"] == "SUB-L1-hist-0001"
    assert store.draft(L2["exercise_id"])["text_es"] == "Mi borrador."
    assert store.draft(L3["exercise_id"]) is None
    assert store.submission(L4["exercise_id"])["sections"] == SECTIONS
    assert [r["attempt_number"] for r in store.tutor_queue()] == [1, 1, 1]
    states = {r["exercise_id"]: (r["submission_id"], r["draft_saved_at"] is not None) for r in store.exercises()}
    assert states[L2["exercise_id"]] == (None, True) and states[L3["exercise_id"]] == ("SUB-L3-hist-0001", False)


def test_migration_is_recorded_once_and_reapplying_changes_nothing(legacy):
    migrations.apply(URL)
    after = snapshot()
    assert migrations.apply(URL) == {"migration": "0001_student_attempts", "status": "already_applied"}
    assert snapshot() == after and sql("SELECT count(*) FROM writing.student_attempt") == [(4,)]
    assert sql("SELECT mode FROM writing.schema_migration") == [("migrated",)]


def test_dry_run_reports_and_rolls_back(legacy):
    before = snapshot()
    report = migrations.apply(URL, dry_run=True)
    assert report["status"] == "dry_run_rolled_back" and report["attempts_created"] == 4
    with psycopg.connect(URL) as conn:
        assert migrations.state(conn) == "legacy"
    assert snapshot() == before and "uq_submission_exercise" in indexes()


def test_a_failed_validation_rolls_everything_back(legacy, monkeypatch):
    before = snapshot()
    monkeypatch.setattr(migrations, "_validate", lambda conn, b: ["1 injected failure"])
    with pytest.raises(migrations.MigrationError, match="injected"):
        migrations.apply(URL)
    with psycopg.connect(URL) as conn:
        assert migrations.state(conn) == "legacy"
    assert sql("SELECT to_regclass('writing.student_attempt')") == [(None,)]
    assert sql("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'writing' "
               "AND column_name = 'attempt_id'") == [(0,)]
    assert snapshot() == before and "uq_submission_exercise" in indexes()


def test_anomalous_history_is_refused_before_any_change(legacy):
    with psycopg.connect(URL) as conn:  # two submissions for one exercise: the old index would never allow it
        conn.execute("DROP INDEX writing.uq_submission_exercise")
        conn.execute("""INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es,
                            submitted_at) VALUES ('SUB-L3-hist-0002', %s, 'typed', 'Otra.', now())""",
                     (L3["exercise_id"],))
    with pytest.raises(migrations.MigrationError, match="1 exercises with more than one submission"):
        migrations.apply(URL)
    assert sql("SELECT to_regclass('writing.student_attempt')") == [(None,)]


def test_rollback_restores_the_old_schema_while_only_first_attempts_exist(legacy):
    before = snapshot()
    migrations.apply(URL)
    report = migrations.rollback(URL)
    assert report["status"] == "rolled_back" and report["before"] == report["after"]
    with psycopg.connect(URL) as conn:
        assert migrations.state(conn) == "legacy"
    assert snapshot() == before and "uq_submission_exercise" in indexes()
    assert migrations.apply(URL)["status"] == "applied"  # and it can be applied again


def test_rollback_is_refused_once_a_revision_attempt_exists(legacy):
    migrations.apply(URL)
    WritingStore(URL).start_revision(L1["exercise_id"])
    with pytest.raises(migrations.MigrationError, match="1 revision attempts exist"):
        migrations.rollback(URL)
    assert sql("SELECT count(*) FROM writing.student_attempt") == [(5,)]


# ---------------------------------------------------------------- integrity constraints


def test_the_schema_rejects_inconsistent_attempt_references(fresh):
    fresh.save_draft(L1["exercise_id"], "Uno.")
    fresh.save_draft(L2["exercise_id"], "Dos.")
    a1, a2 = (fresh.attempts(e["exercise_id"])[0]["attempt_id"] for e in (L1, L2))
    bad = [
        ("INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, exercise_revision) "
         "VALUES ('ATT-dup', %s, 1, 1)", (L1["exercise_id"],)),                      # duplicate attempt number
        ("INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, exercise_revision) "
         "VALUES ('ATT-x', %s, 2, 1)", (L1["exercise_id"],)),                        # attempt 2 without predecessor
        ("INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, previous_attempt_id, "
         "exercise_revision) VALUES ('ATT-y', %s, 2, %s, 1)", (L1["exercise_id"], a2)),  # predecessor elsewhere
        ("UPDATE writing.draft SET exercise_id = %s WHERE attempt_id = %s", (L2["exercise_id"], a1)),  # cross exercise
        ("INSERT INTO writing.submission (submission_id, exercise_id, attempt_id, evidence_mode, text_es, "
         "submitted_at) VALUES ('SUB-x', %s, %s, 'typed', 'x', now())", (L2["exercise_id"], a1)),
        ("INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, submitted_at) "
         "VALUES ('SUB-y', %s, 'typed', 'x', now())", (L1["exercise_id"],)),        # submission without attempt
    ]
    for query, params in bad:
        with pytest.raises(psycopg.errors.IntegrityError), psycopg.connect(URL) as conn:
            conn.execute(query, params)
    fresh.submit_typed(L1["exercise_id"], "Uno.", "req-1")
    with pytest.raises(psycopg.errors.UniqueViolation), psycopg.connect(URL) as conn:  # second submission, same attempt
        conn.execute("INSERT INTO writing.submission (submission_id, exercise_id, attempt_id, evidence_mode, text_es, "
                     "submitted_at) VALUES ('SUB-z', %s, %s, 'typed', 'x', now())", (L1["exercise_id"], a1))


def test_parallel_first_saves_create_one_attempt(fresh):
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(lambda i: fresh.save_draft(L2["exercise_id"], f"Texto {i}.", client_seq=i), range(1, 13)))
    assert len(fresh.attempts(L2["exercise_id"])) == 1
    assert fresh.draft(L2["exercise_id"])["client_seq"] == 12


# ---------------------------------------------------------------- revision attempts (persistence only)


def submitted_and_evaluated(store, exercise, text=L1_CORRECTED, sections=None):
    sub, _ = store.submit_typed(exercise["exercise_id"], text, "req-first", sections)
    complete(sub["submission_id"])
    return sub


def test_a_revision_needs_a_completed_evaluation(fresh):
    eid = L1["exercise_id"]
    with pytest.raises(RevisionNotAllowed, match="no submitted attempt"):
        fresh.start_revision(eid)
    fresh.save_draft(eid, "Borrador.")
    with pytest.raises(RevisionNotAllowed, match="not submitted"):
        fresh.start_revision(eid)
    sub, _ = fresh.submit_typed(eid, L1_CORRECTED, "req-1")
    with pytest.raises(RevisionNotAllowed, match="not completed"):
        fresh.start_revision(eid)
    with psycopg.connect(URL) as conn:  # an evaluation saved partially does not count either
        conn.execute("INSERT INTO writing.evaluation (evaluation_id, submission_id, status, evaluator_role, rubric_id, "
                     "rubric_sha256, feedback, record) VALUES ('EV-p', %s, 'in_progress', 'parent', 'r', 's', '{}', "
                     "'{}')", (sub["submission_id"],))
    with pytest.raises(RevisionNotAllowed, match="not completed"):
        fresh.start_revision(eid)
    assert len(fresh.attempts(eid)) == 1


def test_l1_revision_starts_from_the_submitted_correction_and_keeps_the_original(fresh):
    eid = L1["exercise_id"]
    sub = submitted_and_evaluated(fresh, L1)
    before = snapshot()
    attempt, created = fresh.start_revision(eid)
    assert created and attempt["attempt_number"] == 2
    assert attempt["previous_attempt_id"] == fresh.attempts(eid)[0]["attempt_id"]
    seeded = fresh.attempt_draft(attempt["attempt_id"])
    assert seeded["text_es"] == L1_CORRECTED != L1["source_text_es"] and seeded["client_seq"] is None
    after = snapshot()
    assert after["submission"] == before["submission"] and after["evaluation"] == before["evaluation"]
    assert after["criterion_score"] == before["criterion_score"]
    assert fresh.submission(eid)["submission_id"] == sub["submission_id"]  # exercise-level reads stay on attempt 1


def test_l4_revision_keeps_all_five_sections_and_the_assembled_text(fresh):
    eid = L4["exercise_id"]
    text = "\n\n".join(SECTIONS[k] for k in ("introduction", "development_1", "development_2", "conclusion"))
    submitted_and_evaluated(fresh, L4, text, SECTIONS)
    attempt, _ = fresh.start_revision(eid)
    seeded = fresh.attempt_draft(attempt["attempt_id"])
    assert seeded["sections"] == SECTIONS and set(seeded["sections"]) == {
        "plan", "introduction", "development_1", "development_2", "conclusion"}
    assert seeded["text_es"] == text
    revised = {**SECTIONS, "conclusion": "Una conclusión mejorada."}
    sub, created = fresh.submit_attempt(attempt["attempt_id"], text.rsplit("\n\n", 1)[0] + "\n\nUna conclusión "
                                        "mejorada.", "req-rev", revised)
    assert created and sub["sections"] == revised and sub["attempt_id"] == attempt["attempt_id"]
    assert fresh.submission(eid)["sections"] == SECTIONS  # the first submission is unchanged


def test_parallel_revision_starts_yield_one_attempt_and_never_reseed(fresh):
    eid = L2["exercise_id"]
    submitted_and_evaluated(fresh, L2, "Mi párrafo.")
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: fresh.start_revision(eid), range(8)))
    assert sum(created for _, created in results) == 1
    assert {a["attempt_id"] for a, _ in results} == {fresh.attempts(eid)[1]["attempt_id"]}
    attempt_id = results[0][0]["attempt_id"]
    fresh.save_attempt_draft(attempt_id, "Mi párrafo mejorado.", client_seq=5)
    again, created = fresh.start_revision(eid)  # e.g. a reload: returns the open attempt, keeps its text
    assert not created and fresh.attempt_draft(attempt_id)["text_es"] == "Mi párrafo mejorado."


def test_attempt_autosave_ordering_submission_idempotency_and_freeze(fresh):
    eid = L2["exercise_id"]
    submitted_and_evaluated(fresh, L2, "Mi párrafo.")
    attempt_id = fresh.start_revision(eid)[0]["attempt_id"]
    assert fresh.save_attempt_draft(attempt_id, "Nuevo.", client_seq=20)["applied"]
    stale = fresh.save_attempt_draft(attempt_id, "Viejo.", client_seq=10)
    assert not stale["applied"] and fresh.attempt_draft(attempt_id)["text_es"] == "Nuevo."
    first, created = fresh.submit_attempt(attempt_id, "Nuevo.", "req-a")
    retry, created_again = fresh.submit_attempt(attempt_id, "Otro texto.", "req-b")
    assert created and not created_again and retry["submission_id"] == first["submission_id"]
    assert retry["text_es"] == "Nuevo."
    assert fresh.save_attempt_draft(attempt_id, "Después.", client_seq=99) is None  # frozen after submission
    with pytest.raises(LookupError):
        fresh.save_attempt_draft("ATT-unknown", "x")
    with pytest.raises(LookupError):
        fresh.submit_attempt("ATT-unknown", "x", "req-x")
    complete(first["submission_id"])
    with pytest.raises(RevisionNotAllowed, match="attempt limit"):
        fresh.start_revision(eid)


def test_legacy_exercise_writes_never_reach_a_revision_attempt(fresh):
    eid = L2["exercise_id"]
    first = submitted_and_evaluated(fresh, L2, "Mi párrafo.")
    attempt_id = fresh.start_revision(eid)[0]["attempt_id"]
    fresh.save_attempt_draft(attempt_id, "Revisión en curso.", client_seq=3)
    assert fresh.save_draft(eid, "Escrito por un cliente viejo.", client_seq=999) is None  # attempt 1 is frozen
    again, created = fresh.submit_typed(eid, "Otro.", "req-old")
    assert not created and again["submission_id"] == first["submission_id"]
    assert fresh.attempt_draft(attempt_id)["text_es"] == "Revisión en curso."
    assert fresh.attempt_submission(attempt_id) is None
    assert fresh.draft(eid)["text_es"] == "Mi párrafo."
    assert [r["submission_id"] for r in fresh.exercises() if r["exercise_id"] == eid] == [first["submission_id"]]


def test_attempt_one_follows_editorial_revisions_until_submitted_and_a_revision_stays_pinned(fresh):
    eid = L2["exercise_id"]
    fresh.save_draft(eid, "Borrador.")
    fresh.add_revision(eid, copy.deepcopy(L2), None, "aclaración", [])
    sub, _ = fresh.submit_typed(eid, "Entregado.", "req-1")
    assert sub["exercise_revision"] == 2 and fresh.attempts(eid)[0]["exercise_revision"] == 2
    complete(sub["submission_id"])
    attempt = fresh.start_revision(eid)[0]
    fresh.add_revision(eid, copy.deepcopy(L2), None, "otra aclaración", [])
    assert fresh.save_attempt_draft(attempt["attempt_id"], "Mejora.")["exercise_revision"] == 2
    assert fresh.submit_attempt(attempt["attempt_id"], "Mejora.", "req-2")[0]["exercise_revision"] == 2
    assert fresh.attempt(attempt["attempt_id"])["exercise_revision"] == 2


def test_handwritten_submissions_cannot_be_revised(fresh):
    sub = {"submission_id": "SUB-hand-1", "evidence_mode": "handwritten", "submitted_at": "2026-10-20T10:00:00Z"}
    fresh.add_submission(sub, L2["exercise_id"], handwritten_ref="scan-1.png")
    complete("SUB-hand-1")
    assert fresh.attempts(L2["exercise_id"])[0]["attempt_number"] == 1
    with pytest.raises(RevisionNotAllowed, match="typed"):
        fresh.start_revision(L2["exercise_id"])
