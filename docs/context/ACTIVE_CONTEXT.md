# Active Context: Session Handoff 2026-10-21

## Session Metadata

- **Last Updated:** 2026-10-21
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING

## Current Objective

T006 single-question generation implemented
([ADR-010](../adr/ADR-010-single-question-generation.md)); live validation
partial. Next: regenerate M02 and C01, then decide next PO task.

## Handoff Summary

### Completed

- Repository reset: fresh ACE 2.7.0 baseline on `main`; GitHub history
  replaced. MEP source files kept out of Git (`references/original/` ignored;
  checksums in `references/MANIFEST.sha256`, generic names).
- PostgreSQL 17 takeover: old database and roles removed; role
  `mentor_pro_admin` owns `mentor_pro` and `mentor_pro_test`.
  `scripts/dev/setup_secrets.py` for private passwords and the OpenRouter key.
- T001 — nine question-engine skills, standard
  `.ace/standards/question-engine.md`, knowledge file, JSON Schemas,
  deterministic item checker for all four subjects, skill validator
  ([ADR-005](../adr/ADR-005-question-engine-skill-suite.md)).
- Workbook ingestion assessment
  (`docs/requirements/2026-10-21-curriculum-ingestion-assessment.md`).
- T002 — curriculum baseline `PNE2026-SUM-v1.0` (98 objectives, 344
  evidencias; 78 multiple-choice, 20 `EE` rubric); approved-baseline grounding
  rule ([ADR-006](../adr/ADR-006-curriculum-baseline-v1.md)).
- T003 (PO label T002.1) — catalog migrated to PostgreSQL, schema `curriculum`,
  advisory-locked idempotent imports, Docker Compose file
  ([ADR-007](../adr/ADR-007-postgresql-curriculum-catalog.md)).
- T004 (PO label T003) — practice configuration API and Spanish UI with
  deterministic balanced allocation
  ([ADR-008](../adr/ADR-008-practice-configuration-api.md)). Product Owner
  confirmed the web interface is available.
- T005 — OpenRouter client, free-first routing, paid gate, budgets, usage
  records in `llm.usage_record`, CLI `python -m app.llm.connectivity`.
- T006 — grounded single-question pipeline, blind solve, rubric, checker 1.3.0,
  dev endpoint `POST /api/dev/questions/generate`; live: ES01, EL01 valid;
  M02 not validated; C01 rejected; cost $0.00 (`docs/progress/task_T006_result.md`).

### Current State

- `main` pushed to `origin/main`; working tree clean; no task locks.
- Catalog: PostgreSQL `mentor_pro`, schema `curriculum`; re-import reports
  `unchanged`.
- App: `app/main.py` (FastAPI) + `app/static/`; endpoints
  `GET /api/subjects`, `GET /api/objectives`, `POST /api/practice/configure`.
  Returns allocation slots (objective, evidencia, difficulty); no questions yet.
- Tests: 246 passing (`tests/ace`, `tests/curriculum`, `tests/app`).
  ACE gate `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. After the daily budget resets (UTC), regenerate M02 and C01:
   `scripts/dev/generate_examples.py --out <file> --only M02` (then C01).
2. PO decisions: C09 key-length cue warn vs reject; daily request budget.
3. Next PO task (practice sessions / batch generation) after approval.

### Blockers/Issues

- Daily request budget (50) reached on 2026-10-22.
- Some free models rate-limit (Gemma 429) or are unavailable to this
  account (Nemotron Super 404, Inkling 403).
- Local `pg_hba.conf` uses `trust`; `mentor_pro_admin` has no password.
- Automated browser checks impossible on this machine (Edge exits under
  automation); `scripts/dev/ui_smoke.py` never ran successfully.
- Docker not installed; `docker-compose.yml` untested.
- Student first name remains in pushed commit `42adbe7`; history rewrite needs
  separate approval.
- Remote branch `origin/copilot/clean-repository` (merged PR #1) still exists.
- Framework markdown lint debt (~700 issues; `docs/TODO-markdown-lint.md`).
- Pending decision: balanced vs planned-item-weighted simulation allocation.

### Notes

- Tracker IDs must match `^T[0-9]{3}$`; PO labels are kept in task names/notes.
- Start the app (Git Bash):
  `DATABASE_URL=postgresql://mentor_pro_admin@127.0.0.1:5432/mentor_pro
  .venv/Scripts/python.exe -m uvicorn app.main:app --port 8000`
- Re-import catalog: `.venv/Scripts/python.exe -m curriculum.importer
  --workbook <workbook.xlsx>` (located by checksum).
- Gate: `bash .ace/scripts/verify.sh` (tests need `mentor_pro_test`).
- Approved-baseline items must carry `grounding_basis: approved_baseline` and
  never be shown as official MEP wording.
- Never send student data to models; secrets only via `.env`.

## Active Constraints

- `.ace/standards/question-engine.md`
- `.ace/standards/coding.md`, `.ace/standards/security.md`
- [ADR-005](../adr/ADR-005-question-engine-skill-suite.md) to
  [ADR-008](../adr/ADR-008-practice-configuration-api.md)
