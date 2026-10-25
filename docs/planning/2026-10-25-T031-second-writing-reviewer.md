# Implementation Plan: T031 — Second Independent Writing Reviewer

- **Date:** 2026-10-25
- **Role:** Architect → Developer → QA Engineer
- **ADR:** [ADR-029](../adr/ADR-029-writing-review-fallback.md)
- **Guards:** RCA-004 (`app/writing/generation.py`, `editing.py`, `revalidation.py`)

## Analysis

- Writing reviews (W08, revalidation) route over `OPENROUTER_FREE_MODELS`,
  the list multiple choice also uses.
- `minimax/minimax-m3.1-flash:free` is configured but no longer listed by
  OpenRouter: `nvidia/nemotron-3.5-super-vl:free` is the only working
  independent reviewer (502 and truncation in its history).
- Self-review is detected by exact `model_used` equality; a variant suffix
  (`:free`, `:beta`) of the generator would not match.
- Revalidation allows 4 calls: after 3 failed primary attempts the fallback
  would get 1.

## Plan

1. `LlmSettings.writing_review_models` from
   `OPENROUTER_WRITING_REVIEW_MODELS` (ordered: primary, then qualified
   fallbacks). Empty keeps the current behavior.
2. `route(models=…)`: an explicit candidate list, still filtered to models
   currently listed as free text models; no silent substitution.
   `exclude` and `same_model_review` compare model identity without the
   variant suffix (`same_model`).
3. `generation.review_route()`: the one review call used by L2–L4
   generation, L1 generation and revalidation. Generator always excluded.
   The accepted review records `reviewer_model`.
4. Revalidation call cap 4 → 6 (3 attempts per reviewer, two reviewers).
   Daily request and USD budgets are unchanged.
5. `scripts/dev/benchmark_writing_reviewers.py`: discovery with a stated
   selection rule (no hardcoded candidates), 10 fixed cases built from
   stored L1–L4 exercises with in-memory seeded defects (nothing written to
   `writing`), usage recorded as purpose `evaluation` with a shared call cap.
6. Tests for the eight routing scenarios in the task.
7. Run the benchmark live, qualify or reject per ADR-029 criteria, set the
   configuration, document results in `docs/progress/task_T031_result.md`.

## Out of scope

L5, rubric changes, student-facing changes, multiple-choice routing.
