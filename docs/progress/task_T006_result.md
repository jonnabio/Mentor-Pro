# Task T006 Result: First Curriculum-Grounded Question

> **Date:** 2026-10-22 (completed 2026-10-23 00:03 UTC)
> **Status:** Done — all four subjects validated
> **Decision:** [ADR-010](../adr/ADR-010-single-question-generation.md)

---

## Summary

The pipeline generates one question per request from baseline
`PNE2026-SUM-v1.0` through OpenRouter, validates it (deterministic checker,
blind solve, rubric) and records objective, evidencia, models, tokens, cost
and verdict. Under checker 1.4.0 and prompt 1.2.0, M02, C01, EL01 and ES01
each produced an accepted question. Total API cost: **$0.00**.

---

## Product Owner Decisions Applied

| Decision | Change |
|----------|--------|
| Daily request budget 1000 (local) | `.env` `OPENROUTER_MAX_REQUESTS_PER_DAY=1000`; account is not free tier (1000 free requests/day); paid models stay disabled (`ALLOW_PAID=false`, `MAX_USD_PER_DAY=0`) |
| C09 rejects a material length cue | Checker 1.4.0: fail (`regenerate`) when the key is ≥ 1.5× **and** ≥ 12 characters longer than the longest distractor |
| Record every rejection reason | `validation.attempts` keeps each attempt's verdict and reasons (previously only the last attempt) |

The C09 heuristic compares the key with the *longest* distractor, so a key
that is merely longer than some options passes. The 12-character gap stops
short options failing on ratio alone (`1,405 m` vs `1,5 m`; `12,5 kg` vs
`3 kg`). Prompt 1.2.0 tells the generator to keep options similar in length.

---

## Live Environment

| Item | Value |
|------|-------|
| Pinned free models | `nvidia/nemotron-3-ultra-550b-a55b:free`, `minimax/minimax-m3.1-flash:free`, `nvidia/nemotron-3.5-super-vl:free` |
| Unavailable to this account | Gemma 4 (429 upstream), Nemotron 3 Super (404), Inkling (403) |
| Calls, earlier runs (checker ≤ 1.3.0) | 52 (36 ok, 9 rate-limited, 4 errors, 1 truncated, 2 budget-blocked), $0.00 |
| Calls, final runs (checker 1.4.0) | 30 sent (29 ok, 1 truncated) + 2 budget-blocked before the budget change |
| Tokens, final runs | 19 747 in / 48 032 out |
| **Actual API cost** | **$0.00** — every call `provider_reported`, none missing |

---

## Final Results

| Objective / evidencia | Status | Validation evidence | Generator → solver/reviewer |
|-----------------------|--------|---------------------|-----------------------------|
| **M02** E3 *Compara decimales* (medium) | **Accepted** | All checks pass; M03 `select: max` proves 25/2 = B only; rubric all 2 | Nemotron 3 Ultra → Nemotron 3.5 Super VL (rubric) |
| **C01** E1 *partes de la célula* (easy) | **Accepted** | All checks pass; F01/F02 terms grounded; blind solve A = key; rubric all 2 | Nemotron 3 Ultra → Nemotron 3.5 Super VL |
| **EL01** E8 *idea fundamental* (medium) | **Accepted** | All checks pass incl. R01–R03 (86-word passage); blind solve A = key; rubric all 2 | Nemotron 3 Ultra → Nemotron 3.5 Super VL |
| **ES01** E2 *importancia para la convivencia* (medium) | **Accepted** | All checks pass; F01/F02; blind solve B = key; rubric all 2 | Nemotron 3 Ultra → Nemotron 3.5 Super VL |

Each accepted item has valid objective/evidencia references (G01, G02), four
distinct options (C02, C04), exactly one key (C03), an explanation and a
rationale per distractor (C06) and no material length cue (C09).

### Revalidation of earlier items under C09

| Item | Key / longest distractor (chars) | C09 1.4.0 |
|------|----------------------------------|-----------|
| EL01 `req-484cadcb` | 202 / 83 (2.4×) | **Fail** — replaced by the new EL01 (balanced, 99–108 chars) |
| ES01 `req-0b2aad40` | 161 / 111 (1.45×) | Pass (borderline); superseded by the new ES01 |

### All final-run requests

