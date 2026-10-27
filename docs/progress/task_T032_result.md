# T032 Result: Producción Escrita Usable in Production (Bank Provisioning)

- **Date:** 2026-10-27
- **Role:** Developer
- **Status:** verified locally; not deployed (needs Product Owner approval)

## Assessment (Thought)

- The student writing flow already exists and works: levels with counts,
  eligible-only listing, L1 editor prefilled, L2–L3 text area, L4 five
  stages, ordered autosave (ADR-028), one idempotent submission per
  exercise, "Pendiente de revisión del tutor", tutor review (ADR-024),
  feedback and the "Producción escrita" progress tab (ADR-025).
- Gap 1 (data): production has 0 writing exercises. No export or import
  mechanism existed. Local database: 11 eligible (L1 3, L2 3, L3 3, L4 2),
  1 quarantined (`PE-L1-feria-ciencia-escuela-c9576f`), 0 drafts,
  submissions or evaluations.
- Gap 2 (tutor): `/tutor` answers 404 in production (no token), and every
  request reaches the container from the bridge gateway `172.19.0.1`
  through `docker-proxy`, Wi-Fi included. The loopback check can never
  pass, and trusting the gateway would open the tutor API to the Wi-Fi.
  Changing the boundary needs approval: [ADR-031](../adr/ADR-031-tutor-access-in-production.md)
  (Proposed).

## Action

- `app/writing/bank.py`: `export`, `import [--dry-run] [--report]`,
  `inventory` (`python -m app.writing.bank`, runs inside the image).
  Export carries exercise, revisions, tutor-only references, accepted
  generation attempt, eligibility history, independent validations and the
  generator/reviewer usage rows; quarantined exercises are skipped.
  Import checks the curriculum baseline in the destination, the rubric file
  hash, current-revision contracts, consecutive revisions, the accepted
  attempt, RCA-004 independence (or a passed revalidation) and the L1
  reference; one transaction under an advisory lock; never overwrites
  (identical = unchanged, different = rejected); verifies student tables
  are untouched.
- `tests/app/test_writing_bank.py` (7 tests): export excludes quarantined
  and student data; dry run writes nothing; import repeatable; existing
  student work untouched; inconsistent records, missing baseline and
  conflicting ids rejected; reinstated exercises keep their history; an
  imported exercise completes student → tutor → feedback in a new app.
- Runbook section H (writing exercise bank).

## Observation

- Real-data rehearsal in a scratch `_test` database with the real
  curriculum (98 assertions): dry run imported 11 and wrote nothing;
  import 11; rerun 0 imported, 11 unchanged, 0 rejected; inventory L1 3,
  L2 3, L3 3, L4 2, quarantined none. The first rehearsal exposed a crash
  on exercises with eligibility history (rolled back, nothing written);
  fixed and covered by a test.
- API walk over all 11 imported exercises: Spanish instructions (4–6
  items), L1 source text present, no tutor reference or rubric codes in
  the student view; L1 and L4 flows: stale draft ignored, double submit
  returns one submission, pending-review status, tutor completion,
  feedback visible from a new app instance, progress endpoint populated.
- Gate: `VERIFY_RESULT=pass gate=all`, 545 tests passed. Browser
  (`practice_e2e.py`, mocked, `mentor_pro_test`): 447/447.

## Not done (requires approval)

- Production import (runbook section H) and the image containing T032.
- Tutor access in production (ADR-031).
