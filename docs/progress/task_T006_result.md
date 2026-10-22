# Task T006 Result: First Curriculum-Grounded Question

> **Date:** 2026-10-22
> **Status:** Implemented; live validation partial (see Results)
> **Decision:** [ADR-010](../adr/ADR-010-single-question-generation.md)

---

## Summary

The pipeline generates one question per request from baseline
`PNE2026-SUM-v1.0` through OpenRouter, validates it (deterministic checker,
blind solve, rubric) and records objective, evidencia, models, tokens, cost
and verdict. Live runs exposed six defects, all fixed with regression tests.
Under the final rules, two live questions are valid (EL01, ES01); M02 and C01
are not yet validated.

---

## Live Environment

| Item | Value |
|------|-------|
| `.env` | Created, git-ignored; key added by the owner |
| Connectivity | 468 models listed, 21 free; Nemotron 3 Ultra, 26 in / 16 out tokens, $0, 852 ms |
| Pinned free models | `nvidia/nemotron-3-ultra-550b-a55b:free`, `minimax/minimax-m3.1-flash:free`, `nvidia/nemotron-3.5-super-vl:free` |
| Unavailable to this account | Gemma 4 (429 upstream), Nemotron 3 Super (404), Inkling (403) |
| Calls recorded | 52 (36 ok, 9 rate-limited, 4 errors, 1 truncated, 2 budget-blocked) |
| **Actual API cost** | **$0.00** — all provider-reported, none missing |
| Daily request budget | 50 reached; further calls blocked as designed |

---

## Results

| Objective / evidencia | Final status | Verdict basis | Generator → solver/reviewer |
|-----------------------|--------------|---------------|-----------------------------|
| **ES01** E2 (medium) | **Valid** | Checks pass; blind solve C = key; rubric 2/2/2/2/2 | Nemotron 3 Ultra → MiniMax M3.1 Flash |
| **EL01** E8 (medium) | **Valid, with warning** | Checks pass (C09 key-length warning); blind solve A = key; rubric all 2 | Nemotron 3 Ultra → MiniMax M3.1 Flash |
| **M02** E3 (medium) | **Not validated** | Accepted at checker 1.2.0, then withdrawn: proof `148/100` restated the key (M04 rule, 1.3.0); needs a blind solve | Nemotron 3 Ultra → MiniMax M3.1 Flash |
| **C01** E1 (easy) | **Rejected** | Earlier: F02 term not in key; missing `support_terms`; near-identical options. Last: checks passed but solve blocked by budget (`pending`) | Nemotron 3 Ultra |

Per-request usage (selected): ES01 4 calls, 2 507 / 3 498 tokens, 66 s;
EL01 4 calls, 2 634 / 5 499 tokens, 106 s; M02 (last) 3 calls,
2 309 / 3 960 tokens, 78 s. All $0.

### Valid example — ES01

Estudios Sociales, E2 *"Explica por qué son importantes para la convivencia"*:

```text
En la escuela, los estudiantes de sexto grado organizan una feria comunitaria
para decidir cómo mejorar el parque del barrio. Deben ponerse de acuerdo entre
diferentes opiniones y propuestas.

¿Por qué los Estudios Sociales y la Educación Cívica son importantes para la
convivencia en esta situación?

A) Porque enseñan a conocer la historia y la geografía del país, lo que ayuda a obtener buenas notas.
B) Porque permiten memorizar fechas y nombres de personajes importantes para los exámenes.
C) Porque fomentan la participación, el diálogo, el respeto por la diversidad y la solución pacífica de conflictos, lo que fortalece la convivencia y el bien común.   <- clave
D) Porque solo se centran en los derechos individuales sin considerar los deberes ni la participación democrática.
```

Generated with prompt 1.0.0, whose example terms came from ES01 concepts
(since replaced by placeholders). The key is also the longest option.

### Valid example — EL01

Español, E8 *"Elige la idea fundamental respaldada por el texto"*.

Passage on a school recycling campaign (88 words); key A summarises the
campaign. Blind solver chose A. **Quality concern:** option A is far longer
than the distractors (C09 warning), a cue students can exploit.

### Not validated — M02

Matemáticas, E3 *"Compara decimales"*:

```text
Alturas: 1,45 m; 1,5 m; 1,405 m; 1,48 m. ¿Cuál es la altura de la planta que
quedó en segundo lugar al ordenar las alturas de mayor a menor?
A) 1,45 m   B) 1,5 m   C) 1,405 m   D) 1,48 m   <- clave D
```

The key is correct, but the claimed proof did not compute it.

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

Prompt 1.1.0 shows the exact `subject_checks` shape with neutral placeholders.

---

## Tests and Gate

| Check | Result |
|-------|--------|
| Full suite | 246 passed, 0 skipped |
| ACE gate | `VERIFY_RESULT=pass gate=all` |
| Mutation check | Removing the solve-agreement rule fails its test |
| Key exposure | `.env` git-ignored; key absent from tracked files and all HTTP responses; `student_view` has no key/explanation |

---

## Open Items

1. Regenerate M02 and C01 when the daily budget resets (or raise
   `OPENROUTER_MAX_REQUESTS_PER_DAY`).
2. Decide whether C09 (key-length cue) should reject instead of warn.
3. Rubric scores come from a free model and approved a length-cued key; add
   human spot checks (`question-evaluation`).
