# Active Context: Session Handoff 2026-10-21

## Session Metadata

- **Last Updated:** 2026-10-21
- **Active Role:** Architect (next: Developer)
- **Mode:** PLANNING

## Current Objective

Next task: OpenRouter integration and question generation over the approved
curriculum catalog (tracker T005). Not started.

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

### Current State

- `main` pushed to `origin/main`; working tree clean; no task locks.
- Catalog: PostgreSQL `mentor_pro`, schema `curriculum`; re-import reports
  `unchanged`.
- App: `app/main.py` (FastAPI) + `app/static/`; endpoints
  `GET /api/subjects`, `GET /api/objectives`, `POST /api/practice/configure`.
  Returns allocation slots (objective, evidencia, difficulty); no questions yet.
- Tests: 183 passing (`tests/ace` 99, `tests/curriculum` 44, `tests/app` 40).
  ACE gate `VERIFY_RESULT=pass gate=all`.

### Next Steps

1. Owner runs `.venv/Scripts/python.exe scripts/dev/setup_secrets.py`
   (Postgres password and `OPENROUTER_API_KEY` into `.env`).
2. Owner sets budget and model policy for T005: free-only or paid fallback,
   daily/monthly USD and request limits (`openrouter-model-routing` skill).
3. T005 plan (Architect): OpenRouter client with runtime model discovery and
   free-first routing; generation from allocation slots (`mep-question-design`);
   deterministic checker + independent solve (`question-quality-review`);
   usage/cost records (`llm-cost-observability`); storage tables for items and
   usage. Write ADR-009 before code.
4. Implement T005 after plan approval; keep `/api/practice/configure` contract.

### Blockers/Issues

- `OPENROUTER_API_KEY` not configured yet (`.env` missing).
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
