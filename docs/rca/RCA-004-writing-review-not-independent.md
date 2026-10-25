# RCA-004: Writing Exercises Reviewed by Their Own Generator

> **Severity:** Medium (quality policy; no student data affected)
> **Date:** 2026-10-25
> **Task:** T028
> **Status:** Fixed for new exercises; four stored exercises flagged

---

## Issue Summary

ADR-020 requires W08 to be an independent review by another free model.
The first T028 L4 exercise (`PE-L4-uso-responsable-redes-f9acfc`) was
accepted with a review by `nvidia/nemotron-3-ultra-550b-a55b:free`, the
model that generated it. The reviewer model had answered HTTP 502 three
times.

---

## Evidence

`llm.usage_record` for request `wreq-39117d1b671b4ac8`: generation on
nemotron-3-ultra (ok); review on nemotron-3.5-super-vl, three `http_502`;
review on nemotron-3-ultra (ok). A query over every accepted
`writing.generation_attempt` found the same pattern for the three T023 L1
exercises (`PE-L1-futbol-comunidad-f136a4`,
`PE-L1-manglares-terraba-cafb78`, `PE-L1-feria-ciencia-escuela-c9576f`).

---

## 5 Whys

1. Why was the exercise self-reviewed? `route()` fell back to the generator.
2. Why could it? `avoid` only moves models to the end of the plan; it does
   not exclude them (by design, for practice blind solves).
3. Why did the writing pipeline accept it? It never compared the reviewer
   with the generator after the call.
4. Why was it not caught earlier? Tests used two healthy fake models, so the
   fallback never happened; only one free generator works in practice.
5. Why did the review still look valid? The review JSON is well-formed and
   scores 2; independence is not visible in the review itself.

**Root cause:** the W08 gate trusted `avoid` as an exclusion; nothing
checked which model actually reviewed.

---

## Fix

- `generation.same_model_review()` fails W08 ("review not independent")
  when the reviewer is the generator, in both `generation.py` (L2–L5) and
  `editing.py` (L1). The attempt is rejected and retried; it is never stored
  as an exercise.
- A compliant L4 exercise was generated (`PE-L4-uso-responsable-materiales-aba7b0`,
  reviewer nemotron-3.5-super-vl).
- The four self-reviewed exercises are not changed or deleted; removing or
  re-reviewing them is a Product Owner decision.

### T029 remediation ([ADR-027](../adr/ADR-027-writing-exercise-eligibility.md))

- The four exercises were quarantined (append-only eligibility events)
  and revalidated with the generator excluded from routing.
- A sixth "why" for the L1 cases: at the 3000-token review limit the only
  independent reviewer truncated 4 of its 6 L1 reviews, so the review fell
  through to the generator. L1 reviews now have their own 6000-token limit.
- `route(exclude=…)` replaces "try the generator last" for writing reviews
  at every level; an outage now ends the attempt as `unavailable`.

---

## Prevention

- Test: `tests/app/test_writing_review_independence.py` (reviewer down,
  fallback to the generator is refused).
- Guard RCA-004 in `docs/rca/regression-guards.yaml`.

---

## Lessons Learned

A preference passed to a router is not a guarantee; check the property
that the policy requires on the result (here, the model that answered).
