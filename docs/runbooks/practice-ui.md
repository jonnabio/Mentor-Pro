# Runbook: Practice Configuration UI (local)

> **Date:** 2026-10-21
> **Decision:** [ADR-008](../adr/ADR-008-practice-configuration-api.md)

---

## Prerequisites

- PostgreSQL with the catalog imported (`python -m curriculum.importer`).
- `DATABASE_URL` in the environment or `.env`.
- `.venv/Scripts/python.exe -m pip install -r requirements-dev.txt`

---

## Start

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

Open `http://127.0.0.1:8000/`. API docs: `http://127.0.0.1:8000/api/docs`.

---

## Check

```bash
curl -s http://127.0.0.1:8000/api/subjects
curl -s "http://127.0.0.1:8000/api/objectives?subject=matematicas"
curl -s -X POST http://127.0.0.1:8000/api/practice/configure \
  -H "Content-Type: application/json" \
  -d '{"subject":"ciencias","scope":"subject_simulation","objective_codes":[],"difficulty":"mixed","question_count":5}'
```

Browser smoke test (desktop 1280 px, mobile 390 px; uses installed Edge):

```bash
.venv/Scripts/python.exe scripts/dev/ui_smoke.py --out <folder>
```

---

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| Subjects do not load | `DATABASE_URL` missing or PostgreSQL stopped |
| All counts are 0 | Catalog not imported, or `CURRICULUM_BASELINE` mismatch |
| `ui_smoke.py` fails at browser launch | Edge cannot start in automation on this machine (see T004 report) |
