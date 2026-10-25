# T028 Result: Guided Expository Composition (L4)

- **Status:** verified
- **Role:** Developer
- **ADR:** [ADR-026](../adr/ADR-026-guided-composition-l4.md);
  incident [RCA-004](../rca/RCA-004-writing-review-not-independent.md)

## Generation (real database, OpenRouter, prompt `writing-1.3`)

| Request | Result | Calls | Tokens in/out | Cost |
| --- | --- | --- | --- | --- |
| `wreq-39117d1b671b4ac8` | accepted, then found self-reviewed (RCA-004) | 5 (3 × HTTP 502 on the reviewer) | 2816 / 3276 | $0 |
| `wreq-3428d7e8f65b46dc` | accepted, independent review | 2 | 2849 / 3236 | $0 |

Valid exercise: `PE-L4-uso-responsable-materiales-aba7b0`, "El uso
responsable de los materiales escolares y su efecto en el aprendizaje".
Generator nemotron-3-ultra, reviewer nemotron-3.5-super-vl, all review
scores 2, checks W01–W08 and W13–W19 pass. Targets EE01–EE06 (mandatory)
and EE07–EE18 (optional). Four-item paragraph plan (questions, no model
text). Read in full by the developer before use; exported as the browser
fixture `scripts/dev/fixtures/writing-exercise-L4-T028.json`.

The first exercise (`PE-L4-uso-responsable-redes-f9acfc`) stays in the
bank unchanged; its review was not independent. Removal is a Product Owner
decision (RCA-004), as for three T023 L1 exercises with the same defect.

## Behavior

- Student: five stages (plan, introduction, two development paragraphs,
  conclusion, review and submit), one text area per section, the
  exercise's plan hint per stage, live word count of the composition.
  Sections are saved in `writing.draft.sections` on demand, on stage
  change, two seconds after typing stops and before leaving; a reload
  resumes the stage and text. Nothing generated fills a section.
- Submission: the four paragraphs are required and may not contain blank
  lines; `text_es` = paragraphs joined by a blank line; planning notes kept
  in `writing.submission.sections`; revision recorded; one submission.
- Tutor: plan hints, planning notes, four labeled paragraphs, composition,
  EE01–EE06 with official descriptors (required) and EE07–EE18 under
  "Convenciones (opcional)" with "Sin calificar".
- Dashboard: L4 counts, scored criteria (including optional ones scored);
  only mandatory criteria show "Evaluación pendiente".

## Validation

| Check | Result |
| --- | --- |
| `tests/app/test_writing_guided.py` | 10 passed |
| `tests/app/test_writing_review_independence.py` | 2 passed |
| Full suite (ACE gate `test`) | 507 passed |
| Browser, mocked, `mentor_pro_test`, desktop and mobile | 433/433 (34 new L4 checks) |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all` |

Artificial submissions and evaluations were made only in
`mentor_pro_test`. The real database received only the generated
exercises and their generation and usage records.

Screenshots in `docs/progress/screenshots/T028/`: stage 1, stage 3
(mobile), review, submitted, tutor, student feedback, dashboard.

## Limitations

- One working free generator; the reviewer often answers 502, and a
  self-review now costs a rejected attempt.
- W19 scope words are keyword-based.
- A reload with unsaved typing younger than two seconds triggers the
  browser's leave warning; text typed and then discarded there is lost.
- Paragraph boundaries rely on one section per paragraph; line breaks
  inside a section are kept, blank lines are refused.
