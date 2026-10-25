# Task T026 Result: Human Tutor Writing Evaluation

> **Date:** 2026-10-25
> **Status:** Done
> **Decision:** [ADR-024](../adr/ADR-024-tutor-writing-evaluation.md)

---

## Changes

| File | Change |
|------|--------|
| `app/writing/tutor.py` (new) | `/api/tutor`: queue, submission detail, save/complete evaluation; local tutor boundary |
| `app/static/tutor.html`, `app/static/tutor.js` (new) | "Revisión del tutor": code entry, queue, evaluation screen with official descriptors, partial save, completion dialog |
| `app/writing/store.py` | One evaluation per submission; `exercise_revision`, `updated_at`, `descriptor_ref`; `tutor_queue()`, `evaluation_for()`, `save_evaluation()` (completed is locked) |
| `app/writing/routes.py`, `app/static/app.js`, `index.html`, `styles.css` | Student feedback after completion; "Revisado por el tutor" |
| `app/main.py`, `curriculum/db.py` | Tutor router only with `MENTOR_PRO_TUTOR_TOKEN` (environment or `.env`) |
| `.env.example` | `MENTOR_PRO_TUTOR_TOKEN=` (empty disables review) |
| `scripts/dev/practice_e2e.py`, `tests/app/test_writing_tutor.py` (new) | Tutor scenario (desktop, mobile); 8 API tests |

No change to the rubric, curriculum, multiple choice or generation; no
OpenRouter calls; no automatic grading.

---

## Acceptance (test database)

| Step | API test | Browser (desktop, mobile) |
|------|----------|---------------------------|
| 1 Student submits an L1 correction | Pass | Pass |
| 2 Tutor opens the pending submission | Pass | Pass (queue: 3 pending) |
| 3 Reference correction and official criteria shown | Pass (descriptors equal the rubric file) | Pass (five EE07 descriptors) |
| 4 Scores and feedback | Pass | Pass |
| 5 Partial save and resume | Pass | Pass (after reload) |
| 6 Completion (needs every evaluable criterion) | Pass (422 when incomplete) | Pass |
| 7 Student sees scores and feedback | Pass (points, descriptor, comments, improvements, date) | Pass |
| 8 Student never sees the reference | Pass (all student responses) | Pass (HTML and browser storage) |
| 9 No handwriting scores on typed work | Pass (EE19 score refused; stored as not evaluable) | — |
| 10 Duplicate completion prevented | Pass (409) | Pass (locked form; server 409) |
| L2 and L3 paths | Pass (introduction, development, conclusion) | Pass |
| Boundary | Pass: no token → 404; missing or wrong code → 403; non-loopback host → 403; short token rejected | Pass: wrong code refused; student request 403 |

Integrity: the evaluation stores rubric ID and checksum, the exercise
revision answered and `descriptor_ref` per score; the submission text and
revision are unchanged; one evaluation per submission.

Screenshots: [queue](screenshots/T026/desktop-tutor-queue.png),
[evaluation (mobile)](screenshots/T026/mobile-tutor-evaluation.png),
[student feedback](screenshots/T026/desktop-tutor-student-feedback.png).

---

## Live Configuration

`MENTOR_PRO_TUTOR_TOKEN` was added to the local `.env` (git-ignored). On
the running app: `/tutor` 200; `/api/tutor/queue` 403 without or with a
wrong code, 200 with the code (empty: no real submissions); the student
page does not link to `/tutor`; multiple choice and dashboard 200. No
submission or evaluation was created in the student database.

## Verification

- Suite 489 passed; browser 363/363; `VERIFY_RESULT=pass gate=all`.

## Limitations

- The boundary is a local code, not authentication (ADR-024).
- A completed evaluation cannot be reopened.
- Feedback lists are one item per line; no rich text.
