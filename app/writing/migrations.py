"""Versioned migrations of the `writing` schema (T036, ADR-032).

`WritingStore.__init__` only runs additive DDL (SCHEMA_SQL). Changes that rewrite keys or move student records run
here, invoked explicitly (`python -m app.writing.migrate`), never implicitly on a database holding writing tables.
The one exception is a database without writing tables at all: the store creates it directly at the current
version (there is nothing to transform).

0001_student_attempts: one `writing.student_attempt` per student attempt at an exercise. Attempt 1 is backfilled for
every exercise with a draft or submission; drafts become one per attempt and submissions one per attempt (was one per
exercise). Draft, submission, evaluation and criterion_score rows are compared before and after (all columns except
the new `attempt_id`); any difference or anomaly rolls the whole transaction back. Reports hold counts and digests,
never student text.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext('bootstrap:writing'))"
STUDENT_ATTEMPTS = "0001_student_attempts"

LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS writing.schema_migration (
    migration_id  TEXT PRIMARY KEY,
    applied_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode          TEXT NOT NULL CHECK (mode IN ('fresh', 'migrated')),
    report        JSONB NOT NULL
);
"""

# Ordered by the keys that are unique before and after the migration; the new attempt_id column is left out.
FINGERPRINT_SQL = {
    "draft": "SELECT count(*) AS n, md5(COALESCE(string_agg((to_jsonb(t) - 'attempt_id')::text, '|' "
             "ORDER BY t.exercise_id), '')) AS digest FROM writing.draft t",
    "submission": "SELECT count(*) AS n, md5(COALESCE(string_agg((to_jsonb(t) - 'attempt_id')::text, '|' "
                  "ORDER BY t.submission_id), '')) AS digest FROM writing.submission t",
    "evaluation": "SELECT count(*) AS n, md5(COALESCE(string_agg(to_jsonb(t)::text, '|' "
                  "ORDER BY t.evaluation_id), '')) AS digest FROM writing.evaluation t",
    "criterion_score": "SELECT count(*) AS n, md5(COALESCE(string_agg(to_jsonb(t)::text, '|' "
                       "ORDER BY t.evaluation_id, t.criterion_code), '')) AS digest FROM writing.criterion_score t",
}

ATTEMPT_TABLE_SQL = """
CREATE TABLE writing.student_attempt (
    attempt_id           TEXT PRIMARY KEY,
    exercise_id          TEXT NOT NULL REFERENCES writing.exercise (exercise_id),
    attempt_number       INTEGER NOT NULL CHECK (attempt_number >= 1),
    previous_attempt_id  TEXT,
    exercise_revision    INTEGER NOT NULL CHECK (exercise_revision >= 1),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_attempt_exercise_number UNIQUE (exercise_id, attempt_number),
    CONSTRAINT uq_attempt_exercise UNIQUE (attempt_id, exercise_id),
    CONSTRAINT uq_attempt_previous UNIQUE (previous_attempt_id),
    CONSTRAINT ck_attempt_first_has_no_previous CHECK ((attempt_number = 1) = (previous_attempt_id IS NULL)),
    CONSTRAINT fk_attempt_previous_same_exercise FOREIGN KEY (previous_attempt_id, exercise_id)
        REFERENCES writing.student_attempt (attempt_id, exercise_id)
);
ALTER TABLE writing.draft ADD COLUMN attempt_id TEXT;
ALTER TABLE writing.submission ADD COLUMN attempt_id TEXT;
"""

