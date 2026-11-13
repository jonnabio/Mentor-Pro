# T065 Result: Generation Quality (Difficulty and Grounding)

- **Role:** Developer (PO authorization PO-QUESTION-BANK-COMPLETION-2026-11-11)
- **Status:** done, verified in production (release `v2026.11.12-1`)

## Root Causes (production records, 2026-11-11)

22 attempts from 80 calls: 8 accepted, 10 rejected by checks, 4 cut by
the per-run call limit. No provider failure, duplicate or
independent-solve disagreement.

- **Difficulty (6 attempts, 35 calls): generator failure, rubric
  correct.** 7 of the 8 difficulty failures in the history were `hard`
  requests answered with one-step recognition items (expanded notation
  to a number, "how is the text organized?" for a text marked "Primero…
  Luego…", a definition). The one-line rule "Difícil: razonamiento de
  varios pasos" did not stop this.
- **Grounding (all 10 historical F01/F02 failures, classified):**

| Term | Curriculum text | Class |
| --- | --- | --- |
| tejido muscular (5), tejido epitelial | "tejidos muscular, nervioso, epitelial y sanguíneo" | over-restrictive check |
| inmunidad adquirida | "Inmunidad innata y adquirida" | over-restrictive check |
| hemisferio occidental | "hemisferio norte/occidental" | over-restrictive check |
| sistema circulatorio, contracción, istmo centroamericano | absent | genuine unsupported content |
| participación (F02) | listed, not used in key | model output issue |

  Two attempts mix an over-restricted term with a genuine one and stay
  rejected.

## Change

- `item_checker.py` 1.7.0: `coordinated_phrases` lets F01 read a
  coordinated or slash list of single-word modifiers in the curriculum
  ("tejidos muscular, nervioso y epitelial" grounds "tejido muscular").
  Only head + one listed word is added; anything the curriculum does not
  state still fails. F02 unchanged.
- `prompts.py` generation 1.4.0: `SUBJECT_DIFFICULTY`, explicit easy,
  medium and hard criteria per subject, each `hard` stating what is NOT
  hard; difficulty through the situation, not vocabulary; a self-check.
  `GROUNDING_RULE` for Ciencias and Estudios Sociales: copy support terms
  from the curriculum and use each one.
- **Unchanged:** rubric prompt 1.1.0 and `DIFFICULTY_RULES` (the
  independent judge), verdict thresholds, independent solve, duplicate
  checks, daily limits, paid settings. No relabelling.

## Evidence

### Grounding: offline replay (reproducible, no LLM)

`scripts/dev/replay_grounding.py` on every recorded Ciencias and Estudios
Sociales attempt with a facts item (production export, 42 items):

| Checker | Grounding pass | F01 | F02 |
| --- | --- | --- | --- |
| 1.6.0 (before) | 32/42 | 9 | 1 |
| 1.7.0 (after) | 38/42 | 3 | 1 |

The 4 remaining failures are exactly the genuine ones above.

### Difficulty: live benchmark (same cells, both arms)

`scripts/dev/benchmark_generation_quality.py`: the six production-failing
cells (M03, M02, EL01, C01, ES01 hard; ES01 easy), each through the full
pipeline once with the 1.3.0 generator (`origin/main`) and once with
1.4.0; same validator, rubric and free models as production
(`nemotron-3-ultra`, `gemma-4-26b` fallback), paid off, in-memory usage.

| Replicate | Arm | Accepted | Calls | Calls/accepted | Difficulty pass | Grounding fails |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.3.0 | 1/6 | 26 | 26.0 | 1/8 | 1 |
| 1 | 1.4.0 | 4/6 | 28 | 7.0 | 4/8 | 0 |
| 2 | 1.3.0 | 1/6 | 22 | 22.0 | 1/6 | 1 |
| 2 | 1.4.0 | 3/6 | 26 | 8.7 | 3/6 | 1 |
| **Both** | **1.3.0** | **2/12** | **48** | **24.0** | **2/14** | **2** |
| **Both** | **1.4.0** | **7/12** | **54** | **7.7** | **7/14** | **1** |

Accepted per call: 0.042 before, 0.130 after (about 3x). Remaining
1.4.0 losses: near-identical options on hard Ciencias and Estudios
Sociales (C04, 3 attempts; long parallel options, a correct rejection),
difficulty (3), a unit missing from options (L02, 1), F02 (1). 12 cells
per arm: the result shows a clear direction, not a precise rate.

## Tests

- `tests/ace/test_item_checker.py`: coordinated terms grounded (6 cases),
  unstated terms still fail (5 cases), expansion adds only listed
  modifiers.
- `tests/app/test_generation.py`: criteria for every subject and level;
  the generation prompt states the subject's criteria and the grounding
  rule only where facts apply; the rubric prompt is unchanged.
- Full ACE gate: `VERIFY_RESULT=pass gate=all`.

## Inventory Gaps for Larger Sizes (production, read-only, 2026-11-11)

Whole-subject mixed simulation, the composer's own allocation:

| Subject | Eligible | Size 5 | Size 10 missing |
| --- | --- | --- | --- |
| matematicas | 30 | composes | 3: M07, M12, M20 (one each) |
| espanol | 8 | 3 short | 6 objectives |
| ciencias | 5 | 4 short | 8 objectives |
| estudios_sociales | 14 | 3 short | 6 objectives |

Matemáticas 15/20/25/30 lack 7/10/13/18 questions. The pending M02/M03
candidates do not unlock size 10; targeted runs (`seed_bank run
--objective M07|M12|M20`) after release are the shortest path.

## Release and Production Verification (2026-11-12)

- Implementation PR #68 (head `8aada80`, CI 43161957071 green) merged into
  `dev` as `ecfc6ef`; `dev` CI 43235704859 green.
- Release PR #69 approved by the PO (PO-QBANK-FINAL-2026-11-12), merged
  with `--match-head-commit` as `4245869`; `main` CI 43249020382 green
  (Python Tests, Release Identity, Validate and Publish Docker Image, Tag
  and Release).
- Release `v2026.11.12-1`, digest `sha256:04e01d50…f3e8`; manifest sha256
  `cec91911…16b3` identical on the server.
- Deploy 2026-11-12T15:44:39Z: `PREFLIGHT OK` (no migration), backup
  `mentor_pro_2026-11-12_154415.dump` (sha256 `cec2a5ee…eb7b`) `VERIFY
  OK`, `DEPLOY OK`, smoke 13/13, `STATUS HEALTHY`; window
  `T065-RELEASE-2026-11-12`. Running container: generation prompt 1.4.0,
  checker 1.7.0; paid generation off.

### Acceptance

Accepted candidates per call rise without weakening validation:

- Production targeted runs (M07, M12, M20; 12 calls each): 8 candidates
  from 36 calls (0.22 per call; 0.10 per call on 2026-11-11 with 1.3.0).
- Tutor review (QBANK-FINAL): 5 approved, 3 quarantined (an avoidable
  inconsistency in the context, a reflection beyond primary level, an
  artificial statistic whose key equals the mode). The checker passed all
  three; only the human review caught them, as designed.
- Matemáticas whole-subject mixed size 10 composes from the bank (10
  distinct questions, M01-M20, 4 easy, 3 medium, 3 hard) and the student
  availability API offers `[5, 10]`.
