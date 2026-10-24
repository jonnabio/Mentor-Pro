# RCA-003: Intermittent Quality-Gate and Browser-Test Failures

> **Severity:** Medium (reliability; one latent student-facing defect)
> **Date:** 2026-10-24
> **Task:** T018
> **Status:** Browser failure resolved; T016 gate failure not reproduced

---

## Issue Summary

Two unexplained intermittent failures were reported in T016 and T017:

1. **Browser test (`practice_e2e.py`)**: the first mocked run in T016 stopped
   on `expect(#dashboard-view).to_be_visible()` (5 s), then passed.
2. **ACE gate**: one `verify.sh` run in T016 ended `VERIFY_RESULT=fail
   gate=test`; the next gate and three suite runs passed.

---

## Timeline

| When | Event |
|------|-------|
| T016 | First complete mocked browser run fails on the dashboard wait |
| T016 | One gate run fails `gate=test`; output not kept (see Symptoms) |
| T017 | First suite run fails `test_dashboard_covers_all_78_objectives…`: a different, explained cause (table not created yet), fixed in T017 |
| T018 | Diagnostic capture added to `verify.sh`; bounded reproduction runs |
| T018 | Browser failure reproduced (cycle 1 of 6) and traced to its cause |

---

## Symptoms

- Browser: `#dashboard-view` stays `hidden` after clicking "Ver mi
  progreso"; no server error in the log.
- Gate: only the last line was seen. `verify.sh` did print the last 20
  output lines of the failing gate, but the T016 command piped it through
  `tail -1`, and the gate kept no log file, so the evidence was lost.

---

## Root Cause Analysis

### The 5 Whys (browser failure)

1. Why did the dashboard stay hidden? `openDashboard()` never ran: a probe
   hooking `HTMLElement.hidden` saw the click on `#form-progress` but no
   change to `#dashboard-view`.
2. Why did it not run? The click handler threw first:
   `Cannot read properties of undefined (reading 'value')` (captured with
   `pageerror` in 2 of 40 mobile clicks).
3. Why did it throw? The handler reads `form.elements.subject.value`; the
   subject radios are created only when `GET /api/subjects` answers.
4. Why was the click that early? Playwright clicks as soon as the page has
   loaded (about 50 ms); `/api/subjects` is asynchronous. In every failing
   click the probe counted 0 subject inputs.
5. Why was it not caught? Every scenario before the dashboard waits for
   subject content, and the main-menu dashboard step is the only one that
   clicks right after `page.goto`.

### Root Cause Statement

`app/static/app.js` dereferenced form controls that exist only after an
asynchronous request, so "Ver mi progreso" did nothing when clicked before
the subjects loaded. This was a real (if narrow) student-facing defect. The
test exposed it only when the click won the race.

### Evidence

| Probe (`/api/subjects` unmodified) | Dashboard hidden |
|------------------------------------|------------------|
| 40 clicks right after load, desktop / mobile (three probe runs) | 6/40, 1/40 + 5/40, 3/40 + 7/40 |
| Same, with `pageerror` capture | 0/40, 2/40: all `reading 'value'` |
| Regression scenario (subjects delayed 1 s), old `app.js` | Fails |
| Same, fixed `app.js` | Passes |

### The T016 gate failure

Not reproduced. Runs of the full gate after T016: 6 after a mocked browser
run, 6 back to back, 8 under the fixed code (3 after browser runs), plus
earlier runs: all `VERIFY_RESULT=pass`. Hypotheses checked without
supporting evidence:

| Hypothesis | Finding |
|------------|---------|
| Test order or shared rows | Tests filter by their own baseline or unique IDs; no shared IDs found |
| PostgreSQL setup and teardown | Throwaway schemas per module; DDL serialised by advisory lock |
| Browser, port or process leftovers | Browser script exits before the gate; pytest opens no ports |
| Parallel execution | Gate and suite run serially (no xdist) |
| Startup cleanup | `fail_interrupted()` of each new app fails every queued or running session in the shared test database; a job still running from an earlier test could be marked failed. Possible in principle; no failing test observed |
| Subprocess tests (T016 safety tests) | Deterministic refusals, 60 s bound; never failed |

### Contributing Factors

- No persistent gate log, no separate stderr, no durations.
- Browser assertions abort the run on the first failure without the page's
  JavaScript errors in the output (they are collected only for a final
  check).

---

## Resolution

### Immediate Fix

`app/static/app.js`: `form.elements.subject?.value || null`, so the
dashboard opens before the subjects have loaded. No visible change.

### Permanent Fix

`.ace/scripts/verify.sh` now keeps, per run, `stdout` and `stderr` per gate,
plus a summary with exit code, duration and signal
(`$VERIFY_LOG_DIR`, default `.ace/logs/verify/`, git-ignored). A gate that
exits 0 without any output fails (`exit=125 no_output=1`). On failure both
streams' tails are printed with the log location. The output contract
(`VERIFY_RESULT=…` last line) is unchanged.

---

## Regression Prevention

### Tests Added

- `scripts/dev/practice_e2e.py` `scenario_dashboard_before_subjects_load`:
  delays `/api/subjects` by 1 s, clicks immediately; fails with the old
  handler.
- `tests/ace/test_verify_gate.py`: pass with summary; failure keeps stdout
  and stderr separately; silent success fails; termination by signal 9
  reported.

### Regression Guard

`RCA-003` in `docs/rca/regression-guards.yaml` (`app/static/app.js`,
`.ace/scripts/verify.sh`).

---

## Verification

- Suite 386 passed; browser mocked 183/183 (four runs); gate repeatedly
  `pass` with logs and summaries recorded (see `task_T018_result.md`).

---

## Lessons Learned

### What could improve

- Never truncate gate output to its last line in an investigation; keep the
  log.
- UI handlers must not assume asynchronously created elements exist.

### Action items

- If `gate=test` fails again, read `.ace/logs/verify/<run>/test.stdout.log`
  before rerunning.

---

## References

- `docs/progress/task_T018_result.md`
- [RCA-002](RCA-002-math-proof-not-establishing-question.md) (format)

## Sign-off

Prepared by the Incident Responder session, 2026-10-24.
