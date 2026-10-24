# Task T021 Result: First AI-Generated Writing Exercise

> **Date:** 2026-10-24
> **Status:** Done
> **Decision:** [ADR-020](../adr/ADR-020-writing-exercise-generation.md)

---

## Implementation

| Area | Change |
|------|--------|
| `app/writing/generation.py` | Request check against the level map; grounding from the catalog (`list_rubric_criteria`) joined with the official rubric; prompts modelled on the MEP test; model writes student text only; checks W01–W08; up to 3 requests through `route()` with one `BudgetGate` |
| `app/writing/store.py` | `writing.generation_attempt` (one row per request: status, models, calls, tokens, provider cost, prompt version, checks, review, reasons); `writing.exercise.generation_request_id`; `topics()` |
| `scripts/dev/generate_writing_exercise.py` | Live generation with the real catalog, writing store and usage store |
| `tests/app/test_writing_generation.py` | 19 tests with scripted models |

Unchanged: EE criteria and descriptors, the multiple-choice engine, budgets,
paid fallback (off), student interface. No evaluation of student writing.

---

## Acceptance Run (live, free models)

Request: level L2 (Desarrollo de ideas), Intermedia, EE03 and EE04, one
introduction paragraph.

| Request | Model | Result |
|---------|-------|--------|
| `wreq-c010dffa7d0543bc` | nvidia/nemotron-3-ultra-550b-a55b:free | Rejected: W05, one sentence over 30 words |
| `wreq-cc140084442549c2` | nvidia/nemotron-3-ultra-550b-a55b:free | Rejected: W05, one sentence over 30 words |
| `wreq-fc80d41e7b804dca` | nemotron-3-ultra (generation), nemotron-3.5-super-vl (review) | Accepted: W01–W08 pass; review 2/2 on all five dimensions |

Totals: 4 OpenRouter calls (3 generation, 1 review), 3 558 input and 5 337
output tokens, provider-reported cost USD 0 (complete), 109 s.

### Generated exercise (`PE-L2-alimentacion-saludable-rendimiento-19a72a`)

- **Tema:** La alimentación saludable y el rendimiento escolar
- **Situación comunicativa:** Vos formás parte del comité de salud de tu
  escuela y debés redactar la introducción de un folleto que se entregará en
  la feria de la salud escolar. El folleto va dirigido a estudiantes,
  docentes y familias para informar y explicar por qué una buena
  alimentación ayuda a aprender mejor y convivir sanamente.
- **Ideas sugeridas:** beneficios de una alimentación balanceada para la
  concentración y la memoria; consecuencias de saltarse comidas o comer
  mucha comida chatarra; acciones sencillas que podés hacer en la escuela y
  en casa para comer mejor; el papel de la familia y la escuela para
  promover hábitos alimentarios saludables.
- **Instrucciones:**
  1. Leé la situación comunicativa y el tema.
  2. Pensá una idea principal que presente el tema.
  3. Agregá al menos dos ideas complementarias relacionadas con la
     situación.
  4. Escribí un solo párrafo de introducción con una idea principal que
     presente el tema y al menos dos ideas complementarias relacionadas con
     la situación comunicativa.
  5. Revisá que el párrafo sea coherente y use conectores.
- **Producto esperado:** un solo párrafo de introducción con una idea
  principal y al menos dos ideas complementarias (typed; 1 paragraph).
- **Criterios:** EE03 and EE04, `MEP-RUBRICA-PE-2026#EE03` and `#EE04`,
  scored 0–4 by a human; assertions `PNE2026-PRI-ESP-PE-B2-A3`,
  `PNE2026-PRI-ESP-PE-B3-A4`; sources: rubric, MEP model test, guide.

### Validation

- Contract: `validate_exercise` passes on the stored record; the rubric is
  referenced by ID and checksum, no descriptor text is copied or changed.
- Deterministic checks W01–W07 pass; review W08 all 2.
- Manual review for sixth grade: clear, complete and in Costa Rican voseo;
  the situation states who writes, for whom and why. Weaknesses:
  instruction 4 repeats instructions 2 and 3 and is the longest (about 30
  words); two suggested ideas (consequences, actions) belong to development
  or conclusion paragraphs, which may lead a student beyond the
  introduction.

---

## Verification

- Suite 427 passed (408 + 19); browser 259/259; `VERIFY_RESULT=pass gate=all`.
- Student database: one exercise and three generation attempts in
  `writing.*`; four usage rows in `llm.usage_record`; practice data
  unchanged (381 answers).

---

## Limitations

- W04 is keyword-based; the free-model review (W08) is the second check
  and inherits free-model quality.
- Redundancy between instructions and the scope of suggested ideas are not
  checked.
- L1 generates `conventions_production` only; `conventions_editing` (a
  text to correct) is not generated yet.
- Only one exercise was generated live (L2); L1 and L3–L5 are covered by
  tests with scripted models only.
- The 30-word sentence limit rejected two of three drafts; it is strict by
  design but costs requests.
- The suite now takes about 200 s (see T020 observation).
