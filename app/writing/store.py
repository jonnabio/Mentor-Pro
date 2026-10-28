"""Producción escrita records in PostgreSQL (schema `writing`), ADR-019.

Single student, no profiles: submissions and evaluations belong to the one anonymous student, like
practice.*. Records are validated with app.writing.contracts before they are written; the full JSON
record is kept next to the indexed columns. Nothing here touches practice.* or curriculum.*.
Not wired into the application yet (no student writing screen); T021 generation writes here.
"""

from __future__ import annotations

import secrets
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.writing import contracts, migrations

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS writing;
CREATE TABLE IF NOT EXISTS writing.exercise (
    exercise_id       TEXT PRIMARY KEY,
    level             TEXT NOT NULL CHECK (level IN ('writing_conventions', 'idea_development', 'paragraph_writing',
                                                     'guided_composition', 'full_composition')),
    exercise_type     TEXT NOT NULL,
    difficulty        TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    evidence_mode     TEXT NOT NULL CHECK (evidence_mode IN ('typed', 'handwritten')),
    baseline_version  TEXT NOT NULL,
    rubric_id         TEXT NOT NULL,
    rubric_sha256     TEXT NOT NULL,
    target_criteria   TEXT[] NOT NULL,
    record            JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS writing.submission (
    submission_id     TEXT PRIMARY KEY,
    exercise_id       TEXT NOT NULL REFERENCES writing.exercise (exercise_id),
    evidence_mode     TEXT NOT NULL CHECK (evidence_mode IN ('typed', 'handwritten')),
    text_es           TEXT,
    handwritten_ref   TEXT,
    word_count        INTEGER CHECK (word_count >= 0),
    paragraph_count   INTEGER CHECK (paragraph_count >= 0),
    submitted_at      TIMESTAMPTZ NOT NULL,
    CHECK (evidence_mode <> 'typed' OR text_es IS NOT NULL),
    CHECK (evidence_mode <> 'handwritten' OR handwritten_ref IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS writing.evaluation (
    evaluation_id     TEXT PRIMARY KEY,
    submission_id     TEXT NOT NULL REFERENCES writing.submission (submission_id),
    status            TEXT NOT NULL CHECK (status IN ('pending', 'in_progress', 'completed', 'voided')),
    evaluator_role    TEXT NOT NULL CHECK (evaluator_role IN ('teacher', 'tutor', 'parent')),
    rubric_id         TEXT NOT NULL,
    rubric_sha256     TEXT NOT NULL,
    evaluated_at      TIMESTAMPTZ,
    feedback          JSONB NOT NULL,
    record            JSONB NOT NULL,
    CHECK (status <> 'completed' OR evaluated_at IS NOT NULL)
);
CREATE TABLE IF NOT EXISTS writing.criterion_score (
    evaluation_id     TEXT NOT NULL REFERENCES writing.evaluation (evaluation_id),
    criterion_code    TEXT NOT NULL CHECK (criterion_code ~ '^EE(0[1-9]|1[0-9]|20)$'),
    status            TEXT NOT NULL CHECK (status IN ('scored', 'not_evaluable', 'pending')),
    points            SMALLINT CHECK (points BETWEEN 0 AND 4),
    not_evaluable_reason TEXT,
    PRIMARY KEY (evaluation_id, criterion_code),
    CHECK ((status = 'scored') = (points IS NOT NULL)),
    CHECK (status <> 'not_evaluable' OR not_evaluable_reason IS NOT NULL)
);
-- T021 (ADR-020): one row per generation request; accepted exercises point back to their request.
ALTER TABLE writing.exercise ADD COLUMN IF NOT EXISTS generation_request_id TEXT;
CREATE TABLE IF NOT EXISTS writing.generation_attempt (
    request_id        TEXT PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    level             TEXT NOT NULL,
    difficulty        TEXT NOT NULL,
    target_criteria   TEXT[] NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('accepted', 'rejected', 'unavailable')),
    exercise_id       TEXT,
    models_used       TEXT[] NOT NULL,
    calls             INTEGER NOT NULL,
    tokens_in         INTEGER NOT NULL,
    tokens_out        INTEGER NOT NULL,
    cost_usd          NUMERIC(14, 8) NOT NULL,
    cost_complete     BOOLEAN NOT NULL,
    prompt_version    TEXT NOT NULL,
    checks            JSONB NOT NULL,
    review            JSONB,
    reasons           JSONB NOT NULL,
    exercise          JSONB
);
-- T022: the student's draft per exercise, and at most one submission per exercise (no resubmission yet).
CREATE TABLE IF NOT EXISTS writing.draft (
    exercise_id       TEXT PRIMARY KEY REFERENCES writing.exercise (exercise_id),
    text_es           TEXT NOT NULL,
    word_count        INTEGER NOT NULL CHECK (word_count >= 0),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE writing.submission ADD COLUMN IF NOT EXISTS client_request_id TEXT;
-- T036 (ADR-032): uq_submission_exercise (T022) is no longer created here; migration 0001_student_attempts replaces
-- it with one submission per student attempt (app/writing/migrations.py).
-- T023 (ADR-022): tutor-only reference correction of a correction exercise. Separate from writing.exercise,
-- whose record feeds the student API; no student endpoint reads this table.
CREATE TABLE IF NOT EXISTS writing.reference_correction (
    exercise_id        TEXT PRIMARY KEY REFERENCES writing.exercise (exercise_id),
    corrected_text_es  TEXT NOT NULL,
    corrections        JSONB NOT NULL,
    ambiguities_es     JSONB NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE writing.generation_attempt ADD COLUMN IF NOT EXISTS reference JSONB;
-- T024 (ADR-023): editorial revisions. writing.exercise.record and writing.reference_correction stay as
-- revision 1; later revisions live here with their tutor-only reference and validation results. The student
-- sees the latest revision, or the revision they submitted.
CREATE TABLE IF NOT EXISTS writing.exercise_revision (
    exercise_id   TEXT NOT NULL REFERENCES writing.exercise (exercise_id),
    revision      INTEGER NOT NULL CHECK (revision >= 2),
    record        JSONB NOT NULL,
    reference     JSONB,
    reason        TEXT NOT NULL,
    author        TEXT NOT NULL CHECK (author IN ('human_editor', 'generator')),
    checks        JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exercise_id, revision)
);
ALTER TABLE writing.submission ADD COLUMN IF NOT EXISTS exercise_revision INTEGER NOT NULL DEFAULT 1;
-- T026 (ADR-024): one tutor evaluation per submission, saved partially and completed once.
CREATE UNIQUE INDEX IF NOT EXISTS uq_evaluation_submission ON writing.evaluation (submission_id);
ALTER TABLE writing.evaluation ADD COLUMN IF NOT EXISTS exercise_revision INTEGER;
ALTER TABLE writing.evaluation ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE writing.criterion_score ADD COLUMN IF NOT EXISTS descriptor_ref TEXT;
-- T028 (ADR-026): guided composition (L4) keeps planning notes and each paragraph separately; text_es holds
-- the four paragraphs joined by a blank line.
ALTER TABLE writing.draft ADD COLUMN IF NOT EXISTS sections JSONB;
ALTER TABLE writing.submission ADD COLUMN IF NOT EXISTS sections JSONB;
-- T030 (ADR-028): ordering of draft saves (a delayed older save never overwrites newer text) and the exercise
-- revision the draft was written against.
ALTER TABLE writing.draft ADD COLUMN IF NOT EXISTS client_seq BIGINT;
ALTER TABLE writing.draft ADD COLUMN IF NOT EXISTS exercise_revision INTEGER;
-- T029 (ADR-027, RCA-004): append-only eligibility history; the latest event decides, no event = eligible.
CREATE TABLE IF NOT EXISTS writing.eligibility_event (
    event_id       BIGSERIAL PRIMARY KEY,
    exercise_id    TEXT NOT NULL REFERENCES writing.exercise (exercise_id),
    status         TEXT NOT NULL CHECK (status IN ('quarantined', 'eligible')),
    reason         TEXT NOT NULL,
    source         TEXT NOT NULL,
    validation_id  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Every independent revalidation, passed or not, with its models, results and costs.
CREATE TABLE IF NOT EXISTS writing.independent_validation (
    validation_id     TEXT PRIMARY KEY,
    exercise_id       TEXT NOT NULL REFERENCES writing.exercise (exercise_id),
    exercise_revision INTEGER NOT NULL,
    version           TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN ('passed', 'failed', 'unavailable')),
    generator_model   TEXT,
    reviewer_model    TEXT,
    checks            JSONB NOT NULL,
    review            JSONB,
    reasons           JSONB NOT NULL,
    request_id        TEXT NOT NULL,
    calls             INTEGER NOT NULL,
    tokens_in         INTEGER NOT NULL,
    tokens_out        INTEGER NOT NULL,
    cost_usd          NUMERIC(14, 8) NOT NULL,
    cost_complete     BOOLEAN NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (status <> 'passed' OR (reviewer_model IS NOT NULL AND reviewer_model IS DISTINCT FROM generator_model))
);
"""

ELIGIBLE_SQL = """COALESCE((SELECT ev.status FROM writing.eligibility_event ev WHERE ev.exercise_id = e.exercise_id
                     ORDER BY ev.event_id DESC LIMIT 1), 'eligible') = 'eligible'"""

GUIDED_PARAGRAPHS = ("introduction", "development_1", "development_2", "conclusion")
GUIDED_SECTIONS = ("plan",) + GUIDED_PARAGRAPHS


def assemble_sections(sections: dict[str, str]) -> str:
    """The composition as the tutor reads it: the four paragraphs in order, one blank line apart (no plan)."""
    return "\n\n".join(sections.get(k, "").strip() for k in GUIDED_PARAGRAPHS if sections.get(k, "").strip())

CURRENT_RECORD_SQL = """COALESCE((SELECT r.record FROM writing.exercise_revision r WHERE r.exercise_id = e.exercise_id
                             ORDER BY r.revision DESC LIMIT 1), e.record)"""
CURRENT_REVISION_SQL = """COALESCE((SELECT MAX(r.revision) FROM writing.exercise_revision r
                               WHERE r.exercise_id = e.exercise_id), 1)"""


def word_count(text: str) -> int:
    return len(text.split())


def paragraph_count(text: str) -> int:
    return len([p for p in text.splitlines() if p.strip()])


class EvaluationLocked(RuntimeError):
    """The submission already has a completed evaluation (T026)."""


class InvalidRecord(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class RevisionNotAllowed(RuntimeError):
    """A revision attempt cannot start (no completed evaluation yet, or the attempt limit is reached)."""


MAX_ATTEMPTS = 2  # ADR-032: the first increment allows one revision; the schema allows more


class WritingStore:
    def __init__(self, url: str):
        """Additive DDL only. T036: a database without writing tables is created at the current version; one with
        older writing tables is refused until `python -m app.writing.migrate apply` has run (never implicit)."""
        self.url = url
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(hashtext('bootstrap:writing'))")
            try:
                state = migrations.state(conn)
                if state == "legacy":
                    raise migrations.SchemaMigrationRequired(
                        "writing tables predate migration 0001_student_attempts; "
                        "run `python -m app.writing.migrate apply` after a verified backup")
                conn.execute(SCHEMA_SQL)
                if state == "fresh":
                    migrations.create_fresh(conn)
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtext('bootstrap:writing'))")

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.url, row_factory=dict_row)

    def add_exercise(self, exercise: dict[str, Any], generation_request_id: str | None = None,
                     reference: dict[str, Any] | None = None) -> None:
        problems = contracts.validate_exercise(exercise)
        if problems:
            raise InvalidRecord(problems)
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO writing.exercise (exercise_id, level, exercise_type, difficulty, evidence_mode,
                       baseline_version, rubric_id, rubric_sha256, target_criteria, record, generation_request_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (exercise["exercise_id"], exercise["level"], exercise["exercise_type"], exercise["difficulty"],
                 exercise["deliverable"]["evidence_mode"], exercise["provenance"]["baseline_version"],
                 exercise["evaluation"]["rubric_id"], exercise["evaluation"]["rubric_sha256"],
                 exercise["target_criteria"], Jsonb(exercise), generation_request_id))
            if reference is not None:
                conn.execute(
                    """INSERT INTO writing.reference_correction (exercise_id, corrected_text_es, corrections,
                           ambiguities_es) VALUES (%s, %s, %s, %s)""",
                    (exercise["exercise_id"], reference["corrected_text_es"], Jsonb(reference["corrections"]),
                     Jsonb(reference.get("ambiguities_es", []))))

    def reference_correction(self, exercise_id: str, revision: int | None = None) -> dict[str, Any] | None:
        """Tutor-only (never used by the student API): the reference of `revision`, default the latest."""
        with self._connect() as conn:
            revised = conn.execute(
                """SELECT revision, reference FROM writing.exercise_revision WHERE exercise_id = %s
                   AND reference IS NOT NULL AND (%s::int IS NULL OR revision <= %s)
                   ORDER BY revision DESC LIMIT 1""", (exercise_id, revision, revision)).fetchone()
            if revised and (revision is None or revision >= revised["revision"]):
                return {"exercise_id": exercise_id, "revision": revised["revision"], **revised["reference"]}
            row = conn.execute("SELECT * FROM writing.reference_correction WHERE exercise_id = %s",
                               (exercise_id,)).fetchone()
            return {**row, "revision": 1} if row else None

    def record(self, exercise_id: str, revision: int | None = None) -> dict[str, Any] | None:
        """The exercise record of `revision` (1 = the original record), default the latest."""
        with self._connect() as conn:
            if revision is None:
                row = conn.execute(f"SELECT {CURRENT_RECORD_SQL} AS record FROM writing.exercise e "
                                   "WHERE e.exercise_id = %s", (exercise_id,)).fetchone()
            elif revision == 1:
                row = conn.execute("SELECT record FROM writing.exercise WHERE exercise_id = %s",
                                   (exercise_id,)).fetchone()
            else:
                row = conn.execute("SELECT record FROM writing.exercise_revision WHERE exercise_id = %s "
                                   "AND revision = %s", (exercise_id, revision)).fetchone()
        return row["record"] if row else None

    def revisions(self, exercise_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.exercise_revision WHERE exercise_id = %s ORDER BY revision",
                                (exercise_id,)).fetchall()

    def add_revision(self, exercise_id: str, record: dict[str, Any], reference: dict[str, Any] | None,
                     reason: str, checks: list[dict[str, str]], author: str = "human_editor") -> int:
        """Append an editorial revision; earlier records, references and submissions are never changed."""
        problems = contracts.validate_exercise(record)
        failed = [c for c in checks if c["status"] == "fail"]
        if problems or failed or record["exercise_id"] != exercise_id:
            raise InvalidRecord(problems + [f"{c['id']}: {c['message']}" for c in failed]
                                or ["record is for another exercise"])
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            current = conn.execute("SELECT COALESCE(MAX(revision), 1) AS n FROM writing.exercise_revision "
                                   "WHERE exercise_id = %s", (exercise_id,)).fetchone()["n"]
            conn.execute(
                """INSERT INTO writing.exercise_revision (exercise_id, revision, record, reference, reason, author,
                       checks) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (exercise_id, current + 1, Jsonb(record), Jsonb(reference) if reference else None, reason, author,
                 Jsonb(checks)))
        return current + 1

    def source_texts(self, level: str) -> list[str]:
        """Texts to correct already stored for a level (near-duplicate check, T023)."""
        with self._connect() as conn:
            return [r["text"] for r in conn.execute(
                f"SELECT {CURRENT_RECORD_SQL}->>'source_text_es' AS text FROM writing.exercise e "
                "WHERE e.level = %s AND e.record ? 'source_text_es'", (level,))]

    def topics(self) -> list[str]:
        """Topics already stored, so generation does not repeat them."""
        with self._connect() as conn:
            return [r["topic"] for r in conn.execute("SELECT record->>'topic_es' AS topic FROM writing.exercise")]

    def add_generation_attempt(self, attempt: Any, level: str, difficulty: str, criteria: list[str],
                               prompt_version: str) -> None:
        """Generation metadata and validation history of one request (accepted, rejected or unavailable)."""
        summary = attempt.summary()
        exercise = attempt.exercise
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO writing.generation_attempt (request_id, level, difficulty, target_criteria, status,
                       exercise_id, models_used, calls, tokens_in, tokens_out, cost_usd, cost_complete,
                       prompt_version, checks, review, reasons, exercise, reference)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (attempt.request_id, level, difficulty, criteria, attempt.status,
                 exercise["exercise_id"] if exercise and attempt.status == "accepted" else None,
                 summary["models_used"], summary["calls"], summary["tokens_in"], summary["tokens_out"],
                 summary["cost_usd"], summary["cost_complete"], prompt_version, Jsonb(attempt.checks),
                 Jsonb(attempt.review) if attempt.review else None, Jsonb(attempt.reasons),
                 Jsonb(exercise) if exercise else None,
                 Jsonb(getattr(attempt, "reference", None)) if getattr(attempt, "reference", None) else None))

    # ------------------------------------------------------------ student writing (T022)

    def exercises(self, level: str | None = None, eligible_only: bool = True) -> list[dict[str, Any]]:
        """Stored (validated) exercises, oldest first, with the student's draft and submission state.
        T029: quarantined exercises are left out unless `eligible_only` is False."""
        with self._connect() as conn:
            return conn.execute(
                f"""SELECT e.exercise_id, e.level, e.difficulty, e.evidence_mode, {CURRENT_RECORD_SQL} AS record,
                          {CURRENT_REVISION_SQL} AS revision, e.created_at, {ELIGIBLE_SQL} AS eligible,
                          d.updated_at AS draft_saved_at, s.submission_id, s.submitted_at
                   FROM writing.exercise e
                   LEFT JOIN writing.student_attempt a ON a.exercise_id = e.exercise_id AND a.attempt_number = 1
                   LEFT JOIN writing.draft d ON d.attempt_id = a.attempt_id
                   LEFT JOIN writing.submission s ON s.attempt_id = a.attempt_id
                   WHERE (%(level)s::text IS NULL OR e.level = %(level)s) AND (NOT %(eligible_only)s OR {ELIGIBLE_SQL})
                   ORDER BY e.created_at, e.exercise_id""", {"level": level, "eligible_only": eligible_only}).fetchall()

    # ------------------------------------------------------------ eligibility (T029, RCA-004)

    def eligibility(self, exercise_id: str) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT status FROM writing.eligibility_event WHERE exercise_id = %s "
                               "ORDER BY event_id DESC LIMIT 1", (exercise_id,)).fetchone()
        return row["status"] if row else "eligible"

    def eligibility_events(self, exercise_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.eligibility_event WHERE %(id)s::text IS NULL "
                                "OR exercise_id = %(id)s ORDER BY event_id", {"id": exercise_id}).fetchall()

    def set_eligibility(self, exercise_id: str, status: str, reason: str, source: str,
                        validation_id: str | None = None) -> bool:
        """Append an event unless the exercise already has that status; True when one was added."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            current = conn.execute("SELECT status FROM writing.eligibility_event WHERE exercise_id = %s "
                                   "ORDER BY event_id DESC LIMIT 1", (exercise_id,)).fetchone()
            if (current["status"] if current else "eligible") == status:
                return False
            conn.execute("INSERT INTO writing.eligibility_event (exercise_id, status, reason, source, validation_id) "
                         "VALUES (%s, %s, %s, %s, %s)", (exercise_id, status, reason, source, validation_id))
            return True

    def add_validation(self, row: dict[str, Any]) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO writing.independent_validation (validation_id, exercise_id, exercise_revision, version,
                       status, generator_model, reviewer_model, checks, review, reasons, request_id, calls, tokens_in,
                       tokens_out, cost_usd, cost_complete)
                   VALUES (%(validation_id)s, %(exercise_id)s, %(exercise_revision)s, %(version)s, %(status)s,
                           %(generator_model)s, %(reviewer_model)s, %(checks)s, %(review)s, %(reasons)s,
                           %(request_id)s, %(calls)s, %(tokens_in)s, %(tokens_out)s, %(cost_usd)s, %(cost_complete)s)""",
                {**row, "checks": Jsonb(row["checks"]), "review": Jsonb(row["review"]) if row["review"] else None,
                 "reasons": Jsonb(row["reasons"])})

    def validations(self, exercise_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.independent_validation WHERE %(id)s::text IS NULL "
                                "OR exercise_id = %(id)s ORDER BY created_at", {"id": exercise_id}).fetchall()

    # T036 (ADR-032): every draft and submission belongs to a student attempt. The exercise-level methods below
    # (draft, submission, save_draft, submit_typed) are the T022 contract and always mean attempt 1: they never
    # select or write a later attempt. Attempt-level methods take an explicit attempt_id.

    @staticmethod
    def _current_revision(conn: psycopg.Connection, exercise_id: str) -> int:
        return conn.execute("SELECT COALESCE(MAX(revision), 1) AS n FROM writing.exercise_revision "
                            "WHERE exercise_id = %s", (exercise_id,)).fetchone()["n"]

    def _first_attempt(self, conn: psycopg.Connection, exercise_id: str, create: bool) -> dict[str, Any] | None:
        """Attempt 1 of an exercise; created on the first write (caller holds the exercise row lock)."""
        row = conn.execute("SELECT * FROM writing.student_attempt WHERE exercise_id = %s AND attempt_number = 1",
                           (exercise_id,)).fetchone()
        if row or not create:
            return row
        return conn.execute(
            """INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, exercise_revision)
               VALUES (%s, %s, 1, %s) RETURNING *""",
            (f"ATT-{exercise_id[3:40]}-1-{secrets.token_hex(4)}", exercise_id,
             self._current_revision(conn, exercise_id))).fetchone()

    def _lock_attempt(self, conn: psycopg.Connection, attempt_id: str) -> dict[str, Any] | None:
        """The attempt, after locking its exercise row (the lock every student write of that exercise takes)."""
        row = conn.execute("SELECT exercise_id FROM writing.student_attempt WHERE attempt_id = %s",
                           (attempt_id,)).fetchone()
        if row is None:
            return None
        conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (row["exercise_id"],))
        return conn.execute("SELECT * FROM writing.student_attempt WHERE attempt_id = %s", (attempt_id,)).fetchone()

    def attempts(self, exercise_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.student_attempt WHERE exercise_id = %s "
                                "ORDER BY attempt_number", (exercise_id,)).fetchall()

    def attempt(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.student_attempt WHERE attempt_id = %s",
                                (attempt_id,)).fetchone()

    def attempt_draft(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.draft WHERE attempt_id = %s", (attempt_id,)).fetchone()

    def attempt_submission(self, attempt_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.submission WHERE attempt_id = %s", (attempt_id,)).fetchone()

    def draft(self, exercise_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("""SELECT d.* FROM writing.draft d JOIN writing.student_attempt a USING (attempt_id)
                                   WHERE a.exercise_id = %s AND a.attempt_number = 1""", (exercise_id,)).fetchone()

    def submission(self, exercise_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("""SELECT s.* FROM writing.submission s
                                   JOIN writing.student_attempt a USING (attempt_id)
                                   WHERE a.exercise_id = %s AND a.attempt_number = 1""", (exercise_id,)).fetchone()

    def save_draft(self, exercise_id: str, text_es: str, sections: dict[str, str] | None = None,
                   client_seq: int | None = None) -> dict[str, Any] | None:
        """Upsert the draft of attempt 1; None when it was already submitted (drafts are then frozen).
        Guided compositions (T028) pass their sections; text_es is then the assembled paragraphs.
        T030: a save carrying a `client_seq` not newer than the stored one is stale (a delayed request) and
        changes nothing; the row is returned with `applied` False. Each save records the exercise revision."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            attempt = self._first_attempt(conn, exercise_id, create=True)
            return self._save_draft(conn, attempt, text_es, sections, client_seq)

    def save_attempt_draft(self, attempt_id: str, text_es: str, sections: dict[str, str] | None = None,
                           client_seq: int | None = None) -> dict[str, Any] | None:
        """save_draft for an explicit attempt; LookupError for an unknown attempt."""
        with self._connect() as conn, conn.transaction():
            attempt = self._lock_attempt(conn, attempt_id)
            if attempt is None:
                raise LookupError(attempt_id)
            return self._save_draft(conn, attempt, text_es, sections, client_seq)

    def _save_draft(self, conn: psycopg.Connection, attempt: dict[str, Any], text_es: str,
                    sections: dict[str, str] | None, client_seq: int | None) -> dict[str, Any] | None:
        attempt_id, exercise_id = attempt["attempt_id"], attempt["exercise_id"]
        if conn.execute("SELECT 1 FROM writing.submission WHERE attempt_id = %s", (attempt_id,)).fetchone():
            return None
        current = conn.execute("SELECT * FROM writing.draft WHERE attempt_id = %s", (attempt_id,)).fetchone()
        if current and client_seq is not None and current["client_seq"] is not None \
                and client_seq <= current["client_seq"]:
            return {**current, "applied": False}
        revision = self._attempt_revision(conn, attempt)
        row = conn.execute(
            """INSERT INTO writing.draft (attempt_id, exercise_id, text_es, word_count, sections, client_seq,
                   exercise_revision)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (attempt_id) DO UPDATE SET text_es = EXCLUDED.text_es,
                   word_count = EXCLUDED.word_count, sections = EXCLUDED.sections,
                   client_seq = COALESCE(EXCLUDED.client_seq, writing.draft.client_seq),
                   exercise_revision = EXCLUDED.exercise_revision, updated_at = now()
               RETURNING *""", (attempt_id, exercise_id, text_es, word_count(text_es),
                                Jsonb(sections) if sections is not None else None, client_seq,
                                revision)).fetchone()
        return {**row, "applied": True}

    def _attempt_revision(self, conn: psycopg.Connection, attempt: dict[str, Any]) -> int:
        """Attempt 1 follows the latest editorial revision until it is submitted (T024, ADR-023) and the attempt row
        records it; a revision attempt stays on the revision it was created with (ADR-032)."""
        if attempt["attempt_number"] > 1:
            return attempt["exercise_revision"]
        revision = self._current_revision(conn, attempt["exercise_id"])
        if revision != attempt["exercise_revision"]:
            conn.execute("UPDATE writing.student_attempt SET exercise_revision = %s WHERE attempt_id = %s",
                         (revision, attempt["attempt_id"]))
        return revision

    def submit_typed(self, exercise_id: str, text_es: str, client_request_id: str,
                     sections: dict[str, str] | None = None) -> tuple[dict[str, Any], bool]:
        """Store the one typed submission of attempt 1; repeated or parallel calls return the first."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            attempt = self._first_attempt(conn, exercise_id, create=True)
            return self._submit(conn, attempt, text_es, client_request_id, sections)

    def submit_attempt(self, attempt_id: str, text_es: str, client_request_id: str,
                       sections: dict[str, str] | None = None) -> tuple[dict[str, Any], bool]:
        """submit_typed for an explicit attempt; LookupError for an unknown attempt."""
        with self._connect() as conn, conn.transaction():
            attempt = self._lock_attempt(conn, attempt_id)
            if attempt is None:
                raise LookupError(attempt_id)
            return self._submit(conn, attempt, text_es, client_request_id, sections)

    def _submit(self, conn: psycopg.Connection, attempt: dict[str, Any], text_es: str, client_request_id: str,
                sections: dict[str, str] | None) -> tuple[dict[str, Any], bool]:
        attempt_id, exercise_id = attempt["attempt_id"], attempt["exercise_id"]
        existing = conn.execute("SELECT * FROM writing.submission WHERE attempt_id = %s", (attempt_id,)).fetchone()
        if existing:
            return existing, False
        revision = self._attempt_revision(conn, attempt)
        row = conn.execute(
            """INSERT INTO writing.submission (submission_id, exercise_id, attempt_id, evidence_mode, text_es,
                   word_count, paragraph_count, submitted_at, client_request_id, exercise_revision, sections)
               VALUES (%s, %s, %s, 'typed', %s, %s, %s, now(), %s, %s, %s) RETURNING *""",
            (f"SUB-{exercise_id[3:40]}-{secrets.token_hex(4)}", exercise_id, attempt_id, text_es,
             word_count(text_es), paragraph_count(text_es), client_request_id, revision,
             Jsonb(sections) if sections is not None else None)).fetchone()
        conn.execute("""INSERT INTO writing.draft (attempt_id, exercise_id, text_es, word_count, sections)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (attempt_id) DO UPDATE SET text_es = EXCLUDED.text_es,
                            word_count = EXCLUDED.word_count, sections = EXCLUDED.sections, updated_at = now()""",
                     (attempt_id, exercise_id, text_es, word_count(text_es),
                      Jsonb(sections) if sections is not None else None))
        return row, True

    def start_revision(self, exercise_id: str) -> tuple[dict[str, Any], bool]:
        """Persistence for a revision attempt (no student action calls this yet; T037). Allowed only after the
        latest attempt's submission has a completed evaluation, up to MAX_ATTEMPTS. The new draft is seeded once
        from that submission (L1: the student's correction, not the source text; L4: all five sections). A
        repeated or parallel call returns the open revision attempt (created False) and never re-seeds it."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            latest = conn.execute("SELECT * FROM writing.student_attempt WHERE exercise_id = %s "
                                  "ORDER BY attempt_number DESC LIMIT 1", (exercise_id,)).fetchone()
            if latest is None:
                raise RevisionNotAllowed("no submitted attempt")
            submitted = conn.execute("SELECT * FROM writing.submission WHERE attempt_id = %s",
                                     (latest["attempt_id"],)).fetchone()
            if submitted is None:
                if latest["attempt_number"] > 1:
                    return latest, False
                raise RevisionNotAllowed("the first attempt is not submitted")
            if submitted["evidence_mode"] != "typed":
                raise RevisionNotAllowed("only typed submissions can be revised")
            evaluation = conn.execute("SELECT status FROM writing.evaluation WHERE submission_id = %s",
                                      (submitted["submission_id"],)).fetchone()
            if evaluation is None or evaluation["status"] != "completed":
                raise RevisionNotAllowed("the tutor evaluation is not completed")
            if latest["attempt_number"] >= MAX_ATTEMPTS:
                raise RevisionNotAllowed("attempt limit reached")
            number = latest["attempt_number"] + 1
            attempt = conn.execute(
                """INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, previous_attempt_id,
                       exercise_revision) VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (f"ATT-{exercise_id[3:40]}-{number}-{secrets.token_hex(4)}", exercise_id, number,
                 latest["attempt_id"], submitted["exercise_revision"])).fetchone()
            conn.execute("""INSERT INTO writing.draft (attempt_id, exercise_id, text_es, word_count, sections,
                                exercise_revision) VALUES (%s, %s, %s, %s, %s, %s)""",
                         (attempt["attempt_id"], exercise_id, submitted["text_es"], word_count(submitted["text_es"]),
                          Jsonb(submitted["sections"]) if submitted["sections"] is not None else None,
                          submitted["exercise_revision"]))
            return attempt, True

    # ------------------------------------------------------------ tutor evaluation (T026)

    def submission_by_id(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.submission WHERE submission_id = %s",
                                (submission_id,)).fetchone()

    def tutor_queue(self) -> list[dict[str, Any]]:
        """Every submission with its evaluation status (pending when no evaluation exists), oldest first."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT s.submission_id, s.exercise_id, s.exercise_revision, s.submitted_at, s.evidence_mode,
                          e.level, COALESCE(v.status, 'pending') AS status, v.evaluated_at, v.updated_at,
                          a.attempt_number
                   FROM writing.submission s JOIN writing.exercise e USING (exercise_id)
                   JOIN writing.student_attempt a USING (attempt_id)
                   LEFT JOIN writing.evaluation v USING (submission_id)
                   ORDER BY s.submitted_at""").fetchall()

    def evaluation_for(self, submission_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.evaluation WHERE submission_id = %s",
                                (submission_id,)).fetchone()

    def save_evaluation(self, evaluation: dict[str, Any], exercise: dict[str, Any], exercise_revision: int) -> None:
        """Insert or update the one evaluation of a submission; a completed evaluation is never changed."""
        problems = contracts.validate_evaluation(evaluation, exercise)
        if problems:
            raise InvalidRecord(problems)
        sid = evaluation["submission"]["submission_id"]
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.submission WHERE submission_id = %s FOR UPDATE", (sid,))
            existing = conn.execute("SELECT evaluation_id, status FROM writing.evaluation WHERE submission_id = %s",
                                    (sid,)).fetchone()
            if existing and existing["status"] == "completed":
                raise EvaluationLocked(sid)
            if existing and existing["evaluation_id"] != evaluation["evaluation_id"]:
                evaluation = {**evaluation, "evaluation_id": existing["evaluation_id"]}
            values = (evaluation["status"], evaluation["evaluator"]["role"], evaluation["rubric_id"],
                      evaluation["rubric_sha256"], evaluation.get("evaluated_at"), Jsonb(evaluation["feedback_es"]),
                      Jsonb(evaluation), exercise_revision)
            if existing:
                conn.execute(
                    """UPDATE writing.evaluation SET status = %s, evaluator_role = %s, rubric_id = %s, rubric_sha256 = %s,
                           evaluated_at = %s, feedback = %s, record = %s, exercise_revision = %s, updated_at = now()
                       WHERE evaluation_id = %s""", values + (evaluation["evaluation_id"],))
                conn.execute("DELETE FROM writing.criterion_score WHERE evaluation_id = %s",
                             (evaluation["evaluation_id"],))
            else:
                conn.execute(
                    """INSERT INTO writing.evaluation (status, evaluator_role, rubric_id, rubric_sha256, evaluated_at,
                           feedback, record, exercise_revision, evaluation_id, submission_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    values + (evaluation["evaluation_id"], sid))
            for score in evaluation["criterion_scores"]:
                conn.execute(
                    """INSERT INTO writing.criterion_score (evaluation_id, criterion_code, status, points,
                           not_evaluable_reason, descriptor_ref) VALUES (%s, %s, %s, %s, %s, %s)""",
                    (evaluation["evaluation_id"], score["criterion"], score["status"], score.get("points"),
                     score.get("not_evaluable_reason"),
                     f"{evaluation['rubric_id']}#{score['criterion']}@{score['points']}"
                     if score.get("points") is not None else None))

    # ------------------------------------------------------------ student progress (T027)

    PROGRESS_SQL = """
        SELECT s.submission_id, s.submitted_at, e.level, v.status AS evaluation_status, v.record AS evaluation,
               COALESCE((SELECT r.record FROM writing.exercise_revision r WHERE r.exercise_id = s.exercise_id
                         AND r.revision = s.exercise_revision), e.record)->'evaluation'->'parameters' AS parameters
        FROM writing.submission s JOIN writing.exercise e USING (exercise_id)
        LEFT JOIN writing.evaluation v USING (submission_id)
        ORDER BY s.submitted_at"""

    def progress_inputs(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        """Read-only: completed evaluation records, every submission with its evaluation status and scorable
        criteria (from the exercise revision answered), and the last draft save."""
        with self._connect() as conn:
            rows = conn.execute(self.PROGRESS_SQL).fetchall()
            last_draft = conn.execute("SELECT MAX(updated_at) AS at FROM writing.draft").fetchone()["at"]
        submissions = [{"submission_id": r["submission_id"], "submitted_at": r["submitted_at"].isoformat(),
                        "level": r["level"], "evaluation_status": r["evaluation_status"],
                        "scorable_criteria": [p["criterion"] for p in r["parameters"]
                                              if p["applicability"] == "scored" and not p.get("optional")]}
                       for r in rows]
        evaluations = [r["evaluation"] for r in rows if r["evaluation_status"] == "completed"]
        return evaluations, submissions, last_draft.isoformat() if last_draft else None

    def generation_attempts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.generation_attempt ORDER BY created_at").fetchall()

    def exercise(self, exercise_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT record FROM writing.exercise WHERE exercise_id = %s", (exercise_id,)).fetchone()
        return row["record"] if row else None

    def add_submission(self, submission: dict[str, Any], exercise_id: str, text_es: str | None = None,
                       handwritten_ref: str | None = None) -> None:
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            attempt = self._first_attempt(conn, exercise_id, create=True)
            conn.execute(
                """INSERT INTO writing.submission (submission_id, exercise_id, attempt_id, evidence_mode, text_es,
                       handwritten_ref, word_count, paragraph_count, submitted_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (submission["submission_id"], exercise_id, attempt["attempt_id"] if attempt else None,
                 submission["evidence_mode"], text_es, handwritten_ref, submission.get("word_count"),
                 submission.get("paragraph_count"), submission["submitted_at"]))

    def add_evaluation(self, evaluation: dict[str, Any]) -> None:
        exercise = self.exercise(evaluation["exercise_id"])
        if exercise is None:
            raise InvalidRecord([f"unknown exercise {evaluation['exercise_id']}"])
        problems = contracts.validate_evaluation(evaluation, exercise)
        if problems:
            raise InvalidRecord(problems)
        with self._connect() as conn, conn.transaction():
            conn.execute(
                """INSERT INTO writing.evaluation (evaluation_id, submission_id, status, evaluator_role, rubric_id,
                       rubric_sha256, evaluated_at, feedback, record)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (evaluation["evaluation_id"], evaluation["submission"]["submission_id"], evaluation["status"],
                 evaluation["evaluator"]["role"], evaluation["rubric_id"], evaluation["rubric_sha256"],
                 evaluation.get("evaluated_at"), Jsonb(evaluation["feedback_es"]), Jsonb(evaluation)))
            for score in evaluation["criterion_scores"]:
                conn.execute(
                    """INSERT INTO writing.criterion_score (evaluation_id, criterion_code, status, points,
                           not_evaluable_reason) VALUES (%s, %s, %s, %s, %s)""",
                    (evaluation["evaluation_id"], score["criterion"], score["status"], score.get("points"),
                     score.get("not_evaluable_reason")))

    def evaluations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT record FROM writing.evaluation ORDER BY evaluated_at NULLS LAST").fetchall()
        return [r["record"] for r in rows]
