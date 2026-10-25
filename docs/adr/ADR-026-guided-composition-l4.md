# ADR-026: Guided Expository Composition (Nivel 4)

> **Status:** Accepted (Product Owner task T028)
> **Date:** 2026-10-25

---

## Context

Nivel 4 (Composición guiada) asks for a typed four-paragraph expository
text of at least 200 words with scaffolding (level map, ADR-019). The
generation pipeline (ADR-020), drafts and single submission (ADR-021), tutor
review (ADR-024) and writing dashboard (ADR-025) exist; no L4 exercise does.

---

## Decision

### Criteria

- Mandatory: EE01–EE06 (the level's core criteria), scored in every
  completed evaluation.
- Optional: EE07–EE18. They are listed in `target_criteria` with
  `"optional": true` on their evaluation parameter, allowed only for
  `guided_composition`. The tutor may score them when the text supports
  it; completion never requires them, and an unscored optional criterion
  is simply absent from the evaluation (no "pending" status).
- EE19/EE20 are not targeted: L4 work is typed.

### Generation (prompt `writing-1.3`)

- Same pipeline, budgets, independent review and provenance. The prompt
  and review list only mandatory criteria; prompts for L1–L3 are unchanged.
- For L4 the model also returns `paragraph_plan_es`, stored as
  `scaffolding_es`: four short guidance items in order (introduction,
  causes, consequences, conclusion with actions or solutions).
- New check W19: exactly four plan items, each at most 25 words, each in
  its paragraph's scope, none a ready-made sentence to copy. W04 also
  requires the instructions to name introduction, development and
  conclusion.

### Student workflow

- Five stages: plan, introduction, two development paragraphs (two text
  areas), conclusion, review and submit. Each stage shows short
  code-owned guidance plus its plan item; no model text, criteria or
  scores.
- Drafts: `writing.draft.sections` (JSONB: `plan`, `introduction`,
  `development_1`, `development_2`, `conclusion`); `text_es` holds the
  assembled paragraphs. Saved on demand, on stage change, after a short
  pause in typing, and before leaving; a reload resumes the saved
  sections. Generated content never fills a section.
- Submission: the four paragraphs are required (422 otherwise) and may not
  contain blank lines, so each stays one paragraph. `text_es` is the four
  paragraphs joined by a blank line; `writing.submission.sections` keeps
  them and the planning notes separately; the exercise revision is
  recorded; duplicates return the first submission.

### Tutor

`/tutor` shows the instructions, the paragraph plan, the student's planning
notes, the four labeled paragraphs and the assembled text, the mandatory
criteria with official descriptors, and the optional EE07–EE18 under
"Convenciones (opcional)" with a "Sin calificar" choice.

---

## Consequences

- Dashboard (ADR-025): "Evaluación pendiente" counts only mandatory
  criteria; optional criteria count once scored.
- L1–L3 records, prompts and editors are unchanged.

---

## Related

- [ADR-019](ADR-019-produccion-escrita-foundation.md),
  [ADR-020](ADR-020-writing-exercise-generation.md),
  [ADR-021](ADR-021-student-writing-practice.md),
  [ADR-024](ADR-024-tutor-writing-evaluation.md),
  [ADR-025](ADR-025-writing-learning-dashboard.md)
- `docs/progress/task_T028_result.md`
