# Active Context: Question Engine Skills

## Session Metadata

- **Last Updated:** 2026-10-21
- **Active Role:** QA Engineer
- **Mode:** VERIFICATION

## Current Objective

Equip ACE with verified skills for a curriculum-grounded, OpenRouter-powered
PNE question generation engine (T001). No application code yet.

## Current State

### Working

- Fresh repository (`main`), ACE 2.7.0 baseline; MEP PDFs excluded from Git,
  checksums in `references/MANIFEST.sha256`.
- Local PostgreSQL 17: role `mentor_pro_admin` owns empty database
  `mentor_pro`; passwords set privately with `scripts/dev/setup_secrets.py`.
- Nine question-engine skills, shared standard, knowledge file, schemas,
  deterministic checker for all four subjects, skill validator, tests
  (T001, [ADR-005](../adr/ADR-005-question-engine-skill-suite.md)).

### In Progress

- None.

### Blocked

- Local `pg_hba.conf` uses `trust`; passwords are not enforced (owner
  accepted for development).

## Next Steps

1. [ ] Owner runs `python scripts/dev/setup_secrets.py` (Postgres password,
       OpenRouter key into `.env`).
2. [ ] Accept or amend [ADR-004](../adr/ADR-004-web-app-stack.md) (stack).
3. [ ] Apply `curriculum-data-ingestion` to the Marco 2025 tables
       (all four subjects, diagnóstica and sumativa); human review.
4. [ ] Build the evaluation dataset (`question-evaluation`).
5. [ ] Reduce baseline markdown lint debt (`docs/TODO-markdown-lint.md`).

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md)
- Plan: `docs/planning/2026-10-21-question-engine-skills-plan.md`
