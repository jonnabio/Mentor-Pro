# ADR-017: Practice Session Classification

> **Status:** Accepted (Product Owner task T017)
> **Date:** 2026-10-24

---

## Context

T016 (ADR-016) stopped new automated runs from reaching the student
database, but 117 historical test sessions remain there and the learning
dashboard (ADR-015) counts their answers. The Product Owner approved
excluding the 103 confirmed test sessions, quarantining the 14 ambiguous
ones, and keeping the 2 presumed student sessions, without deleting
anything.

---

## Decision

### Classification table (`practice` schema)

```sql
practice.session_classification (
    session_id      TEXT PRIMARY KEY REFERENCES practice.session,
    classification  TEXT CHECK (classification IN ('student', 'automated_test', 'quarantined')),
    reason          TEXT NOT NULL,
    audit_ref       TEXT NOT NULL,
    classified_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)
practice.classification_audit (append-only: session, previous, new, reason, audit_ref, action, at)
```

A session without a row is a student session. Exclusion depends on the
session's recorded classification, never on question IDs. Sessions,
items and answers are never changed or deleted.

### Where exclusion applies

- `app/practice/mastery.py` `ANSWERS_SQL`: answers from sessions classified
  `automated_test` or `quarantined` are filtered out before the window that
  numbers attempts, so first attempts, repeats, accuracy and statuses are
  recomputed from student activity only.
- `app/practice/bank.py` `seen_questions`: exposure history (freshness
  preference when composing practices) uses student sessions only. Bank
  eligibility is unchanged.

### Applying a classification

`scripts/dev/classify_sessions.py` (dry run by default):

- recomputes the T016 classes with `test_data_report.classify` and compares
  them with the frozen manifest `docs/progress/T017_classification_manifest.json`
  (session IDs and answer counts); any difference refuses execution;
- `--apply --backup FILE` requires a readable `pg_dump` custom-format
  archive, then writes all rows and audit entries in one transaction under an
  advisory lock; re-running is a no-op; a session already classified
  differently refuses;
- `--rollback AUDIT_REF` deletes the classification rows of that reference
  (sessions become student again) and logs the action in the audit table;
- records dashboard metrics before and after.

---

## Consequences

- The dashboard shows student activity only; reclassifying is a data change,
  not a code change, and can be undone.
- Future automated runs use the test database (ADR-016), so new sessions in
  the student database need no classification.

---

## Related

- [ADR-015](ADR-015-repeat-aware-learning-status.md),
  [ADR-016](ADR-016-test-database-isolation.md)
- `docs/progress/task_T017_result.md`
