# T069 Result: Quiz Sizes 5–30, Coverage and Capacity

- **Role:** Developer (PO authorization PO-T069-2026-11-16)
- **Status:**
  - Implemented and tested.
  - PO review of the PR is required before release.
  - Capacity expansion is proposed only:
    [ADR-037](../adr/ADR-037-quiz-size-capacity.md).
- **Plan:**
  [2026-11-16 T069 plan](../planning/2026-11-16-T069-quiz-sizes-plan.md)

## 1. Review inventory (production, read-only, 2026-11-16)

All 23 pending candidates are in the tutor dashboard queue: `ReviewQueue`,
the same source as "Revisión de preguntas". No verdict was recorded.

| Subject | Pending | Objective and difficulty |
| --- | --- | --- |
| Español | 7 | EL01 hard; EL02 easy, medium, hard; EL03 easy, medium, hard |
| Matemáticas | 6 | M04 easy ×2, medium ×2, hard; M05 hard |
| Ciencias | 6 | C02 easy, medium, hard; C03 easy, medium; C04 easy |
| Estudios Sociales | 4 | ES02 easy, hard; ES03 easy, hard |

Recorded verdicts so far: 26 approved and 15 quarantined (37%).

**Backlog:**

- The scheduler stays enabled at 10 calls every 3 hours, about 80 free calls
  a day.
- Recent ticks produced about 2 candidates each, so the queue can grow by
  about 16 a day.
- No candidate has been reviewed since T068 was deployed.

**Recommendation:**

- Keep the scheduler running. Generation, not review, is the first missing
  stage for every size (section 3).
- Pause it with `replenish pause --reason ...` if the queue passes **40**,
  about two days of growth, before the tutor's first review session.
- After the first session, compare the tutor's reviews per day with about 16
  a day.
- The scheduler was not changed. Pausing needs the PO's operational
  authorization.

## 2. Multi-size regression (synthetic database)

`tests/app/test_quiz_sizes_subjects.py` uses its own four-subject workbook
(baseline `SIZES-v1`), with unequal objectives and evidencias per subject. It
stocks 4 approved questions per evidencia and level.

- **Every subject, sizes 5, 10, 15, 20, 25 and 30:**
  - availability offers exactly what the composer builds;
  - each size starts complete, from the bank only;
  - the question count matches the request, with no repeated question;
  - per-objective counts equal `allocate` (D2);
  - every level stays within ±1 of a third (D3);
  - no model call is made.
- **Scoring, history and analytics:** a 30-question practice in Ciencias
  and in Estudios Sociales, with 20 of 30 answered correctly:
  - the summary shows 20 correct, 67%;
  - the history row shows 30 questions, all from the bank, completed;
  - the tutor detail shows each item's result and difficulty;
  - the analytics groups count the answers.
- **Insufficient inventory:**
  - with 3 questions per objective, Estudios Sociales offers 5, 10 and 15;
  - 20, 25 and 30 are refused with `insufficient_inventory` (largest 15),
    and no session is created;
  - an unstocked subject offers only 5, which falls back to generation
    (T059).
- **Browser:** a 30-question practice from the form to the result, on
  desktop (1280 px, Ciencias) and a phone (390 px, Estudios Sociales). All
  six sizes are enabled, there is no sideways scroll, and no model call is
  made.
- **Count model:** `tests/app/test_capacity.py` checks that the exact count
  agrees with the real composer for every size and difficulty when there are
  no near duplicates.

## 3. Capacity assessment (production, read-only, 2026-11-16)

The real composer decides availability. The stages come from
`app/practice/capacity.py`, run on production with the T069 code sent
inline, without deploying it. The table shows missing questions per stage
for a whole-subject mixed practice.

| Subject | Size | Composes | Plan | Generated | Approved | Missing per objective (pending) |
| --- | --- | --- | --- | --- | --- | --- |
| Matemáticas | 5, 10 | yes | 0 | 0 | 0 | — |
| Matemáticas | 15 | no | 0 | 3 | 3 | M08, M15, M21 (hard short 3) |
| Matemáticas | 20 | no | 0 | 5 | 6 | M04 (5 pending), M08, M10, M13, M15, M21 |
| Matemáticas | 30 | no | 0 | 8 | 11 | 9 objectives; hard short 11 |
| Español | 5 | no | 0 | 2 | 2 | EL04, EL05 (hard short 2, 2 pending) |
| Español | 30 | no | 0 | 16 | 22 | 7 objectives; hard short 10 |
| Ciencias | 5 | no | 0 | 1 | 2 | C04 (1 pending), C16 |
| Ciencias | 30 | no | 0 | 21 | 23 | 16 objectives; hard short 10 |
| Estudios Sociales | 5 | no | 0 | 1 | 1 | ES24 (hard) |
| Estudios Sociales | 30 | no | 0 | 19 | 19 | 19 objectives; hard short 11 |

The coverage view and `replenish capacity` give the full per-size detail.
Answers to the PO's five questions:

