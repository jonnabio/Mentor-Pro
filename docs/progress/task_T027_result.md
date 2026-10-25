# T027 Result: Writing Learning Dashboard

- **Status:** verified
- **Role:** Developer
- **ADR:** [ADR-025](../adr/ADR-025-writing-learning-dashboard.md)

## Behavior

"Mi progreso" has a fifth tab, **Producción escrita**. It loads
`GET /api/writing/progress` and hides the multiple-choice metrics;
`/api/dashboard` is unchanged.

- Activity: exercises submitted, evaluations completed, evaluations
  pending, per level L1–L5 "N evaluados · M entregados", last writing
  practice date (latest submission or saved draft).
- Coverage (apart from performance): Evaluado / Evaluación pendiente /
  Sin evaluar, each "n de 20".
- Per dimension (official rubric mapping): "Promedio x de 4 · k de n
  criterios evaluados" from the latest points of evaluated criteria only,
  or "Sin evaluar". No weights, total or grade.
- Per criterion EE01–EE20: code, official wording, status, and when
  evaluated the latest and best score (0–4), number of evaluations and last
  evaluation date. "No evaluable" counts (EE19/EE20 on typed work) are
  shown as a note and never scored.
- "Ir a Producción escrita" opens the existing level list.

Scores come only from `completed` evaluations; `pending` and `in_progress`
evaluations give none. The endpoint is read-only.

## Queries

Progress input (`WritingStore.PROGRESS_SQL`): every submission with its
level, evaluation status and record, and the evaluation parameters of the
exercise revision it answered (scorable criteria for "pendiente"):

```sql
SELECT s.submission_id, s.submitted_at, e.level, v.status AS evaluation_status, v.record AS evaluation,
       COALESCE((SELECT r.record FROM writing.exercise_revision r WHERE r.exercise_id = s.exercise_id
                 AND r.revision = s.exercise_revision), e.record)->'evaluation'->'parameters' AS parameters
FROM writing.submission s JOIN writing.exercise e USING (exercise_id)
LEFT JOIN writing.evaluation v USING (submission_id)
ORDER BY s.submitted_at;
SELECT MAX(updated_at) FROM writing.draft;
```

Independent check used by the browser test (latest score per criterion):

```sql
SELECT DISTINCT ON (c.criterion_code) c.criterion_code, c.points
FROM writing.criterion_score c JOIN writing.evaluation v USING (evaluation_id)
WHERE v.status = 'completed' AND c.status = 'scored'
ORDER BY c.criterion_code, v.evaluated_at DESC;
```

## Fix found on the way

`app/static/app.js` (RCA-003 guard): a late answer for a writing level the
student had already left could fill the next level's list and hide its
empty state (mobile browser run). `openWriting` and `openWritingLevel` now
ignore superseded answers. Guard invariant kept: main-menu handlers do not
depend on loaded content.

## Validation

| Check | Result |
| --- | --- |
| `tests/app/test_writing_progress.py` (acceptance 1–8) | 6 passed |
| Full suite (ACE gate `test`) | 495 passed |
| Browser, mocked, `mentor_pro_test`, desktop and mobile | 399/399 |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |

Browser checks compare the screen with the SQL above: 20 criteria with
official wording; counts 4 / 3 / 1; latest scores of the 5 evaluated
criteria; pending EE16–EE18 without a score; EE19 unscored; dimension
averages 2, 2, 2,5 and "Sin evaluar" for 1 and 5; shown after reload;
Matemáticas tab unchanged; button opens the writing list; no overflow.
Artificial submissions and evaluations were made only in
`mentor_pro_test`; the student database was not written.

Screenshots: `docs/progress/screenshots/T027/desktop-writing-dashboard.png`,
`docs/progress/screenshots/T027/mobile-writing-dashboard.png`.
