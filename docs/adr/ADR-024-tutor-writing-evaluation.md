# ADR-024: Human Tutor Writing Evaluation

> **Status:** Accepted (Product Owner task T026)
> **Date:** 2026-10-25

---

## Context

Students submit typed writing (ADR-021) that waits for "revisión del
tutor". The tutor needs to review submissions with the official rubric
(ADR-019) and the tutor-only reference corrections (ADR-022, ADR-023), and
the student needs to see the result. The application has no accounts.

---

## Decision

### Tutor boundary (not authentication)

- The tutor router (`/api/tutor`) and page (`/tutor`) exist only when
  `MENTOR_PRO_TUTOR_TOKEN` is set (environment or `.env`, at least 16
  characters). Without it they return 404.
- Every tutor request must come from a loopback address (`127.0.0.1`,
  `::1`) and carry the token in `X-Tutor-Token`, compared in constant time;
  otherwise 403.
- The student UI never links to `/tutor`; student endpoints never read
  tutor data.

**Limitations.** Whoever can use the computer and knows the code is the
tutor. The code is kept in the tutor tab's `sessionStorage`; on a shared
browser profile a student who opens that tab could read it. The server is
plain HTTP on localhost. This boundary prevents accidental exposure, not a
determined local user; real separation needs accounts or a separate device,
which this single-student application does not have.

### Workflow

- Queue: every submission with title, level, date, status (`pending`,
  `in_progress`, `completed`) and target criteria.
- Evaluation screen: instructions, text with errors (L1), the read-only
  student text, the reference correction of the revision answered, and each
  target criterion with its official wording and its five official
  descriptors as the score options. EE19/EE20 on typed work are shown as
  "No evaluable" and cannot be scored.
- Partial evaluations are saved and resumed (`in_progress`). Completion
  requires every evaluable criterion and locks the evaluation (409 after
  that). No examination grade is computed.

### Data

One evaluation per submission (`uq_evaluation_submission`), written through
`contracts.validate_evaluation`. Each evaluation stores the rubric ID and
checksum and the exercise revision answered; each score stores
`descriptor_ref` (`MEP-RUBRICA-PE-2026#EE07@3`). The submission is never
changed.

### Student feedback

After completion the student view adds `feedback`: per criterion the
official statement, the points out of 4 and the matching official
descriptor (or "No evaluable"), the tutor's comments, areas to improve, an
optional next step and the date; the status reads "Revisado por el tutor".
The reference correction is never included.

---

## Consequences

- Reopening a completed evaluation is not possible; a correction would need
  a new, explicit feature.
- Descriptors become visible to the student only after evaluation, as
  feedback.

---

## Related

- [ADR-019](ADR-019-produccion-escrita-foundation.md),
  [ADR-021](ADR-021-student-writing-practice.md),
  [ADR-022](ADR-022-nivel-1-correction-exercises.md),
  [ADR-023](ADR-023-l1-editor-and-editorial-revisions.md)
- `docs/progress/task_T026_result.md`
