# RCA-002: Math Proof Accepted Without Establishing the Question

> **Status:** Verified
> **Severity:** High
> **Created:** 2026-10-23
> **Resolved:** 2026-10-23
> **Owner:** Incident Responder (T009)

---

## Issue Summary

The deterministic maths checker marked a question as proven when its proof
(`select: max`, or an expression such as `3 * 6`) pointed at the key without
checking the property the question asked for ("múltiplo de 3 y par"). Such
items skipped the independent blind solve. Keys found so far were correct,
but correctness rested only on the generating model.

---

## Timeline

| When | Event |
|------|-------|
| T006 (2026-10-22) | `148/100` restated a key; M04 operand grounding added (1.3.0) |
| T007 (2026-10-23) | `3 * 6` "proved" 18 is a multiple of 3 and even; M04 cue for "¿Cuál de los siguientes…?" (1.5.0) |
| T008 (2026-10-23) | `select: max` "proved" 24 for "mayor cantidad … de modo que … múltiplo de 3 y par" |
| T009 (2026-10-23) | Checker 1.6.0: proof must establish what is asked |

---

## Symptoms

- `math_proven: true`, `requires_independent_solve: false` on a property
  question (`set-5b7eb9ee`, slot 3, `req-6f0f451b`).
- No blind-solve call for that item.

---

## Root Cause Analysis

### The 5 Whys

1. Why was the item accepted without a blind solve? The checker reported
   `math_proven: true`.
2. Why proven? M03 found that exactly one option equals the proof value, and
   M04 only checked where expression operands came from.
3. Why was that enough? The checker treated "the proof value matches one
   option" as "the key is correct", whatever the question asked.
4. Why did that hold for `select`? `select: min|max` was designed for pure
   comparison stems; nothing checked that the stem asks for that extreme
   without further conditions.
5. Why was it not caught earlier? Fixes in T006 and T007 patched specific
   symptoms (foreign operands, one stem phrasing) rather than the general
   rule.

### Root Cause Statement

The checker verified that a proof is internally consistent with the options,
not that it answers the question being asked.

### Contributing Factors

- The generator chooses the proof type and can pick one that is easy to
  satisfy.
- Rubric scoring (model-based) also accepted the item.

---

## Resolution

### Immediate Fix

None needed for live data: keys were verified by hand; set `set-5b7eb9ee`
slot 3 is recorded as validated under checker 1.5.0 only.

### Permanent Fix

Checker 1.6.0 (`_unproven_reason`): a proof counts only if

- no number property (múltiplo, divisor, divisible, par, impar, primo,
  compuesto, factor, "de modo que", "que cumpla", "a la vez", "podría",
  "posible") appears in the stimulus or stem; and
- for `select: min|max`, the stem asks for that extreme (mayor/menor, más
  grande/pequeño, máximo/mínimo …) and adds no comparison condition (entre,
  pero, si fue, mayor que, menor que, excepto, segundo, tercero, ordenar) and
  no opposite extreme.

Otherwise M04 warns and the item needs an agreeing blind solve; a missing or
disagreeing solve is not accepted (`pending` / `regenerate`).

---

## Regression Prevention

### Tests Added

- `tests/ace/test_item_checker.py`: T008 slot 3 (`select: max`), largest
  option violating the property (M03 fail), T007 `3 * 6` without the
  "¿Cuál de los siguientes…?" phrasing, property in stimulus only, four
  `select` stems that do not ask the extreme, preserved valid proofs (T007
  slot 2, T008 slots 2 and 5, plain division), "para" not a property cue.
- `tests/app/test_generation.py`: property question accepted only with an
  agreeing blind solve; rejected when the solve disagrees or is unavailable.

### Standards Updated

`.ace/skills/question-quality-review/SKILL.md` (M04 row) and ADR-010.

### Knowledge Base Updated

`docs/progress/task_T009_result.md`.

### Regression Guard

`docs/rca/regression-guards.yaml`, entry RCA-002.

---

## Verification

### Fix Verification

All 18 accepted Matemáticas items re-checked offline: only the T008 slot 3
item newly loses its proof; the two others that change were already caught
(T006 `148/100`, T007 `3 * 6`). No previously valid proof is lost.

### Prevention Verification

Mutation: making `_unproven_reason` return `None` fails 9 tests.

---

## Lessons Learned

### What went well

- Hand verification of every key in T007/T008 reports exposed the defect.

### What could improve

- Fix the general rule, not the observed phrasing.

### Action items

- Keyword cues are heuristic: unusual phrasing of a property can still slip
  through; human spot checks of maths items remain needed.

---

## References

- [ADR-010](../adr/ADR-010-single-question-generation.md)
- `docs/progress/task_T008_result.md`, `docs/progress/task_T009_result.md`

---

## Sign-off

- Incident Responder (T009), 2026-10-23
