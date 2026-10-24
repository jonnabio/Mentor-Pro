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

from app.writing import contracts

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
CREATE UNIQUE INDEX IF NOT EXISTS uq_submission_exercise ON writing.submission (exercise_id);
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
"""


def word_count(text: str) -> int:
    return len(text.split())


def paragraph_count(text: str) -> int:
    return len([p for p in text.splitlines() if p.strip()])


class InvalidRecord(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class WritingStore:
    def __init__(self, url: str):
        self.url = url
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("SELECT pg_advisory_lock(hashtext('bootstrap:writing'))")
            try:
                conn.execute(SCHEMA_SQL)
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

    def reference_correction(self, exercise_id: str) -> dict[str, Any] | None:
        """Tutor-only; never used by the student API (app/writing/routes.py)."""
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.reference_correction WHERE exercise_id = %s",
                                (exercise_id,)).fetchone()

    def source_texts(self, level: str) -> list[str]:
        """Texts to correct already stored for a level (near-duplicate check, T023)."""
        with self._connect() as conn:
            return [r["text"] for r in conn.execute(
                "SELECT record->>'source_text_es' AS text FROM writing.exercise WHERE level = %s "
                "AND record ? 'source_text_es'", (level,))]

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

    def exercises(self, level: str | None = None) -> list[dict[str, Any]]:
        """Stored (validated) exercises, oldest first, with the student's draft and submission state."""
        with self._connect() as conn:
            return conn.execute(
                """SELECT e.exercise_id, e.level, e.difficulty, e.evidence_mode, e.record, e.created_at,
                          d.updated_at AS draft_saved_at, s.submission_id, s.submitted_at
                   FROM writing.exercise e
                   LEFT JOIN writing.draft d USING (exercise_id)
                   LEFT JOIN writing.submission s USING (exercise_id)
                   WHERE %(level)s::text IS NULL OR e.level = %(level)s
                   ORDER BY e.created_at, e.exercise_id""", {"level": level}).fetchall()

    def draft(self, exercise_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.draft WHERE exercise_id = %s", (exercise_id,)).fetchone()

    def submission(self, exercise_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM writing.submission WHERE exercise_id = %s", (exercise_id,)).fetchone()

    def save_draft(self, exercise_id: str, text_es: str) -> dict[str, Any] | None:
        """Upsert the draft; None when the exercise was already submitted (drafts are then frozen)."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            if conn.execute("SELECT 1 FROM writing.submission WHERE exercise_id = %s", (exercise_id,)).fetchone():
                return None
            return conn.execute(
                """INSERT INTO writing.draft (exercise_id, text_es, word_count) VALUES (%s, %s, %s)
                   ON CONFLICT (exercise_id) DO UPDATE SET text_es = EXCLUDED.text_es,
                       word_count = EXCLUDED.word_count, updated_at = now()
                   RETURNING *""", (exercise_id, text_es, word_count(text_es))).fetchone()

    def submit_typed(self, exercise_id: str, text_es: str, client_request_id: str) -> tuple[dict[str, Any], bool]:
        """Store the one typed submission of an exercise; repeated or parallel calls return the first."""
        with self._connect() as conn, conn.transaction():
            conn.execute("SELECT 1 FROM writing.exercise WHERE exercise_id = %s FOR UPDATE", (exercise_id,))
            existing = conn.execute("SELECT * FROM writing.submission WHERE exercise_id = %s",
                                    (exercise_id,)).fetchone()
            if existing:
                return existing, False
            row = conn.execute(
                """INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count,
                       paragraph_count, submitted_at, client_request_id)
                   VALUES (%s, %s, 'typed', %s, %s, %s, now(), %s) RETURNING *""",
                (f"SUB-{exercise_id[3:40]}-{secrets.token_hex(4)}", exercise_id, text_es, word_count(text_es),
                 paragraph_count(text_es), client_request_id)).fetchone()
            conn.execute("""INSERT INTO writing.draft (exercise_id, text_es, word_count) VALUES (%s, %s, %s)
                            ON CONFLICT (exercise_id) DO UPDATE SET text_es = EXCLUDED.text_es,
                                word_count = EXCLUDED.word_count, updated_at = now()""",
                         (exercise_id, text_es, word_count(text_es)))
            return row, True

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
            conn.execute(
                """INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, handwritten_ref,
                       word_count, paragraph_count, submitted_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (submission["submission_id"], exercise_id, submission["evidence_mode"], text_es, handwritten_ref,
                 submission.get("word_count"), submission.get("paragraph_count"), submission["submitted_at"]))

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