# Attempt 1 per exercise with student work. Revision: the submission's, else the draft's, else the current one
# (ADR-032). created_at: the earliest timestamp recorded for that work (drafts keep only their last save).
BACKFILL_SQL = """
WITH work AS (
    SELECT e.exercise_id, s.exercise_revision AS submitted_revision, d.exercise_revision AS draft_revision,
           LEAST(s.submitted_at, d.updated_at) AS first_seen,
           COALESCE((SELECT MAX(r.revision) FROM writing.exercise_revision r WHERE r.exercise_id = e.exercise_id), 1)
               AS current_revision
    FROM writing.exercise e
    LEFT JOIN writing.submission s ON s.exercise_id = e.exercise_id
    LEFT JOIN writing.draft d ON d.exercise_id = e.exercise_id
    WHERE s.submission_id IS NOT NULL OR d.exercise_id IS NOT NULL
)
INSERT INTO writing.student_attempt (attempt_id, exercise_id, attempt_number, previous_attempt_id, exercise_revision,
                                     created_at)
SELECT 'ATT-' || substr(exercise_id, 4, 37) || '-1-' || substr(md5(exercise_id), 1, 8), exercise_id, 1, NULL,
       COALESCE(submitted_revision, draft_revision, current_revision), first_seen
FROM work;
UPDATE writing.draft d SET attempt_id = a.attempt_id FROM writing.student_attempt a
    WHERE a.exercise_id = d.exercise_id AND a.attempt_number = 1;
UPDATE writing.submission s SET attempt_id = a.attempt_id FROM writing.student_attempt a
    WHERE a.exercise_id = s.exercise_id AND a.attempt_number = 1;
"""

CONSTRAIN_SQL = """
ALTER TABLE writing.draft ALTER COLUMN attempt_id SET NOT NULL;
ALTER TABLE writing.submission ALTER COLUMN attempt_id SET NOT NULL;
ALTER TABLE writing.draft ADD CONSTRAINT fk_draft_attempt FOREIGN KEY (attempt_id, exercise_id)
    REFERENCES writing.student_attempt (attempt_id, exercise_id);
ALTER TABLE writing.submission ADD CONSTRAINT fk_submission_attempt FOREIGN KEY (attempt_id, exercise_id)
    REFERENCES writing.student_attempt (attempt_id, exercise_id);
ALTER TABLE writing.draft DROP CONSTRAINT {draft_pk};
ALTER TABLE writing.draft ADD CONSTRAINT draft_pkey PRIMARY KEY (attempt_id);
CREATE INDEX ix_draft_exercise ON writing.draft (exercise_id);
CREATE UNIQUE INDEX uq_submission_attempt ON writing.submission (attempt_id);
DROP INDEX IF EXISTS writing.uq_submission_exercise;
CREATE INDEX ix_submission_exercise ON writing.submission (exercise_id);
"""

ROLLBACK_SQL = """
DROP INDEX writing.ix_submission_exercise;
DROP INDEX writing.uq_submission_attempt;
CREATE UNIQUE INDEX IF NOT EXISTS uq_submission_exercise ON writing.submission (exercise_id);
DROP INDEX writing.ix_draft_exercise;
ALTER TABLE writing.draft DROP CONSTRAINT draft_pkey;
ALTER TABLE writing.draft ADD CONSTRAINT draft_pkey PRIMARY KEY (exercise_id);
ALTER TABLE writing.draft DROP COLUMN attempt_id;
ALTER TABLE writing.submission DROP COLUMN attempt_id;
DROP TABLE writing.student_attempt;
DELETE FROM writing.schema_migration WHERE migration_id = '0001_student_attempts';
"""


class MigrationError(RuntimeError):
    """A precondition or post-migration check failed; nothing was changed."""


class SchemaMigrationRequired(RuntimeError):
    """The database holds writing tables older than this code; run `python -m app.writing.migrate apply`."""


def _exists(conn: psycopg.Connection, relation: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (relation,)).fetchone()[0]


def is_applied(conn: psycopg.Connection, migration_id: str = STUDENT_ATTEMPTS) -> bool:
    return _exists(conn, "writing.schema_migration") and conn.execute(
        "SELECT 1 FROM writing.schema_migration WHERE migration_id = %s", (migration_id,)).fetchone() is not None


def state(conn: psycopg.Connection) -> str:
    """'fresh' (no student tables yet), 'legacy' (needs the migration), 'drifted' (migrated, but a pre-T036 image
    has since recreated uq_submission_exercise, which would block revision submissions) or 'current'."""
    if not _exists(conn, "writing.draft"):
        return "fresh"
    if not is_applied(conn):
        return "legacy"
    return "drifted" if _exists(conn, "writing.uq_submission_exercise") else "current"


