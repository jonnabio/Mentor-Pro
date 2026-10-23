# ADR-010: Single Curriculum-Grounded Question Generation

> **Status:** Accepted (Product Owner task T006)
> **Date:** 2026-10-21

---

## Context

T006 requires one validated multiple-choice question per request, grounded in
baseline `PNE2026-SUM-v1.0`, generated through the ADR-009 OpenRouter router,
with model, tokens, cost and validation recorded. Invalid questions must be
rejected, and the key must not reach students before they answer.

---

## Decision

### Pipeline (`app/generation/`)

1. **Grounding** (`grounding.py`): objective, verbatim assertion, evidencias,
   concepts and source from the catalog; one evidencia (explicit ordinal or
   the first). Rubric (`EE`) and ungroundable objectives abstain.
2. **Prompt** (`prompts.py`, `item-generation` 1.0.0): curriculum passed as
   delimited data; *forma actual* context; difficulty as cognitive demand;
   four options; subject-specific check blocks; JSON only.
3. **Parsing** (`parsing.py`): only model-authored fields are kept; IDs,
   curriculum reference, verbatim excerpt, `grounding_basis` and generation
   metadata are set by code.
4. **Validation**: shared deterministic checker (1.2.0) with concepts as
   reviewed facts → blind independent solve on a different free model
   (skipped only when the math key is proven) → rubric on a different model.
5. **Verdict**: `question-quality-review` table. Up to two generation
   attempts; only `accept` is a valid question.

### Mathematics

- New `subject_checks.math.select` (`min` \| `max`) for comparison items: the
  checker computes the answer from the option values.
- An `expression` must contain an operator; a bare number would restate the
  model's key and is rejected.
- Checker 1.3.0 (M04): expression operands must appear in the item text or be
  2–10, 100 or 1000; otherwise the key is not proven and a blind solve is
  required (e.g. `148/100` for a key of 1,48).

- Checker 1.4.0 (C09, PO decision 2026-10-22): a material key-length cue
  fails (`regenerate`). Material means the key is at least 1.5× and at least
  12 characters longer than the longest distractor; the gap keeps short
  numeric or one-word options from failing. Prompt 1.2.0 asks for options of
  similar length.
- `validation.attempts` keeps every generation attempt's verdict and reasons.
- Checker 1.6.0 (T009): a deterministic proof counts only if it establishes
  what the stem asks. A number property (múltiplo, par, primo, divisible,
  "de modo que"…) in the stimulus or stem leaves any proof unproven;
  `select: min|max` proves a key only when the stem asks for that extreme
  without further conditions (entre, pero, segundo, mayor que…). Unproven
  items need an agreeing blind solve; without one they are not accepted.

### Live hardening (2026-10-22)

- Candidates: free, text-input, text-only-output models; pin with
  `OPENROUTER_FREE_MODELS`.
- 401 stops routing; 403 skips the model; truncated replies are
  `invalid_output`.
- Token limits: generation 4000, solve 2000, rubric 3000.
- Parsers ignore leaked reasoning; `subject_checks` keeps only known keys.

### Records

- Usage per call: `llm.usage_record` (ADR-009), purposes `generation`,
  `independent_solve`, `review`.
- Per request: `generation.question_attempt` — objective code, evidencia,
  difficulty, status, verdict, models, calls, tokens, cost, validation, item.

### Exposure

- `POST /api/dev/questions/generate` exists only when
  `MENTOR_PRO_DEV_ENDPOINTS=true`; otherwise 404.
- Accepted: `item` (with key, for developers) and `student_view` (no key,
  explanation or rationales). Rejected: `rejected_draft` only, never `item`.
- Student routes are unchanged and never return keys.

---

## Alternatives Considered

### Alternative 1: Trust model-provided metadata

- **Pros:** Simpler prompt handling.
- **Cons:** Models can invent IDs or claim official provenance.
- **Why rejected:** Fail-closed provenance rule.

### Alternative 2: Skip the rubric to save calls

- **Pros:** Fewer calls.
- **Cons:** Violates the review skill's accept rule.
- **Why rejected:** Free models make the extra calls cost-neutral.

---

## Consequences

### Positive

- No question is reported valid without deterministic checks plus either a
  math proof or an agreeing blind solve, and a full-score rubric.

### Negative

- Three model calls per accepted non-math question; acceptance depends on
  free-model quality.

### Neutral

- Rubric scores come from a model and are not ground truth.

---

## Related

- [ADR-006](ADR-006-curriculum-baseline-v1.md), [ADR-009](ADR-009-openrouter-integration.md)
- Report: `docs/progress/task_T006_result.md`