| Request | Objective | Calls | Outcome | Reason |
|---------|-----------|-------|---------|--------|
| `req-5d8bab43` | M02 | 0 | unavailable | daily budget (50) reached |
| `req-10ca1b74` | C01 | 0 | unavailable | daily budget (50) reached |
| `req-9004c7b5` | M02 | 2 | rejected (regenerate) | M02 two options equal value |
| `req-29316ad5` | C01 | 4 | **accepted** | 1st attempt rejected (reason not retained — fixed since) |
| `req-5075b12a` | EL01 | 3 | **accepted** | — |
| `req-4d32e222` | ES01 | 4 | **accepted** | 1st attempt rejected (reason not retained — fixed since) |
| `req-9e723546` | M02 | 5 | rejected (revise) | rubric `language` = 1 |
| `req-6eaee573` | M02 | 2 | rejected (regenerate) | M02 option A missing unit `m` |
| `req-be2a64fc` | M02 | 3 | rejected (revise) | rubric `difficulty_match` = 1 |
| `req-8b426d9a` | M02 | 3 | rejected (revise) | rubric `difficulty_match` = 1 |
| `req-f0f4ae38` | M02 | 2 | unavailable | fallback truncated at 4000 tokens |
| `req-e19a3e0d` | M02 | 2 | **accepted** | — |

M02 took 7 requests (22 calls); rejections were genuine, not bypassed.

---

## Accepted Examples

### M02 — Matemáticas

```text
En la feria de la escuela, cuatro grupos midieron la longitud de sus cintas
decorativas en metros y obtuvieron los siguientes resultados:
¿Cuál de las siguientes longitudes es la mayor?
A) 12,35   B) 12,5   C) 12,3   D) 12,05      <- clave B
```

Independent verification: all integer parts are 12; tenths are 3, 5, 3, 0,
so 12,5 is the maximum and is unique. The checker proves the same with exact
fractions (`select: max` → 25/2, only B matches); no model proof is trusted.
**Quality note:** the stimulus says "los siguientes resultados" and mentions
metres, but the values appear only as options without units. Correct, but
awkward wording the rubric did not catch.

### C01 — Ciencias

```text
En la clase de ciencias, la maestra muestra una lámina de una célula animal.
¿Cuál es la función principal de la membrana celular?
A) Controlar el intercambio de sustancias y proteger la célula.   <- clave
B) Almacenar la información genética en el núcleo.
C) Servir de medio donde ocurren las reacciones químicas.
D) Transmitir impulsos nerviosos a través del cuerpo.
```

Support terms `membrana`, `intercambio`, `protección` are in the approved
detailed content (F01) and used by key and explanation (F02); blind solver
chose A.

### EL01 — Español

An 86-word passage on a school recycling campaign. Key A ("…recolectó 120
kilogramos de reciclables y enseñó a cuidar el ambiente") is supported by
verbatim passage spans (R03); the three distractors are true details. Option
lengths 99–108 characters, so there is no length cue. Blind solver chose A.

### ES01 — Estudios Sociales

Feria comunitaria scenario; key B ("Porque fomentan el diálogo, el respeto
por diversidad y la solución pacífica de conflictos para alcanzar el bien
común"). Blind solver chose B. The key is the longest option (119 vs 88
characters, 1.35× the longest distractor), below the C09 threshold.

---

## Defects Found Live and Fixed

| # | Defect | Fix |
|---|--------|-----|
| 1 | Auto-selection picked audio models (Lyria) | Only text-in/text-only-out models are candidates |
| 2 | Any 403 aborted all routing | 401 stops; 403 skips that model |
| 3 | Reasoning models truncated before answering | `finish_reason=length` → `invalid_output`; higher token limits |
| 4 | Rubric/solve parsing failed on leaked reasoning | Last JSON object with rubric keys; letter on final line |
| 5 | Model injected keys into `subject_checks` | Only known blocks and keys kept |
| 6 | Expression `148/100` "proved" the key | M04: operands must come from item text (or 2–10, 100, 1000); otherwise blind solve required |
| 7 | Only the last attempt's reasons were stored | `validation.attempts` records every attempt |

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 254 passed (C09: 2 obvious-cue and 5 acceptable-variation cases; attempt history) |
| ACE gate | `VERIFY_RESULT=pass gate=all` |
| Fixture change | Reading test fixture had a 1.55× length-cued key; distractors lengthened |
| Key exposure | `.env` git-ignored; key absent from tracked files and HTTP responses; `student_view` has no key/explanation |

---

## Open Items

1. Rubric scores come from one free model; add human spot checks
   (`question-evaluation`). It missed the M02 stimulus wording.
2. Social-studies keys tend to be the longest option even below the C09
   threshold; watch this in the evaluation set.
3. M02 acceptance rate was 1 in 7 requests; prompt tuning for maths is a
   candidate for the next task.