REFUSALS = {
    "legacy": "writing tables predate migration 0001_student_attempts; "
              "run `python -m app.writing.migrate apply` after a verified backup",
    "drifted": "uq_submission_exercise was recreated after migration 0001_student_attempts (an older image ran on "
               "this database); run `python -m app.writing.migrate repair`",
}


def refuse_unless_current(conn: psycopg.Connection) -> str:
    """The startup check of the application and tutor service; returns the state when it may start."""
    current = state(conn)
    if current in REFUSALS:
        raise SchemaMigrationRequired(REFUSALS[current])
    return current


def fingerprints(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    return {table: dict(zip(("count", "digest"), conn.execute(query).fetchone()))
            for table, query in FINGERPRINT_SQL.items()}


def _preconditions(conn: psycopg.Connection) -> list[str]:
    problems = []
    for label, query in (
            ("exercises with more than one submission",
             "SELECT count(*) FROM (SELECT exercise_id FROM writing.submission GROUP BY exercise_id "
             "HAVING count(*) > 1) x"),
            ("drafts or submissions of an unknown exercise",
             "SELECT (SELECT count(*) FROM writing.draft d WHERE NOT EXISTS (SELECT 1 FROM writing.exercise e "
             "WHERE e.exercise_id = d.exercise_id)) + (SELECT count(*) FROM writing.submission s WHERE NOT EXISTS "
             "(SELECT 1 FROM writing.exercise e WHERE e.exercise_id = s.exercise_id))"),
            ("evaluations of an unknown submission",
             "SELECT count(*) FROM writing.evaluation v WHERE NOT EXISTS (SELECT 1 FROM writing.submission s "
             "WHERE s.submission_id = v.submission_id)")):
        n = conn.execute(query).fetchone()[0]
        if n:
            problems.append(f"{n} {label}")
    return problems


def _validate(conn: psycopg.Connection, before: dict[str, dict[str, Any]]) -> list[str]:
    problems = []
    after = fingerprints(conn)
    problems += [f"{t} changed during the migration" for t in before if before[t] != after[t]]
    for label, query in (
            ("drafts without attempt", "SELECT count(*) FROM writing.draft WHERE attempt_id IS NULL"),
            ("submissions without attempt", "SELECT count(*) FROM writing.submission WHERE attempt_id IS NULL"),
            ("attempts whose exercise differs from their draft or submission",
             "SELECT (SELECT count(*) FROM writing.draft d JOIN writing.student_attempt a USING (attempt_id) "
             "WHERE a.exercise_id <> d.exercise_id) + (SELECT count(*) FROM writing.submission s "
             "JOIN writing.student_attempt a USING (attempt_id) WHERE a.exercise_id <> s.exercise_id)"),
            ("attempts without draft or submission",
             "SELECT count(*) FROM writing.student_attempt a WHERE NOT EXISTS (SELECT 1 FROM writing.draft d "
             "WHERE d.attempt_id = a.attempt_id) AND NOT EXISTS (SELECT 1 FROM writing.submission s "
             "WHERE s.attempt_id = a.attempt_id)"),
            ("attempts whose revision differs from their submission",
             "SELECT count(*) FROM writing.submission s JOIN writing.student_attempt a USING (attempt_id) "
             "WHERE a.exercise_revision <> s.exercise_revision")):
        n = conn.execute(query).fetchone()[0]
        if n:
            problems.append(f"{n} {label}")
    return problems


def _apply(conn: psycopg.Connection, mode: str) -> dict[str, Any]:
    """Runs inside the caller's transaction; raises MigrationError (caller rolls back) on any problem."""
    conn.execute(LOCK_SQL)
    conn.execute(LEDGER_SQL)
    if is_applied(conn):
        return {"migration": STUDENT_ATTEMPTS, "status": "already_applied"}
    conn.execute("LOCK TABLE writing.draft, writing.submission, writing.evaluation, writing.criterion_score "
                 "IN ACCESS EXCLUSIVE MODE")
    problems = _preconditions(conn)
    if problems:
        raise MigrationError("; ".join(problems))
    before = fingerprints(conn)
    conn.execute(ATTEMPT_TABLE_SQL)
    conn.execute(BACKFILL_SQL)
    problems = _validate(conn, before)
    if problems:
        raise MigrationError("; ".join(problems))
    draft_pk = conn.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'writing.draft'::regclass "
                            "AND contype = 'p'").fetchone()[0]
    conn.execute(CONSTRAIN_SQL.format(draft_pk=sql.Identifier(draft_pk).as_string(conn)))
    attempts = conn.execute("SELECT count(*) FROM writing.student_attempt").fetchone()[0]
    revision_notes = conn.execute(
        "SELECT count(*) FROM writing.draft d JOIN writing.submission s USING (attempt_id) "
        "WHERE d.exercise_revision IS DISTINCT FROM s.exercise_revision").fetchone()[0]
    report = {"migration": STUDENT_ATTEMPTS, "status": "applied", "mode": mode, "attempts_created": attempts,
              "before": before, "after": fingerprints(conn),
              # informational: drafts keep the revision of their last save; the attempt takes the submission's
              "drafts_with_other_revision_than_submission": revision_notes}
    conn.execute("INSERT INTO writing.schema_migration (migration_id, mode, report) VALUES (%s, %s, %s)",
                 (STUDENT_ATTEMPTS, mode, Jsonb(report)))
    return report


