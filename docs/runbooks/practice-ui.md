# Runbook: Práctica PNE UI (local)

> **Date:** 2026-10-21
> **Decision:** [ADR-008](../adr/ADR-008-practice-configuration-api.md),
> [ADR-013](../adr/ADR-013-student-practice-sessions.md) (practice sessions, T010)

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

Practice flow: choose subject, objectives, difficulty and 5 questions, then
"Generar práctica". Generation runs as a server job (about 10 minutes on free
models); the page polls every 3 s and resumes after a reload. Requires
`OPENROUTER_API_KEY` in `.env`.

```bash
curl -s -X POST http://127.0.0.1:8000/api/practice/sessions -H "Content-Type: application/json"   -d '{"subject":"matematicas","scope":"selected_objectives","objective_codes":["M02","M04","M05"],
       "difficulty":"medium","question_count":5,"client_request_id":"manual-0001"}'
curl -s http://127.0.0.1:8000/api/practice/sessions/<session_id>
```

Browser end-to-end test (installed Chrome, desktop 1280 px and mobile 390 px):

```bash
.venv/Scripts/python.exe scripts/dev/practice_e2e.py --out <folder>          # mocked generator
.venv/Scripts/python.exe scripts/dev/practice_e2e.py --out <folder> --live   # OpenRouter, ~10 min
```

---

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| Subjects do not load | `DATABASE_URL` missing or PostgreSQL stopped |
| All counts are 0 | Catalog not imported, or `CURRICULUM_BASELINE` mismatch |
| Browser test fails at launch | Use Chrome (`channel="chrome"`); Edge cannot start in automation on this machine |
| Practice shows "se interrumpió" | The server restarted during generation; configure it again |
