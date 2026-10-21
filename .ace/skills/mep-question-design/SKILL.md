---
name: mep-question-design
description: Designs original Spanish (Costa Rica) multiple-choice PNE practice items for sixth grade, each tied to one groundable evidencia (official or approved baseline), with configurable option count, cognitive-demand difficulty, plausible distractors, exactly one correct answer, explanations and provenance metadata in the QuestionItem JSON contract. Use when writing generation prompts or producing candidate items.
---

# Skill: MEP Question Design

> Writes candidate items from a coverage-plan slot and a grounding bundle.

---

## Purpose

- Produce *forma actual* items: a problem in a context close to the student,
  aimed at one evidencia.
- Write in Costa Rican Spanish suitable for 11–12-year-olds.
- Guarantee one correct option and plausible, diagnosable distractors.
- Emit machine-readable items with full provenance.

Shared rules: `.ace/standards/question-engine.md`.
Prompt construction and versioning: `.ace/skills/prompt-engineering/SKILL.md`.

---

## Activation

Use when:

- writing or changing a generation prompt;
- producing candidate items for a coverage-plan slot;
- regenerating or revising an item after review.

---

## Inputs

| Field | Required | Description |
|-------|----------|-------------|
| `slot` | Yes | One coverage-plan slot (evidencia, difficulty, verb, task format) |
| `grounding` | Yes | The slot's evidencia entry from the grounding bundle |
| `option_count` | Yes | 3, 4 or 5 (default 4 — assumption, not verified against MEP items) |
| `avoid` | No | Stems of sibling and bank items to avoid repeating |
| `revision_notes` | No | Reasons from `question-quality-review` |

---

## Outputs

One QuestionItem per slot, valid against
`.ace/schemas/question-engine/question-item.schema.json`.

Required subject blocks in `subject_checks`:

| Subject | Block | Content |
|---------|-------|---------|
| Matemáticas | `math` | Exact `expression` whose value is the key; optional `unit` |
| Español | `reading` | `key_support_span` copied verbatim from the passage |
| Ciencias, Estudios Sociales | `facts` | `support_terms` found in the evidencia, stimulus or reviewed facts |

Example: `.ace/schemas/question-engine/examples/items-valid.json`.

---

## Procedures

### 1. Plan the item

```markdown
1. Read the evidencia text_es and its cognitive verb.
2. Choose a task the verb demands (Identifica → locate; Aplica → solve).
3. Pick a familiar Costa Rican context (school, market, community, nature).
```

### 2. Set difficulty by cognitive demand

| Level | Demand |
|-------|--------|
| `easy` | One step, explicit information, familiar context |
| `medium` | Two steps or an inference from the stimulus |
| `hard` | Multi-step reasoning, selecting relevant from irrelevant information |

Never claim an MEP *nivel de desempeño*.

### 3. Write stem, stimulus and options

```markdown
- Stem: a complete question ending in "?"; avoid negatives; if unavoidable, write NO in capitals.
- Stimulus: required when the stem refers to a text, table, figure or map.
  Español needs an original passage (≥ 40 words).
- Options: parallel grammar, similar length, ordered logically (numbers ascending).
- Banned: "todas/ninguna de las anteriores", "a y b".
- Numbers: decimal comma (3,5), thousands with a space (12 500); never "1.000".
```

### 4. Design distractors

Each distractor reflects a specific, plausible misconception (wrong operation,
partial reading, confusing related concepts). Record it in
`distractor_rationales`. Never use a distractor that is also defensibly correct.

### 5. Explain

`explanation` (Spanish) states why the key is correct using the evidencia's
concept; it must not introduce facts absent from the grounding.

### 6. Attach provenance

Fill `curriculum_ref`, `source_refs` (verbatim excerpt), `grounding_basis`
(`official` or `approved_baseline`, from the grounding bundle) and `generation`
(model requested and used, prompt ID and version, timestamp).

---

## Dependencies

| Skill | Relationship |
|-------|-------------|
| `mep-curriculum-grounding` | Supplies the evidencia and verbatim text |
| `evidence-coverage-planning` | Supplies slots |
| `openrouter-model-routing` | Executes model calls |
| `question-quality-review` | Judges every candidate |
| `prompt-engineering` | Generic prompt versioning practice |

---

## Failure Handling

| Condition | Action |
|-----------|--------|
| Evidencia cannot be assessed with a selected-response item | Abstain for the slot; report `not_assessable_mc` |
| Needed diagram cannot be supplied | Abstain; never reference a missing image |
| Model output is not valid JSON | Request one repair via routing; then drop the slot |
| Revision notes cannot be satisfied | Return `regenerate` request, not a weaker item |

---

## Examples

### Correct (Matemáticas, easy)

Stem: "Se quieren formar grupos de 12 estudiantes con 144 estudiantes … ¿Cuántos
grupos se forman?" Options 10 / 12 / 14 / 132; `math.expression: "144 / 12"`.

### Incorrect

"¿Qué es una idea fundamental?" — recall only (*forma tradicional*), no text,
does not exercise *Identifica las ideas fundamentales en textos no literarios*.

---

## Common Pitfalls

1. **Copying test items**: generate original tasks only.
2. **Ungrounded facts in explanations**: stay within the evidencia.
3. **Key length cue**: the longest option should not systematically be correct.
4. **English or Mexican/Spain Spanish idioms**: use es-CR register.
5. **Student data in prompts**: prompts contain curriculum data only.

---

## Invocation

```markdown
"Apply the mep-question-design skill from .ace/skills/mep-question-design/SKILL.md
to write a 4-option item for slot 2 of coverage plan CP-20261021-0001."
```
