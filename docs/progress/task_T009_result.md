# Task T009 Result: Mathematical Validation Correctness

> **Date:** 2026-10-23
> **Status:** Done — checker 1.6.0
> **RCA:** [RCA-002](../rca/RCA-002-math-proof-not-establishing-question.md)

---

## Defect

The maths checker accepted a deterministic proof whenever its value matched
exactly one option. It never checked that the proof answers the question:

- `select: max` (T008 slot 3) found the largest option for "¿Cuál es la
  mayor cantidad de equipos … de modo que … sea múltiplo de 3 y par?".
- `3 * 6` (T007) evaluated to 18 for "múltiplo de 3 y a la vez par"; 1.5.0
  only caught it when the stem said "¿Cuál de los siguientes…?".

Such items skipped the blind solve. The keys were correct (verified by hand),
but only the generating model had established the property.

---

## Proof Types Inspected

| Proof | What it establishes | Gap before 1.6.0 |
|-------|---------------------|------------------|
| `expression` (M01, M03) | Exact value; exactly one option equals it | Not that the value is what the stem asks |
| Operand grounding (M04, 1.3.0) | Operands come from the item text or small constants | Same |
| Property-selection stem (M04, 1.5.0) | "¿Cuál de los siguientes…?" / "podría" → blind solve | Other phrasings; `select` not covered |
| `select: min\|max` (M03) | Which option is smallest or largest | Not that the stem asks for that extreme, or adds conditions |

---

## Correction (checker 1.6.0)

A proof counts (`math_proven: true`) only if it establishes what is asked:

1. **Properties:** no number property in the stimulus or stem — múltiplo,
   divisor, divisible, par, impar, primo, compuesto, factor, "de modo que",
   "que cumpla", "cumple", "a la vez", "podría", "posible". Applies to both
   proof types.
2. **`select`:** the stem asks for that extreme (mayor/menor, más
   grande/pequeño, máximo/mínimo, más alto/bajo, más largo/corto) and adds no
   comparison condition (entre, pero, si fue, mayor que, menor que, excepto,
   sin contar, segundo, tercero, penúltimo, ordenar) and no opposite extreme.

Otherwise M04 is a warning, `requires_independent_solve` is true, and the
item is accepted only with an agreeing blind solve. A disagreeing solve gives
`regenerate`; an unavailable solve gives `pending`. Neither is accepted.
Matching uses whole words on accent-stripped text ("para" ≠ "par").

Unchanged: curriculum, budgets, concurrency, schemas, prompts, student
interface, and every other check.

---

## Regression Results

| Test | Result |
|------|--------|
| T008 slot 3 (`select: max` + "de modo que … múltiplo de 3 y par") | Not proven → solve required |
| Largest option violates the property (30 for 72 alumnos) | M03 fail, never accepted |
| T007 `3 * 6` without "¿Cuál de los siguientes…?" | Not proven |
| Property only in the stimulus | Not proven |
| `select` when the stem asks "segundo lugar", a range, the opposite extreme or no extreme | Not proven (4 cases) |
| Valid proofs: T007 slot 2 (`select: max`), T008 slot 2 (`select: min`), `1236 / 12`, `144 / 6` | Still proven |
| "Para … para cada aula" | Still proven |
| Pipeline: property question with agreeing / disagreeing / unavailable solve | accepted / rejected / rejected |
| Mutation: `_unproven_reason` always `None` | 9 tests fail |
| Full suite | 298 passed |
| ACE gate | `VERIFY_RESULT=pass gate=all` |

### Re-check of every accepted Matemáticas item (18)

| Change under 1.6.0 | Items |
|--------------------|-------|
| Newly unproven | 1 — T008 `set-5b7eb9ee` slot 3 (`req-6f0f451b`), the defect |
| Already unproven since earlier fixes | 2 — T006 `148/100`, T007 `3 * 6` |
| Proven, still proven | 6 |
| Not proven, verified by an agreeing blind solve | 9 (unchanged) |

No previously valid proof is lost. Historical records are left as audit
data; `set-5b7eb9ee` slot 3 was validated under checker 1.5.0 only.

---

## Validation Limitations

1. Cues are Spanish keyword heuristics. A property phrased without them (for
   example "se puede repartir sin que sobre") still counts as proven if the
   arithmetic matches. Mitigation: the rubric and human spot checks.
2. Conservative by design: incidental words ("un par de zapatos", "posible")
   force a blind solve that is not strictly needed (one extra call).
3. The blind solve is a single free model; agreement is evidence, not proof.
   The checker cannot verify properties itself (divisibility, parity) yet; a
   typed property check would make such keys provable.
4. No new live generation was run (not required); the next set will show the
   expected extra solve calls for property questions.