1. **Curriculum allocation:** satisfiable for every size and subject. Every
   objective has at least one evidencia; ES14 and ES18 have exactly one.
2. **Plan cells:** the 100-cell plan holds every whole-subject mixed size
   from 5 to 30 in all four subjects (plan column 0 everywhere).
   - Explicit-level sizes 25 and 30 lack 1 to 3 cells in Matemáticas,
     Ciencias and Estudios Sociales.
   - Single-objective practices are capped at 0 to 10 questions.
   - Details are in ADR-037.
3. **Generated:** this is the first stage that fails, for every size not yet
   available. Even if the tutor approved all 23 pending questions, no new
   size would open. Español, Ciencias and Estudios Sociales would still lack
   size 5, and Matemáticas size 15.
4. **Approved:**
   - Matemáticas is 3 questions short of 15.
   - Español, Ciencias and Estudios Sociales are 1 to 2 short of 5.
   - Progress toward 30, in approved questions:

     | Subject | Approved | With every pending one approved |
     | --- | --- | --- |
     | Matemáticas | 19/30 | 22/30 |
     | Estudios Sociales | 11/30 | 11/30 |
     | Español | 8/30 | 14/30 |
     | Ciencias | 7/30 | 9/30 |

5. **Remaining causes:**
   - Every gap is an objective-count gap: specific objectives lack questions
     at any level.
   - **Hard** is the scarcest level in every subject.
   - No size fails on near duplicates alone: no available size disagrees with
     the counts.
   - No gap comes from missing curriculum evidence.

**Structural or temporary:**

- For whole-subject mixed practices of 5 to 30, every shortfall is temporary
  inventory: generation first, then review. Nothing structural blocks size 30
  in any subject.
- The structural limits are explicit-level 25 and 30 (16 cells in total) and
  single-objective sizes above the plan. Both are in ADR-037, proposed only.

**Time to size 30 at the current rate (an estimate, not a commitment):**

- The four subjects lack 64 generated questions in total.
- With 37% quarantined, about 100 candidates are needed: about 700 free calls,
  9 to 10 days of the scheduler.
- About 100 tutor reviews are also needed.

## 4. Tutor coverage view

- **"Cobertura del banco" in the tutor page** (tutor service only, tutor
  check, read-only), per subject:
  - sizes available now;
  - each missing size with its missing approved count and blocker
    (structural, generation, review, duplicates);
  - for the next size, the objectives and levels short, with needed,
    approved and missing counts and the pending questions that could close
    each gap;
  - progress toward 30;
  - a table of approved, pending and plan cells per objective and level.
- **API:** `GET /api/tutor/coverage?subject=...` returns 422 for an unknown
  subject and 403 without the token or from another address. It is absent
  from the student app.
- **Source of truth:** `BankComposer.available_sizes`, the student
  availability's own call. Pending questions never count as available.
  Total inventory is shown only beside the per-size result.
- **Command line:** `python -m app.practice.replenish capacity [--subject S]`
  gives the same report plus the plan's structural limits.

Screenshots (synthetic data): [coverage, phone](screenshots/T069/t069-coverage-390.png),
[coverage, desktop](screenshots/T069/t069-coverage-1280.png),
[size 30 form, desktop](screenshots/T069/t069-1280-1-form-30.png),
[result after 30 questions, phone](screenshots/T069/t069-390-3-summary.png).

## Unchanged

- `BankComposer`, the availability rule (T063), the student UI, the
  practice routes and jobs (RCA-006 guarded files are untouched).
- The seeding plan, the scheduler, the review flow and eligibility: nothing
  is approved or quarantined automatically.
- Spending: no model call in any new path. The capacity check is pure
  counting.

## Regression guards

- **RCA-006:** no guarded file changed. `test_quiz_sizes.py` and
  `test_bank_only_practice.py` pass. The new tests extend the "offered means
  it starts" check to four subjects and every size.
- **RCA-005:** `ci.yml` only adds the T069 browser tests to the existing
  browser step, whose executed count must now be at least 5. No dependency
  was added.
- **RCA-003:** untouched.

## Verification

- New tests:
  - `tests/app/test_capacity.py`: 10 passed;
  - `tests/app/test_quiz_sizes_subjects.py`: 7 passed, plus 2 browser tests
    passed with `MENTOR_PRO_BROWSER=1`;
  - `tests/app/test_tutor_coverage.py`: 5 passed, plus 2 browser tests
    passed.
- **Local ACE gate** (`bash .ace/scripts/verify.sh`, log
  `.ace/logs/verify/20261115-201742-1030`): 1189 passed, 14 skipped,
  5 failed.
  - All 5 failures are in `tests/app/test_deploy_backup.py`, with
    "disposable PostgreSQL did not start".
  - On this workstation a Windows Application Control policy blocks
    `initdb.exe`. That is environmental and unrelated to T069; no deploy
    file changed.
  - Those tests run in CI (Linux).
  - Markdown lint: 0 issues. Skill validation passes (36 skills, 0
    problems).
- **CI:** see the PR.
