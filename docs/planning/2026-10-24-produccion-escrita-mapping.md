# Producción Escrita: Criteria Mapping (T020)

> **Date:** 2026-10-24
> **Decision:** [ADR-019](../adr/ADR-019-produccion-escrita-foundation.md)
> **Data:** `curriculum/writing/MEP-RUBRICA-PE-2026.json`,
> `curriculum/writing/exercise-levels.json`

---

## Sources

| Source | Use | SHA-256 (first 12) |
|--------|-----|--------------------|
| Rúbrica MEP 2026, primaria (`MEP-RUBRICA-PE-2026`) | Criteria, 0–4 descriptors, weights, counting note | `460a931a4e2c` |
| Prueba de Producción Textual, primaria 2026 (model) | Full-composition task model: topic, situation, suggested ideas, 4 paragraphs, 90 minutes, pen | `7e657f24295b` |
| Guía de preparación, producción escrita 2026 | Topic and situation models (5 weekly exercises) | `2b42d432a0ec` |
| Baseline `PNE2026-SUM-v1.0` | EE01–EE20 records (`written_rubric`), assertion IDs | — |

The descriptors were transcribed verbatim from the PDF and checked against
page images. Two source oddities are kept as written: EE13's 4-point
descriptor reads "rrr", and EE17's 1-point descriptor reads "al inicio y
final". The rubric's EE05 statement reads "…dos párrafos de desarrollo y
cada uno…", while the baseline record reads "…de desarrollo, cada uno…".
Both are kept unchanged and the test pins this as the only difference.

---

## Levels

| Level | Code | Exercise types | Deliverable | Core criteria |
|-------|------|----------------|-------------|---------------|
| L1 Convenciones de escritura | `writing_conventions` | `conventions_editing`, `conventions_production` | 3–8 sentences | One or more of EE07–EE18 |
| L2 Desarrollo de ideas | `idea_development` | `introduction_paragraph` | 1 paragraph | EE03, EE04 |
| L3 Redacción de párrafos | `paragraph_writing` | `development_paragraphs` (2 paragraphs), `conclusion_paragraph` (1) | 1–2 paragraphs | EE03 + EE05 or EE06 |
| L4 Composición guiada | `guided_composition` | `guided_composition` | 4 paragraphs, 200 words, scaffolded, untimed | EE01–EE06 |
| L5 Composición expositiva completa | `full_composition` | `full_composition` | 4 paragraphs, 200 words, 90 minutes, pen | EE01–EE20 |

Levels L2–L4 may add convention criteria (EE07–EE18). A level never scores
part of a criterion: each criterion it targets is scored with the full
official descriptors, which is why EE01 and EE02 (whole-text length and
structure) appear only from L4.

---

## Criteria

All 20 criteria are mapped; every criterion is core in at least one level.

| Code | Dimension (weight) | Criterion (rubric wording) | Core in | Allowed in | Evidence | PDF page |
|------|--------------------|----------------------------|---------|------------|----------|----------|
| EE01 | D1 (20 %) | Redacta un texto con una extensión de 200 palabras. | L4, L5 | L4, L5 | Typed or handwritten | 2 |
| EE02 | D1 (20 %) | Construye un texto estructurado a partir de párrafos de introducción, desarrollo y conclusión. | L4, L5 | L4, L5 | Typed or handwritten | 2 |
| EE03 | D2 (20 %) | Desarrolla el mensaje expositivo con unidad temática (coherencia) a partir de la situación comunicativa. | L2, L3, L4, L5 | L2, L3, L4, L5 | Typed or handwritten | 3 |
| EE04 | D3 (40 %) | Redacta el párrafo de introducción con cohesión entre la idea principal y, al menos, dos ideas complementarias, en relación con el tema y la situación comunicativa. | L2, L4, L5 | L2, L4, L5 | Typed or handwritten | 4 |
| EE05 | D3 (40 %) | Redacta con cohesión dos párrafos de desarrollo y cada uno con su idea principal y al menos dos ideas complementarias, en relación con las causas y consecuencias derivadas del tema y la situación comunicativa. | L3, L4, L5 | L3, L4, L5 | Typed or handwritten | 5, 6 |
| EE06 | D3 (40 %) | Redacta el párrafo de conclusión que evidencie cohesión entre la idea principal y, al menos, dos ideas complementarias, en relación con las acciones o soluciones derivadas de la situación comunicativa. | L3, L4, L5 | L3, L4, L5 | Typed or handwritten | 6, 7 |
| EE07 | D4 (15 %) | Emplea la concordancia gramatical entre el artículo, el sustantivo y el adjetivo, conforme a la normativa en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 7 |
| EE08 | D4 (15 %) | Emplea la concordancia gramatical entre el verbo y el sujeto, conforme a la normativa en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 7 |
| EE09 | D4 (15 %) | Emplea los usos normativos de las letras b-v en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 8 |
| EE10 | D4 (15 %) | Emplea los usos normativos de las letras s-c-z en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 8 |
| EE11 | D4 (15 %) | Emplea el uso normativo de la letra h en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 8 |
| EE12 | D4 (15 %) | Emplea los usos normativos de las letras g-j en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 8 |
| EE13 | D4 (15 %) | Emplea los usos normativos de la r-rr en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 8 |
| EE14 | D4 (15 %) | Emplea los usos normativos de las letras m-n en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 9 |
| EE15 | D4 (15 %) | Emplea las reglas de acentuación de las palabras agudas, graves, esdrújulas y sobreesdrújulas en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 9 |
| EE16 | D4 (15 %) | Emplea el punto y seguido y el punto y aparte, según la normativa en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 9 |
| EE17 | D4 (15 %) | Emplea la coma en enumeraciones y los signos de interrogación y exclamación (al inicio y al final de los enunciados), conforme a la normativa en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 10 |
| EE18 | D4 (15 %) | Emplea el uso normativo de la mayúscula al inicio de las oraciones y en los sustantivos propios en el texto. | L5 | L1, L2, L3, L4, L5 | Typed or handwritten | 10 |
| EE19 | D5 (5 %) | Redacta el texto con trazo legible de las letras. | L5 | L4, L5 | Handwritten only | 10 |
| EE20 | D5 (5 %) | Redacta el texto con letras de un mismo tipo (imprenta o cursiva) conforme a la normativa. | L5 | L4, L5 | Handwritten only | 11 |

---

## Handwritten Evidence

EE19 (trazo legible) and EE20 (letras de un mismo tipo) judge handwriting.
They are scored only from the handwritten sheet or an image of it. A typed
submission records them as `not_evaluable` with reason
`handwritten_evidence_required`: they are neither 0 nor omitted, and progress
reports them as without evidence. Typed text can also hide convention errors
if the input corrects spelling automatically; the future writing screen must
turn autocorrection off (see ADR-019, Risks).

---

## Scoring Parameters

- Scale 0–4 per criterion; a score is the index of the matching official
  descriptor (`contracts.descriptor(code, points)`).
- EE07–EE18 descriptors count non-normative uses: 0 uses = 4 points, 1 = 3,
  2 = 2, 3 = 1, 4 or more = 0. When recorded, `non_normative_uses` must
  agree with the points. The rubric note applies: an identical repeated use
  counts once (`counting_rule: identical_repetition_counts_once`).
- Dimension weights (20/20/40/15/5 %) are kept for reference. Progress
  reports per-dimension averages with coverage; it computes no weighted
  grade.
