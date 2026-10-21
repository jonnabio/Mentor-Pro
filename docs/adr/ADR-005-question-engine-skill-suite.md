# ADR-005: Question Engine Skill Suite

> **Status:** Accepted
> **Date:** 2026-10-21

---

## Context

ACE ships only generic skills. Building a curriculum-grounded PNE question
engine needs domain procedures for grounding, design, validation, routing and
cost tracking. Responsibilities must not overlap, and shared rules must have a
single source of truth.

---

## Decision

We will add nine domain skills under `.ace/skills/` following the native skill
format, plus:

- `.ace/standards/question-engine.md` for rules shared by all nine skills;
- `.ace/knowledge/mep-pne-curriculum.md` for MEP vocabulary;
- JSON Schemas in `.ace/schemas/question-engine/` as machine-readable contracts;
- one deterministic item checker for all four subjects, owned by
  `question-quality-review`;
- `.ace/scripts/validate_skills.py` to verify skill structure and references.

Generic skills are referenced, never modified.

---

## Alternatives Considered

### Alternative 1: Enhance generic skills (`model-evaluation`, `prompt-engineering`)

- **Pros:** Fewer files.
- **Cons:** Mixes domain rules into framework-wide skills.
- **Why rejected:** Breaks reuse across projects.

### Alternative 2: Separate checkers per subject

- **Pros:** Smaller files.
- **Cons:** Duplicated common checks.
- **Why rejected:** Product owner requested one checker for all subjects.

---

## Consequences

### Positive

- Each pipeline concern has exactly one owner.
- Contracts are testable with JSON Schema.

### Negative

- Non-math answers cannot be proven deterministically; an independent solve
  remains mandatory for Español, Ciencias and Estudios Sociales.

### Neutral

- Modifying `.ace/standards/question-engine.md` requires an ADR.

---

## Related

- [Implementation plan](../planning/2026-10-21-question-engine-skills-plan.md)
- [ADR-004](ADR-004-web-app-stack.md)
