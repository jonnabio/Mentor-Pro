---
name: question-quality-review
description: Validates generated PNE items before they enter the question bank using one deterministic checker for all four subjects (structure, grounding, duplicates, subject checks), a blind independent solve and a rubric, then returns a ValidationResult with an accept, revise, regenerate or reject verdict. Use whenever a candidate item is produced or changed.
---

# Skill: Question Quality Review

> Sole owner of the publish decision. Fails closed.

---

## Purpose

Verify alignment, correct key, ambiguity, distractor plausibility, language,
difficulty, duplicates and completeness, and decide what happens to the item.

Shared rules: `.ace/standards/question-engine.md`.

---

## Activation

Use when an item is generated, revised, imported or its sources change.

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `items` | Yes | QuestionItem JSON (one or a list) |
| `records` | Yes | Curriculum records cited by the items |
| `bank` | No | Existing bank items for duplicate detection |
| `facts` | No | Reviewed fact strings for Ciencias / Estudios Sociales |
| `option_count` | No | Required number of options |

---

## Outputs

One ValidationResult per item:
`.ace/schemas/question-engine/validation-result.schema.json`
(example: `.ace/schemas/question-engine/examples/validation-result.json`).

---

## Procedures

### 1. Deterministic checks (always first)

```bash
.venv/Scripts/python.exe .ace/skills/question-quality-review/scripts/item_checker.py \
  items.json --records records.json [--bank bank.json] [--facts facts.json] [--option-count 4]
```

| ID | Applies to | Check |
|----|-----------|-------|
| C01 | All | Schema valid |
| C02 | All | Option labels A… in order; required count |
| C03 | All | Key references exactly one option |
| C04 | All | Options distinct (exact and near-identical) |
| C05 | All | No "todas/ninguna de las anteriores", "a y b" … |
| C06 | All | Rationale for every distractor |
| C07 | All | Stem ≤ 120 words, options ≤ 30 words |
| C08 | All | Stimulus present when the stem refers to one |
| C09 | All | Key length cue: fails if key ≥ 1.5× and ≥ 12 chars longer than the longest distractor |
| L01 | All | No announced content left unshown (stimulus ending in `:`; math data cue without numbers) |
| L02 | Matemáticas | Unit named in the text → every option carries a unit |
| L03 | All | Stem question marks paired (`¿…?`) and the question is complete |
| G01 | All | Chain, subject, application; record official or approved baseline (ADR-006) |
| G02 | All | Every excerpt verbatim in a groundable record |
| G03 | All | Cognitive verb appears in the evidencia (warning) |
| D01 | All | No exact or near duplicate (bank and siblings) |
| M01–M03 | Matemáticas | Exact expression or `select: min\|max`; es-CR numbers and units; only the key matches |
| M04 | Matemáticas | Expression operands from the item text; property-selection stems ("¿Cuál de los siguientes…?") need a blind solve |
| R01–R03 | Español | Passage ≥ 40 words; quoted spans and key support verbatim |
| F01–F02 | Ciencias, Estudios Sociales | Support terms grounded and used by key/explanation |

Any `fail` → exit code 1 and a provisional verdict: `reject` for G01/G02,
otherwise `regenerate` (step 4). All pass → `pending` until steps 2–3.

### 2. Independent solve (when `requires_independent_solve`)

```markdown
1. Send stimulus, stem and options only — no key, explanation or rationales.
2. Use a different model from the generator when available.
3. Ask for one label or "AMBIGUOUS". Parse deterministically.
4. agrees_with_key = (chosen_label == answer_key).
```

Only Matemáticas items with `math_proven: true` may skip this step.

### 3. Rubric (0–2 each)

| Criterion | 2 means |
|-----------|---------|
| `alignment` | Task exercises the evidencia's verb and concept |
| `clarity` | Single reading; no ambiguity |
| `distractor_quality` | Each distractor maps to a plausible misconception |
| `language` | Correct es-CR, age-appropriate, no idioms from other regions |
| `difficulty_match` | Cognitive demand matches requested level |

### 4. Verdict rules

| Condition | Verdict |
|-----------|---------|
| Deterministic fail on G01/G02 (grounding) | `reject` |
| Other deterministic fail, or solve disagrees / says AMBIGUOUS | `regenerate` (max 2 per slot), then `reject` |
| All pass, any rubric criterion = 0 | `regenerate` |
| All pass, any rubric criterion = 1 | `revise` (one attempt), re-run all checks |
| All pass, all rubric criteria = 2, solve agrees or math proven | `accept` |
| Independent solve unavailable | `pending`; never publish |

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `mep-curriculum-grounding` | Defines what a valid curricular link is |
| `math-answer-verification` | Procedure behind checks M01–M03 |
| `mep-question-design` | Receives revise / regenerate notes |
| `openrouter-model-routing` | Runs independent solve and rubric calls |
| `question-evaluation` | Aggregates verdicts into metrics |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| Checker input error (exit 2) | Treat the batch as not validated; fix input |
| jsonschema missing (C01 warn) | Install `requirements-dev.txt`; do not publish |
| Rubric model returns invalid output | Retry once; else `pending` |
| Item edited after `accept` | New item version; full review again |

---

## Examples

### Accept

ES item `Q-PNE2025-PRI-ESP-DIAG-B1-A1-E8-7b21e0aa`: checks pass, solver picks B
(= key), rubric 2/2/2/2/2 → `accept`.

### Reject

Math item whose options include "1.000": M02 fails (ambiguous number) →
`regenerate`; after two failures → `reject`.

Tests: `tests/ace/test_item_checker.py`.

---

## Common Pitfalls

1. **Showing the key to the solver**: invalidates the independent solve.
2. **Treating structural pass as correctness** for non-math subjects.
3. **Skipping sibling duplicate checks** within one generated batch.
4. **Letting the generator grade itself**: reviewer model must differ when possible.

---

## Invocation

```markdown
"Apply the question-quality-review skill from
.ace/skills/question-quality-review/SKILL.md to validate the batch in
items.json against the PNE2025 records."
```
