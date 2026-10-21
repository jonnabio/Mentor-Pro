# Task T004 Result: Practice Configuration UI and API (Product Owner label T003)

> **Date:** 2026-10-21
> **Status:** Verified (browser check not executed — see Limitations)
> **Decision:** [ADR-008](../adr/ADR-008-practice-configuration-api.md)

---

## Summary

A FastAPI backend and a plain HTML/CSS/JavaScript page let a student choose
subject, objectives (one, several or all), difficulty and question count, and
see a deterministic allocation. No questions are generated. The curriculum
catalog and `curriculum/` code are unchanged; the importer reports
`unchanged` (98 assertions, 344 evidencias).

The task text mentions the SQLite catalog; since T003 (PO label T002.1) the
catalog is PostgreSQL, which is what the API reads.

---

## Delivered

| Item | Location |
|------|----------|
| API (`/api/subjects`, `/api/objectives`, `/api/practice/configure`) | `app/main.py` |
| Allocation policy (pure, deterministic) | `app/allocation.py` |
| UI | `app/static/index.html`, `styles.css`, `app.js` |
| Browser smoke script | `scripts/dev/ui_smoke.py` |
| Runbook | `docs/runbooks/practice-ui.md` |
| Tests | `tests/app/` (40) |

---

## Validation

| Requirement | Evidence | Result |
|-------------|----------|--------|
| Four subjects load | API test; live server: 8 / 22 / 19 / 29 objectives | Pass |
| 78 objectives individually selectable | Each configured as `single_objective` on the real baseline; text and evidence counts match | Pass |
| `EE` excluded | Not listed; `EE01` rejected with Spanish message | Pass |
| Multiple selection | M07, M01, M22 → 4 / 3 / 3 | Pass |
| All objectives | Every subject × 5, 10, 20, 30: totals exact, spread ≤ 1 | Pass |
| Fewer questions than objectives | Ciencias, 5 questions → C01, C04, C08, C12, C16; 14 reported uncovered | Pass |
| Objective–evidence links | Every slot's evidencia belongs to its objective | Pass |
| Invalid configurations rejected | 13 cases (scope/count mismatch, duplicates, unknown or foreign codes, rubric, bad subject, difficulty, count, scope) → 422 | Pass |
| Deterministic allocation | Same input twice and shuffled selection order give identical output | Pass |
| Existing tests | `tests/ace` 99, `tests/curriculum` 44 | Pass |
| Full suite | 183 passed, 0 skipped | Pass |
| ACE gate | `bash .ace/scripts/verify.sh` → `VERIFY_RESULT=pass gate=all` | Pass |
| Desktop and mobile | Responsive CSS (breakpoints 480 px, 720 px; 44 px touch targets); automated browser run not possible | **Not verified** |

Live server check (`uvicorn`, real catalog): `/`, `/static/app.js` → 200;
subjects, objectives and configure responses as above.

---

## Limitations

| Topic | Note |
|-------|------|
| Browser verification | Microsoft Edge exits immediately when launched by automation (Playwright and plain `--headless`), inside and outside the tool sandbox. `scripts/dev/ui_smoke.py` is written but has not run successfully. Manual check needed at 1280 px and 390 px. |
| Allocation strategy | Balanced only; planned-item weighting deferred (ADR-008) |
| Same subset each time | With few questions, the same objectives are chosen for the same selection (by design) |
| Tracker IDs | PO task T003 is tracker T004 (`^T[0-9]{3}$`) |
