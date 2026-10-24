# Task T017 Result: Historical Test Data Cleanup and Learning Integrity

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-017](../adr/ADR-017-session-classification.md)

---

## Implementation

| Area | Change |
|------|--------|
| `app/practice/store.py` | `practice.session_classification` (`student` / `automated_test` / `quarantined`, reason, audit reference, timestamp) and append-only `practice.classification_audit` |
| `app/practice/mastery.py` | Dashboard answers exclude `automated_test` and `quarantined` sessions before attempts are numbered |
| `app/practice/bank.py` | Exposure history (`seen_questions`) uses student sessions only; bank eligibility unchanged |
| `app/main.py` | The dashboard initialises the practice tables first, so it works on a database where no practice ran yet |
| `scripts/dev/classify_sessions.py` | Freeze, dry run, `--apply --backup`, `--rollback`; refuses on any count or ID difference |
| `docs/progress/T017_classification_manifest.json` | Frozen session IDs, classes and answer counts (random IDs only) |

No session, item or answer was modified or deleted. Curriculum, bank,
generated questions, validation histories, generation, OpenRouter budgets
and the mastery thresholds are unchanged.

---

## Classification Applied (student database, audit `T017-2026-10-24`)

| Classification | Sessions | Answers | Source |
|----------------|----------|---------|--------|
| `automated_test` (excluded) | 103 | 308 | T016 confirmed test |
| `quarantined` (excluded, kept) | 14 | 68 | T016 probable test |
| `student` (included) | 2 | 5 | T016 presumed student |

Before writing: the manifest IDs matched every session ID listed in the
T016 report (103, 14, 2), and the dry run matched the approved counts.
Applying again reported 0 inserted, 119 unchanged.

After applying, all of these were identical to before: 119 sessions, 501
items, 381 answers (checksum of every answer row unchanged), 112 generation
attempts, 98 assertions, 344 evidencias and 400 LLM usage rows.

---

## Learning Metrics

Full values: [T017_metrics.json](T017_metrics.json).

| Subject | Answers before → after | Distinct questions | Mastery accuracy | Statuses after |
|---------|------------------------|--------------------|------------------|----------------|
| Español (8) | 77 → 0 | 77 → 0 | 71.4 % → — | 8 Sin practicar |
| Matemáticas (22) | 178 → 0 | 145 → 0 | 66.9 % → — | 22 Sin practicar |
| Ciencias (19) | 71 → 5 | 71 → 5 | 69.0 % → 100 % | 18 Sin practicar, 1 Dominio consolidado (C06) |
| Estudios Sociales (29) | 55 → 0 | 55 → 0 | 80.0 % → — | 29 Sin practicar |

Before cleanup, 6 objectives showed "Dominio consolidado" and 3
"Necesita refuerzo" from test activity. Afterwards, C06 has 5 distinct
first attempts, all correct (≥ 5 distinct, > 90 %, which the six-level model
classifies as "Dominio consolidado"). `GET /api/dashboard` on the student
database lists all 78 objectives.

---

## Backup and Rollback

- Backup: `pg_dump -Fc` of `mentor_pro`, outside the repository:
  `%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T017_2026-10-24.dump`
  (208 586 bytes, SHA-256 `deaa295f…37763f6`).
- Verified by restoring into a scratch database: identical row counts and
  answer checksum; the scratch database was then dropped.
- Undo the classification only (recommended):
  `.venv/Scripts/python.exe scripts/dev/classify_sessions.py --rollback T017-2026-10-24`
  deletes the classification rows of that reference (the sessions count
  again) and logs `rollback` entries in the audit table.
- Full restore (last resort, stop the app first):

  ```bash
  pg_restore -h 127.0.0.1 -U mentor_pro_admin -d mentor_pro --clean --if-exists <dump>
  ```

---

## Verification

| Requirement | Evidence |
|-------------|----------|
| 1–2 Test and quarantined answers excluded | `test_classified_sessions_are_excluded_and_first_attempts_recomputed[automated_test, quarantined]`; student-database metrics above |
| 3 Student answers included | `test_student_classification_and_cancelled_student_practices_still_count`; C06 5 answers after |
| 4 Cancelled student practices count | Same test; T015 test unchanged |
| 5 Unanswered never incorrect | Same test (3 unanswered: 2 answers, 1 correct); T014.1 tests |
| 6 Exposure from student history only | `test_exposure_history_ignores_classified_sessions` |
| 7 First attempts recomputed | Excluded first attempt → the student's later answer becomes the first attempt |
| 8 Six-level model | Thresholds unchanged; status tests pass |
| 9 All 78 objectives | `test_dashboard_covers_all_78_objectives_with_six_statuses`; live endpoint 78 |
| 10 Bank independent | Bank tests pass; mocked browser bank scenario 5/5 from the bank |
| Script safety | `test_session_classification.py`: refusal on mismatch, idempotent apply, conflict refusal with no partial write, rollback with audit |

- Suite: 382 passed (375 + 7 new).
- Browser (mocked, `mentor_pro_test`): 182/182. The live OpenRouter run was
  not repeated: T017 changes no generation path.
- ACE gate: `VERIFY_RESULT=pass gate=all`.

During development the first suite run failed once: the dashboard queried
`session_classification` before any practice code had created it. Fixed by
the `app/main.py` change (reproduced by dropping the table in the test
database, then passing). The unexplained T016 gate failure predates this
table and remains unexplained.

---

## Regression Guards

No guarded file was modified (RCA-001, RCA-002).
