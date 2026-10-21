# Active Context: Curriculum Baseline v1.0

## Session Metadata

- **Last Updated:** 2026-10-21
- **Active Role:** QA Engineer
- **Mode:** VERIFICATION

## Current Objective

Curriculum baseline `PNE2026-SUM-v1.0` in the PostgreSQL catalog
(T002; T003 = PO label T002.1;
[ADR-006](../adr/ADR-006-curriculum-baseline-v1.md),
[ADR-007](../adr/ADR-007-postgresql-curriculum-catalog.md)). No OpenRouter
integration, question generation or frontend yet.

## Current State

### Working

- Fresh repository (`main`), ACE 2.7.0 baseline; MEP PDFs excluded from Git,
  checksums in `references/MANIFEST.sha256`.
- Local PostgreSQL 17: role `mentor_pro_admin` owns empty database
  `mentor_pro`; passwords set privately with `scripts/dev/setup_secrets.py`.
- Nine question-engine skills, shared standard, knowledge file, schemas,
  deterministic checker for all four subjects, skill validator, tests
  (T001, [ADR-005](../adr/ADR-005-question-engine-skill-suite.md)).
- Curriculum catalog in PostgreSQL `mentor_pro`, schema `curriculum` (98
  objectives, 344 evidencias; 78 multiple-choice, 20 `EE` rubric), loaded with
  `python -m curriculum.importer` via `DATABASE_URL`; approved-baseline
  grounding (T002, T003). Test database `mentor_pro_test`.

### In Progress

- None.

### Blocked

- Local `pg_hba.conf` uses `trust`; passwords are not enforced (owner
  accepted for development).

## Next Steps

1. [ ] Owner runs `python scripts/dev/setup_secrets.py` (Postgres password,
       OpenRouter key into `.env`).
2. [ ] Accept or amend [ADR-004](../adr/ADR-004-web-app-stack.md) (stack).
3. [ ] PO task T003 (tracker T004, needs approval): OpenRouter
       integration, coverage planning and generation over the catalog.
4. [ ] Build the evaluation dataset (`question-evaluation`).
5. [ ] Decide whether to rewrite Git history to remove the student name in
       commit `42adbe7` (separate approval).
6. [ ] Reduce baseline markdown lint debt (`docs/TODO-markdown-lint.md`).

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md), [ADR-006](../adr/ADR-006-curriculum-baseline-v1.md)
- Plan: `docs/planning/2026-10-21-question-engine-skills-plan.md`
