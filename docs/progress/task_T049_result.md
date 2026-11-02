# T049 Result: Default-Off Bank-Only Switch

- **Date:** 2026-11-02
- **Role:** Developer
- **Status:** Done. PO final approval 2026-11-02; PR #44 (head `33de1f2`,
  CI 41474791091) merged into `dev` as `69e2c39` (`dev` CI 41481451161).
  Not released. No deployment, no live generation, no production seeding,
  budget unchanged.
- **Decision record:** [ADR-035](../adr/ADR-035-bank-only-configurable-practice.md)
  (switch section)

## Change

- `app/main.py`: `MENTOR_PRO_BANK_ONLY_ENABLED`, default off;
  `/api/subjects` reports `practice` (`bank_only`, `question_counts`).
- `app/practice/routes.py`: `source: bank_only` refused with 422
  `bank_only_disabled` while off.
- `app/static/*`: sizes 10–30 hidden and disabled unless the server
  enables them; the "5 preguntas" note is back while off.
- Carries the T048 merge record and release checklist (commit `1186934`).

## Verification

- Switch parsing (absent, empty, `false`, `0`, `no` off; `true`, `1`,
  `YES` on); direct `bank_only` requests refused while off with nothing
  created; earlier generated flow while off and on; T048 tests with the
  switch on.
- Browser (`MENTOR_PRO_BROWSER=1`): off shows only 5 and the note, and a
  practice is generated as before; on keeps the T048 checks. Found and
  fixed: `.segmented label` display overrode `hidden`.
- ACE gate: `VERIFY_RESULT=pass gate=all`; pytest 926 passed, 9 skipped
  (opt-in latency and browser tests).
