# ADR-014: Validated Question Bank

> **Status:** Accepted (Product Owner task T013)
> **Date:** 2026-10-23

---

## Context

Every practice generated all five questions through OpenRouter (6–12 minutes,
free-model failures). Accepted questions with full validation records already
exist in `generation.question_attempt`. T013 asks to reuse them, generate only
what is missing, keep the allocation, quality policy, provenance and answer
protection, and prefer questions a browser has not seen, without accounts.

---

## Decision

### Inventory and eligibility (`app/practice/bank.py`)

- The bank is `generation.question_attempt` rows with `status = 'accepted'`;
  no copy is made.
- A slot matches on baseline version, objective code, evidencia ID, exact
  difficulty and subject.
- Eligible: validated by the current checker version (verdict `accept`), or
  explicitly revalidated against it: the current deterministic checker passes
  on the stored item with the catalog grounding, the key is proven by current
  rules or a recorded blind solve agreed, and the recorded rubric is all 2.
- Revalidations are stored once per item and checker version in
  `generation.bank_revalidation` (eligible flag and reasons); historical rows
  are never changed. A new checker version triggers revalidation on demand.

### Composition

- At session creation, each allocation slot takes a random eligible item,
  never one already in the set and never a D01 near duplicate of one.
- Items already served are avoided when an alternative exists. Since T014
  ([ADR-015](ADR-015-repeat-aware-learning-status.md)) exposure comes from
  PostgreSQL history across all sessions; the per-tab token hash is still
  stored but no longer decides freshness.
- Slots never borrow items from other objectives or evidencias.
- All slots filled → the session is `complete` at once; no job, no
  OpenRouter call. Otherwise the job generates only the missing slots
  (`generate_set` with the remaining allocation; bank items are seeded into
  the set-wide duplicate check).

### Persistence

`practice.item.source` (`bank` or `generated`) and `source_request_id` (the
originating attempt); `practice.session.bank_count` and `browser_hash`.

### Interface

While the server composes the practice: "Preparando práctica con preguntas
disponibles". While generating: "Generando preguntas adicionales" (with how
many came from the bank). A fully banked practice starts immediately.

---

## Consequences

### Positive

- Common configurations start in about a second at zero cost; generation is
  limited to gaps.

### Negative

- Bank quality inherits earlier model-scored rubrics and blind solves.
- Random selection: repeated practices draw from a small pool until it grows.

### Neutral

- The bank grows only through generation; there is no management screen.

---

## Related

- [ADR-010](ADR-010-single-question-generation.md),
  [ADR-011](ADR-011-validated-practice-sets.md),
  [ADR-013](ADR-013-student-practice-sessions.md)
- Report: `docs/progress/task_T013_result.md`
