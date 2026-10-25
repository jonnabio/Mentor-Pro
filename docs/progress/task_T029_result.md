# T029 Result: Writing Exercise Independent-Review Remediation

- **Status:** verified
- **Role:** Developer (incident remediation)
- **ADR:** [ADR-027](../adr/ADR-027-writing-exercise-eligibility.md);
  [RCA-004](../rca/RCA-004-writing-review-not-independent.md)

## Affected exercises and outcome

Identified from `writing.generation_attempt` and `llm.usage_record`
(generator and reviewer both `nvidia/nemotron-3-ultra-550b-a55b:free`):

| Exercise | Quarantined | Independent review | Final |
| --- | --- | --- | --- |
| `PE-L1-futbol-comunidad-f136a4` | yes | 1.0 unavailable (truncated); 1.1 passed, super-vl | eligible |
| `PE-L1-manglares-terraba-cafb78` | yes | 1.0 unavailable (truncated, 502); 1.1 passed, super-vl | eligible |
| `PE-L1-feria-ciencia-escuela-c9576f` | yes | 1.0 and 1.1 unavailable (no valid review) | quarantined |
| `PE-L4-uso-responsable-redes-f9acfc` | yes | 1.0 passed, super-vl | eligible |

No exercise failed on content; the one remaining quarantined exercise has
no independent review yet. Replacement: one L1 exercise,
`PE-L1-huerta-escolar-8c310b` (EE16–EE18, generator nemotron-3-ultra,
reviewer nemotron-3.5-super-vl, all review scores 2), read by the developer.

Final eligible inventory: L1 3, L2 3, L3 3, L4 2 (minimum 3/3/3/1).

## Fixes

- `route(exclude=…)`: writing reviews at every level exclude the generator;
  an outage ends as `unavailable`, never a self-review.
- L1 reviews: own 6000-token limit (the reviewer truncated 4 of 6 L1
  reviews at 3000).
- Eligibility events and independent validations (append-only); students
  see eligible exercises only; submitted work stays readable.
- Found during the run: the first rerun re-quarantined the reinstated L4
  exercise (event 6). The quarantine step is now once per exercise
  (regression test), and event 9 reinstated it with its passed validation.

## OpenRouter usage (T029, real database)

18 usage records: 13 518 input and 48 551 output tokens, $0 (free models;
daily USD budget 0, 30 of 1000 daily requests used on 2026-10-25). Includes
7 revalidation requests and 5 L1 generation requests (4 rejected by W09/W11
or exhausted, 1 accepted). Every failed reviewer attempt is in
`llm.usage_record`.

## Validation

| Check | Result |
| --- | --- |
| `tests/app/test_writing_revalidation.py` | 9 passed |
| `tests/app/test_writing_review_independence.py` | 4 passed |
| Full suite (ACE gate `test`) | 518 passed |
| Browser, mocked, `mentor_pro_test`, desktop and mobile | 437/437 (quarantine hidden and reinstated) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |

Backup before the real changes:
`%USERPROFILE%\mentor-pro-backups\mentor_pro_pre_T029_2026-10-25.dump`
(schemas `writing`, `llm`). No student work was written to the real
database; exercise records, revisions, references, attempts, drafts and
submissions are unchanged.

## Remaining risks

- One independent reviewer (nemotron-3.5-super-vl) for one generator
  (nemotron-3-ultra); it often answers 502 or truncates. Its outage blocks
  all new exercises and revalidations (reported, never bypassed).
- `PE-L1-feria-ciencia-escuela-c9576f` stays quarantined until a later
  revalidation passes (`scripts/dev/remediate_writing_review.py`).
- Adding a second working free reviewer model remains the main fix.
