---
name: math-answer-verification
description: Independently proves Matemáticas answer keys with exact rational arithmetic, es-CR number formats (decimal comma, space thousands), units, fractions and equivalence, and confirms exactly one option is correct; covers geometry, statistics and probability by reducing them to exact expressions. Use for every math item and whenever math parsing or number formatting is involved.
---

# Skill: Math Answer Verification

> Prove the key deterministically, or mark the item unverifiable.

---

## Purpose

- Validate calculations exactly (no floating point).
- Check equivalence between fractions, decimals and mixed numbers.
- Verify units and Costa Rican number formatting.
- Detect rounding and precision errors.
- Confirm a unique correct option.

Implementation: `.ace/skills/question-quality-review/scripts/cr_math.py`
(used by checks M01–M03 of the shared item checker).

---

## Activation

Use for every `matematicas` item, and when designing items whose options are
numbers, measures or money (₡).

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `subject_checks.math.expression` | One of | Exact expression (with an operator) whose value is the key |
| `subject_checks.math.select` | One of | `min` or `max`: comparison items; the checker picks the option value |
| `subject_checks.math.unit` | No | Expected unit shared by all options (e.g. `cm`, `kg`, `₡`) |
| `options` | Yes | Option texts as shown to students |
| `answer_key` | Yes | Label of the intended answer |

---

## Outputs

Checker entries M01–M03 plus `math_proven` in the ValidationResult:

```json
{ "id": "M03", "status": "pass", "message": "expression = 12; only the key matches" }
```

`math_proven: true` only when every option parsed, values are distinct and
exactly the key equals the expression.

---

## Procedures

### 1. Encode the solution as an expression

| Topic | Encoding |
|-------|----------|
| Arithmetic, money | `2500 * 3 - 1200` |
| Fractions | `3/4 + 1/8` |
| Decimals | `12,5 * 4` |
| Perimeter / area | `2 * (8 + 5)`, `8 * 5 / 2` |
| Mean | `(7 + 9 + 8) / 3` |
| Probability (equally likely) | `3 / 8` |
| Unit conversion | `2,5 * 1000` (state unit `m` in `unit`) |

Allowed syntax: integers, decimal comma, `+ - * / ( )`. No powers, names or calls.

### 1b. Comparison items

"¿Cuál es el menor / mayor…?" items use `select: min` or `select: max`; the
checker computes the answer from the option values. A bare number as
`expression` is rejected because it restates the key instead of proving it.

### 2. Format options in MEP style

| Input | Value | Note |
|-------|-------|------|
| `12 500` | 12500 | Space groups thousands |
| `3,25` | 13/4 | Decimal comma |
| `2 1/2` | 5/2 | Space before a fraction = mixed number |
| `₡12 500` | 12500, unit `₡` | Colón sign as unit |
| `1.000`, `2.5` | — | Rejected: ambiguous |

### 3. Verify

```bash
.venv/Scripts/python.exe .ace/skills/question-quality-review/scripts/item_checker.py items.json --records records.json
```

### 4. Precision and rounding

- If the task asks to round, encode the rounded value explicitly and state the
  rounding rule in the stem ("redondee a la décima").
- Distractors that differ only by rounding must be justified in the rationale.

### 5. Non-numeric math items

Items whose options are figures, classifications or statements (e.g.
*Clasifica triángulos*) cannot be proven by expression. Set no `math` block,
expect M01 to fail, and route to an independent solve with a geometry-specific
rubric. Do not publish without it.

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `question-quality-review` | Owns the checker and the verdict |
| `mep-question-design` | Must supply the expression and unit |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| `AmbiguousNumberError` | Regenerate with MEP formatting |
| Expression not evaluable | Regenerate; never guess the intended expression |
| Two options equal the expression | Regenerate (non-unique key) |
| Key ≠ expression value | Reject the key; regenerate |
| Unit mismatch | Regenerate with consistent units |

---

## Examples

### Proven

`expression: "144 / 12"`, options 10/12/14/132, key B (= 12) → `math_proven: true`.

### Caught

Options "1/2" and "0,5" in the same item → M02 fail (equal values).

Tests: `tests/ace/test_cr_math.py`.

---

## Common Pitfalls

1. **Float arithmetic**: `0,1 + 0,2` must equal exactly `3/10`.
2. **Dot as separator**: never valid in MEP style.
3. **Letting the LLM compute the key** without an expression.
4. **Thousands spaces inside expressions**: write `12500` inside `expression`.

---

## Invocation

```markdown
"Apply the math-answer-verification skill from
.ace/skills/math-answer-verification/SKILL.md to prove the keys of the
Matemáticas items in items.json."
```
