# T070 Result: Question Bank Final Acceptance

- **Role:** QA Engineer (PO authorization PO-T069-RELEASE-2026-11-16)
- **Date:** 2026-11-16
- **Production:** `v2026.11.16-2` (`835ffb2`, image
  `@sha256:dc5d1ce4…805b`), `STATUS HEALTHY`.
- **Method:**
  - read-only production checks: SQL in a read-only transaction, read-only
    commands, and GET or availability calls that create nothing;
  - the CI test database, with synthetic data only.
  - No production practice was created and no tutor verdict was recorded.
- **Outcome:** **every mandatory software criterion passes.** We propose
  closing the Question Bank development initiative (section 5).

## 1. Acceptance matrix

Status key:

- **P:** implemented and verified in production.
- **S:** verified with synthetic inventory, not yet stocked in production.
- **O:** operational work that continues after the feature closes.
- **D:** software defect or failed mandatory criterion.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | All four subjects' practice flows work | P | Production availability answers for all four subjects. Smoke 13/13. 16 real student sessions across all four subjects, every complete one with exactly `slots_total` items. Synthetic API and browser tests cover all four subjects |
| 2 | Every offered size starts | P + S | Production offers Matemáticas 5 and 10 (both built by the composer) and 5 elsewhere (generation, T059). The CI tests start every offered size and refuse the next one with nothing created (`test_quiz_sizes.py`, `test_quiz_sizes_subjects.py`, RCA-006) |
| 3 | Bank practices use approved questions only | P | Of 18 bank-served items: 0 quarantined, 0 unapproved seeder questions, 0 without an accepted source. 0 pending questions ever served |
| 4 | Mixed sizes 5–30 work end to end | S | `test_quiz_sizes_subjects.py`: all four subjects, every size, exact count, allocation (D2), level balance (D3), no repeats, no model call; browser on desktop and phone (CI, 5 browser tests executed) |
| 5 | Production shows sizes that match inventory | P | Coverage API, `replenish capacity` and student availability agree for every subject (T069 result, post-deploy checks) |
| 6 | Answers, scoring, success rates, tutor analytics | P + S | Production: 38 answers, 0 whose stored correctness differs from the item key. Synthetic: 30-question practices score 20/30 (67%), and the history, tutor detail and analytics groups are correct |
| 7 | Tutor review stores authentic decisions and comments | S + O | Production: 41 verdicts, all by `tutor`, unchanged across two deploys; the `comment` column is present. Dashboard approve, quarantine, comment and exactly-once are verified in CI (T068 browser test). The first production decision through the dashboard is the tutor's to make |
| 8 | Replenishment enabled, bounded, observable, free-only | P | Enabled, 10 calls per tick, not paused. 7 days: 14 ticks `ok` (139 calls, 26 candidates), 8 skipped (7 before enabling, 1 busy). All 846 recorded calls free, $0. `OPENROUTER_ALLOW_PAID=false` |
| 9 | Coverage dashboard reports current shortages | P | "Cobertura del banco" deployed. Its sizes equal the student availability. Shortfalls by stage match the T069 assessment |
| 10 | No corruption of student records, curriculum or verdicts | P | Identical fingerprints before and after the deploy. 0 items with an unknown objective or evidencia. 0 verdicts without a question. 0 repeated questions in a practice |

## 2. Verified synthetically, not yet stocked in production

- Mixed sizes 15–30 in Matemáticas, and every bank size in Español, Ciencias
  and Estudios Sociales.
  - The software builds them from a stocked synthetic bank.
  - Production currently lacks approved questions: for size 30, Matemáticas
    11, Español 22, Ciencias 23, Estudios Sociales 19.
  - The shortage is reported correctly, so it is **not a defect**.
- **Bank-only configuration:** production enables bank-only practice for
  Matemáticas only (`MENTOR_PRO_BANK_ONLY_SUBJECTS`).
  - The other three subjects keep the 5-question generated flow, by
    configuration.
  - Once their inventory composes, adding them to that setting (PO
    authorization, environment change and force-recreate) is a
    configuration step, not development.
  - Enabling them earlier is also safe: an empty bank still offers 5
    through generation (T059).

## 3. Operational work after closure

- **Tutor review:** 26 pending. The tutor's first dashboard review is also
  the production proof of criterion 7.
- **Scheduler:**
  - free-only, 10 calls per 3-hour tick;
  - pause if the queue passes 40 before the first substantial review;
  - record the backlog and reason, notify the PO, and never resume
    automatically.
- **Inventory growth toward size 30:** about 64 accepted questions, roughly
  9 to 10 days of scheduler time plus about 100 tutor reviews at the
  current rate. Hard questions are the scarcest level.
- **Monitoring:** periodic read-only `replenish capacity` and the coverage
  view.
- **Deferred decision:** ADR-037's 16-cell extension for explicit-level 25
  and 30.

## 4. Defects and failed mandatory criteria

**None mandatory.** Known minor items, none blocking:

- `replenishment.run` marks every difficulty `candidates_generated`, so cells
  without a candidate are later labelled `reviewed`. This mislabels a
  request record only; it does not affect eligibility, practices or
  spending. If the PO wants it fixed, the smallest correction is to mark only
  the difficulties that received a candidate.
- `tests/app/test_practice_browser.py` (the T048 shortage-retry browser
  test) is still opt-in. The T069 browser tests in CI cover sizes, the
  practice and the result. Adding this file to the CI browser step is a
  one-line change.
- **Local workstation only:** Windows Application Control blocks
  `initdb.exe`, so 5 `test_deploy_backup.py` tests fail locally. They pass
  in CI.

## 5. Recommendation

1. **Close the Question Bank development initiative.**
   - The software is complete and verified in production for:
     - composition and availability;
     - review;
     - replenishment;
     - coverage reporting;
     - analytics;
     - data integrity.
   - Larger sizes depend only on inventory, which the application reports
     correctly.
2. **Continue as operations:**
   - tutor review;
   - free scheduled generation under the 40-item rule;
   - monitoring with the coverage view.
3. **Configuration decision for the PO:** enable bank-only practice for
   Español, Ciencias and Estudios Sociales, now or when their first sizes
   compose.
