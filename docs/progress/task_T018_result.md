# Task T018 Result: Intermittent Quality-Gate Failure

> **Date:** 2026-10-24
> **Status:** Done (browser cause fixed; T016 gate failure not reproduced)
> **RCA:** [RCA-003](../rca/RCA-003-intermittent-gate-and-browser-failures.md)

---

## Findings

| Failure | Result |
|---------|--------|
| Browser dashboard wait (T016 first run) | Reproduced (1 of 6 cycles; probes up to 7/40 clicks). Cause: "Ver mi progreso" handler threw `reading 'value'` when clicked before `/api/subjects` answered. Fixed |
| Gate `gate=test` (T016) | Not reproduced in 20 full gate runs. Its output was lost because the investigation command kept only the last line and the gate had no log. Cause not established |
| Suite failure in T017 | Already explained and fixed in T017 (classification table missing) |

---

## Changes

| File | Change |
|------|--------|
| `app/static/app.js` | `form.elements.subject?.value`; no visible change |
| `.ace/scripts/verify.sh` | Per run and gate: stdout and stderr files, summary with exit code, duration, signal; silent success fails; failure prints both tails and the log path |
| `tests/ace/test_verify_gate.py` | 4 tests: pass, failure streams, silent success, signal 9 |
| `scripts/dev/practice_e2e.py` | `scenario_dashboard_before_subjects_load` (fails on the old handler) |
| `docs/rca/` | RCA-003 and its regression guard |

Test-database isolation is unchanged. No curriculum, student record,
classification, bank, OpenRouter setting or visible interface change.

---

## Verification

| Run | Result |
|-----|--------|
| Reproduction: 6 × (mocked browser run, gate) + 6 gates | Gates 12/12 pass; browser 5/6 (cycle 1 failed on the dashboard) |
| Regression scenario on the old `app.js` | Fails (dashboard hidden) |
| Fixed code: 8 gates, 3 browser runs between them | 8/8 pass; browser 183/183 each |
| Final suite | 386 passed (382 + 4) |
| Final browser (mocked) | 183/183 |
| Gate self-tests | Silent command → `exit=125 no_output=1`, `fail`; `kill -9` → `exit=137 terminated_by_signal=9`, `fail` |

Every gate run in T018 has a summary under `.ace/logs/verify/<run>/`.

---

## Final Verification (Product Owner approval)

| Check | Result |
|-------|--------|
| Local server restarted (`uvicorn app.main:app --port 8000`) | Running; served `app.js` contains the fix |
| Smoke test, "Ver mi progreso" clicked with `/api/subjects` delayed 1.5 s (desktop, mobile) | 0 subjects loaded at click; dashboard visible; no JavaScript errors |
| Smoke test, normal load | Dashboard visible; no JavaScript errors |
| Writes during the smoke test | None (GET requests only; no practice started, no answer sent) |
| Final ACE gate | `VERIFY_RESULT=pass gate=all` |
| Commit check (`b4a34e2`) | 9 intended files; no secrets, credentials, student data, logs, `.env` or dumps; `.ace/logs/` git-ignored |
| Push | `a875cc1..b4a34e2 main -> main` |

---

## Unresolved Risks

- **Unresolved:** the T016 `gate=test` failure. No evidence was kept and it
  was not reproduced; its root cause is unknown and not fixed. The next
  occurrence will keep its full logs.
- The regression scenario lives in the browser script, which is not part of
  the ACE gate.

## Follow-up (not part of T018)

- **Shared test-database job interference:** `fail_interrupted()` fails
  every queued or running session in the shared test database when any new
  app instance starts, so a job left running by one test (or a concurrent
  browser run) can be marked failed by another. Not observed to fail a
  test. Candidate fix for a separate task: scope the cleanup per process or
  isolate practice tables per test schema.
