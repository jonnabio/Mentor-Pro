# Release and Acceptance Checklist: T047 + T048

- **Date:** 2026-11-01
- **Status:** Steps 2–6 done 2026-11-02: `v2026.11.02-1` deployed, switch
  off ([release record](../progress/2026-11-02-production-release.md)).
  Step 7 (browser acceptance) pending; steps 8–9 need authorization.
- **Source:** `dev` at `0a776f9` (`dev` CI 41383980544). Production runs
  `v2026.10.31-1` (`e7dd6edb…3215`), schema `0001`.
- **Scope:** T047 bank foundation (ADR-034), T048 bank-only configurable
  practice (ADR-035). No `deploy/` change, no migration: a same-schema
  deploy (runbook section 0). The T047 tables are created additively on
  first use.

## T049 switch (2026-11-02)

Release with `MENTOR_PRO_BANK_ONLY_ENABLED` absent (off): the student keeps
the 5-question flow with generation, and T047 holds seeded questions until
review. Step 1 found 34 accepted questions in production, about one per
cell, so bank-only stays off until Matemáticas passes review. Enabling it
later: add `MENTOR_PRO_BANK_ONLY_ENABLED=true` to `/etc/mentor-pro/app.env`
(administrator), redeploy the same release, smoke, then the bank-only
browser checks below. The release also includes T049.

## Decision before release

The student UI now serves practices only from the bank. A topic, level or
size without enough eligible questions gets the shortage message, not a
5-minute generated practice. Step 1 shows what the student can practice
on release day; the PO accepts that coverage or waits for the pilot
(step 9).

## Steps

| # | Step | Pass | Stop |
| --- | --- | --- | --- |
| 1 | Read-only inventory (authorization needed): count accepted questions by subject, objective, evidencia, difficulty, in a read-only transaction | Counts recorded | Any write or error |
| 2 | Release PR `dev` → `main`, pinned to `69e2c39` (T047–T049); protected tag, GitHub Release, manifest | CI green, manifest sha256 recorded | CI red |
| 2a | Administrator: `MENTOR_PRO_BANK_ONLY_ENABLED` absent from `/etc/mentor-pro/app.env` (key names only); after deploy `/api/subjects` reports `bank_only: false` | Off | Present: stop, PO decides |
| 3 | `status`, `smoke` | `STATUS HEALTHY`, `SMOKE PASS (9/9)` | Anything else |
| 4 | `backup`, then `verify-backup <dump>` | `BACKUP OK`, `VERIFY OK` | Anything else |
| 5 | `preflight "$M"` | `PREFLIGHT OK` (schema `0001`) | Anything else |
| 6 | `deploy "$M" --backup <dump> --window "$W" --authorization "$A"`, then `smoke`, `status` | `DEPLOY OK`, 9/9, `HEALTHY` | Roll back (below) |
| 7 | PO browser acceptance on the house Wi-Fi | All checks below pass | Roll back on a defect |
| 8 | Read-only inventory again (as step 1) | Same counts; no new rows | Investigate |
| 9 | Seeding pilot (separate authorization) | See below | Exit 1 or 4, `failed` review |

Steps 3–6 use `T="sudo -n /usr/local/lib/mentor-pro/mentorpro"` (runbook
section 0). No `sudo install` is needed: `deploy/` is unchanged.

## Rollback readiness

- Target: `v2026.10.31-1` (`e7dd6edb…3215`), same schema `0001`.
  `rollback --backup <step-4 dump> --window "$W" --authorization "$A"`,
  pass `ROLLBACK OK`, then `smoke` 9/9.
- The T047 tables stay; the previous image ignores them. Sessions created
  by T048 remain readable (same columns).
- Never roll back to anything before `v2026.10.30-1`. Never restore over
  the live database.

## Browser acceptance (step 7)

Practices: done by the student, or classified afterwards (ADR-017); no
synthetic writing submissions.

- [ ] Switch off (release): only 5 and "Por ahora las prácticas tienen 5
      preguntas."; a practice is prepared as before.
- [ ] Switch on (after review), the remaining checks: the form shows 5,
      10, 15, 20, 25, 30; 5 is selected.
- [ ] A choice the bank can fill (from step 1) starts at once, without the
      "Generando" screen; answered to the summary; "Mi progreso" updates.
- [ ] "Salir de la práctica" and "Volver al menú principal" work.
- [ ] Shortage: a larger size shows the Spanish message and "Hacer una
      práctica de N preguntas"; that button starts an N-question practice.
- [ ] A choice with no stock shows "Todavía estamos preparando…" and no
      button; no practice is created.
- [ ] Writing: "Abrir Producción escrita" opens an exercise; earlier
      submissions and tutor feedback are visible; the tutor page loads and
      "Volver a Mentor Pro" works. Look only; submit nothing.

## Seeding pilot (step 9, separate authorization)

- Matemáticas only, in the app container, runbook section L:
  `seed run --subject matematicas --max-calls 10`, then `seed report`.
- Budget unchanged (50 requests a day, shared). Stop at `run_call_limit`
  or `daily_budget`; resume another day.
- `review-sample` → the tutor reviews 10 questions → `review-record`.
  Seeded questions reach practices only after `review_status: passed`.
- Record calls per accepted question, coverage and the review result.
