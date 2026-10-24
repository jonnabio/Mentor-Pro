"""Producción escrita records in PostgreSQL (schema `writing`), ADR-019.

Single student, no profiles: submissions and evaluations belong to the one anonymous student, like
practice.*. Records are validated with app.writing.contracts before they are written; the full JSON
record is kept next to the indexed columns. Nothing here touches practice.* or curriculum.*.
Not wired into the application yet (no student writing screen); T021 generation writes here.
"""

from __future__ import annotations

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
"""


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

    def add_exercise(self, exercise: dict[str, Any], generation_request_id: str | None = None) -> None:
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
                       prompt_version, checks, review, reasons, exercise)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (attempt.request_id, level, difficulty, criteria, attempt.status,
                 exercise["exercise_id"] if exercise and attempt.status == "accepted" else None,
                 summary["models_used"], summary["calls"], summary["tokens_in"], summary["tokens_out"],
                 summary["cost_usd"], summary["cost_complete"], prompt_version, Jsonb(attempt.checks),
                 Jsonb(attempt.review) if attempt.review else None, Jsonb(attempt.reasons),
                 Jsonb(exercise) if exercise else None))

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