def create_fresh(conn: psycopg.Connection) -> None:
    """Startup on a database whose writing tables were just created empty: bring them to the current version."""
    with conn.transaction():
        _apply(conn, "fresh")


def apply(url: str, dry_run: bool = False) -> dict[str, Any]:
    """Explicit migration of an existing database. All or nothing; a dry run reports and rolls back."""
    with psycopg.connect(url) as conn:
        if not _exists(conn, "writing.draft"):
            raise MigrationError("no writing tables in this database (the application creates them)")
        try:
            with conn.transaction():
                report = _apply(conn, "migrated")
                if dry_run:
                    raise _DryRun(report)
        except _DryRun as done:
            return {**done.report, "status": "dry_run_rolled_back"}
    return report


def repair(url: str) -> dict[str, Any]:
    """Remove a uq_submission_exercise recreated by an older image; nothing else changes."""
    with psycopg.connect(url) as conn, conn.transaction():
        conn.execute(LOCK_SQL)
        if state(conn) != "drifted":
            raise MigrationError(f"nothing to repair (state {state(conn)})")
        before = fingerprints(conn)
        conn.execute("DROP INDEX writing.uq_submission_exercise")
        return {"migration": STUDENT_ATTEMPTS, "status": "repaired", "before": before, "after": fingerprints(conn)}


def rollback(url: str) -> dict[str, Any]:
    """Undo 0001 while every exercise still has only attempt 1; refused once a revision attempt exists."""
    with psycopg.connect(url) as conn, conn.transaction():
        conn.execute(LOCK_SQL)
        if not is_applied(conn):
            raise MigrationError("0001_student_attempts is not applied")
        conn.execute("LOCK TABLE writing.student_attempt, writing.draft, writing.submission, writing.evaluation, "
                     "writing.criterion_score IN ACCESS EXCLUSIVE MODE")
        later = conn.execute("SELECT count(*) FROM writing.student_attempt WHERE attempt_number > 1").fetchone()[0]
        if later:
            raise MigrationError(f"{later} revision attempts exist; the one-submission-per-exercise schema cannot "
                                 "hold them (restore the pre-migration backup instead, ADR-032)")
        before = fingerprints(conn)
        conn.execute(ROLLBACK_SQL)
        after = fingerprints(conn)
        if before != after:
            raise MigrationError("student records changed during the rollback")
        return {"migration": STUDENT_ATTEMPTS, "status": "rolled_back", "before": before, "after": after}


class _DryRun(Exception):
    def __init__(self, report: dict[str, Any]):
        super().__init__("dry run")
        self.report = report
