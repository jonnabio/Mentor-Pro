# ADR-037: Quiz-Size Capacity and Plan Extension

> **Status:** Proposed (T069, PO-T069-2026-11-16). Nothing here is implemented
> until the PO approves it. Amends [ADR-034](ADR-034-question-bank-foundation.md)
> (the fixed 100-cell plan) if accepted.
> **Date:** 2026-11-16

---

## Context

Each subject's seeding batch has a fixed plan of 100 cells:
`allocate(all objectives, 100, "mixed")`. Each cell is one objective,
evidencia and difficulty, and holds one question. The seeder only fills
planned cells, so the plan caps what generation can supply. Questions from
practice generation can also be eligible, so in a few cells production holds
more eligible questions than the plan has (Matemáticas M01, M02, M09, M16;
Estudios Sociales ES11, ES12).

A practice of size N needs:

- per objective, exactly the questions `allocate` assigns (no swapping, D2);
- per level, the composer's share: within ±1 of a third for mixed, or all N
  for an explicit level;
- distinct questions with no near duplicates.

`app/practice/capacity.py` (T069) checks the first two exactly, as a small
flow problem. It reports the fewest extra questions or cells that would make a
size feasible. A test confirms that it agrees with the real composer whenever
there are no near duplicates.

## Findings

Curriculum shape, `PNE2026-SUM-v1.0`:

| Subject | Objectives | Evidencias | Plan cells per objective |
| --- | --- | --- | --- |
| Español | 8 | 5 to 9 | 12 to 13 |
| Matemáticas | 22 | 2 to 15 | 4 to 5 |
| Ciencias | 19 | 2 to 11 | 5 to 6 |
| Estudios Sociales | 29 | 1 to 3 | 3 to 4 |

### 1. Whole subject, mixed difficulty (the main student choice)

The 100-cell plan holds every size from 5 to 30 in all four subjects. Each
objective needs at most 2 questions at size 30 (4 in Español) and has at least
3 cells. **No structural limit.** Today's gaps are temporary inventory
shortfalls; see the T069 result.

### 2. Whole subject, one explicit level

| Subject | Easy 25 / 30 | Medium 25 / 30 | Hard 25 / 30 |
| --- | --- | --- | --- |
| Español | 0 / 0 | 0 / 0 | 0 / 0 |
| Matemáticas | 1 / 2 | 1 / 3 | 1 / 3 |
| Ciencias | 0 / 2 | 0 / 2 | 1 / 2 |
| Estudios Sociales | 0 / 0 | 0 / 1 | 0 / 1 |

These are the minimum extra plan cells for each choice. Sizes 5 to 20 fit
everywhere. Covering every level at size 30 needs **8 extra cells in
Matemáticas, 6 in Ciencias, 2 in Estudios Sociales and none in Español**:
16 in total.

### 3. Single objective (and small selections)

The plan holds 3 to 13 cells per objective. As planned today, a
single-objective practice reaches at most:

| Subject | Mixed | Explicit level |
| --- | --- | --- |
| Español | 10 | 0 to 5 |
| Matemáticas | 0 to 5 | 0 |
| Ciencias | 5 | 0 |
| Estudios Sociales | 0 | 0 |

"0" means size 5 cannot come from the bank. It is still offered: a size-5
shortage generates the whole practice (T059, RCA-006).

Size 30 on every objective, mixed, needs a plan of 240 (Español), 660, 570 and
870 cells. With every explicit level as well it needs 720 to 2,610. Size 10
alone needs 190 to 290 cells in the three larger subjects.

### Re-planning is the wrong tool

Raising `target` re-runs `allocate` and redistributes every cell, so the
numbers are much worse than the true minimum:

| Goal | Re-plan to target | Cells appended to the current plan |
| --- | --- | --- |
| Whole-subject levels to 30 | Matemáticas 118, Ciencias 106, Estudios Sociales 146 | 8, 6, 2 |

A new plan would also renumber cells. Every active link and pending question
would point at a different cell.

## Decision (proposed)

1. **Keep the 100-cell plan.** It structurally supports whole-subject mixed
   practices of 5 to 30 in every subject. The gaps there are generation and
   review, not capacity.
2. **Optionally, approve 16 extension cells** for whole-subject explicit-level
   practices of size 25 and 30:
   - Matemáticas: 8;
   - Ciencias: 6;
   - Estudios Sociales: 2.

   They are appended to each current batch's plan as cells 101 onward.
   Their objective and level are chosen exactly by `capacity.shortfall`.
   Existing cells, links and verdicts stay unchanged.
3. **Do not expand for single-objective sizes above the plan.** The cost is
   hundreds of cells per subject. The student is never misled today: the UI
   offers only sizes the composer builds (T063), and size 5 falls back to
   generation. If the PO wants larger single-objective practices, it should be
   a separate decision with its own budget.

## Consequences

- **Coverage:**
  - Option 2 adds depth on 2 to 8 objective-level pairs per subject. It does
    not add objectives or evidencias.
  - The curriculum allocation (D2) and level balance (D3) are unchanged.
- **Generation cost and quota:**
  - Production yield over 30 days was 5.3 to 8.2 free-model calls per accepted
    question.
  - About 37% of reviewed candidates were quarantined (15 of 41 verdicts).
  - 16 extension cells therefore cost about 16 / 0.63 × 7 ≈ 180 free calls,
    about 2.3 days of the scheduler's 80 calls per day. Paid spend stays zero.
  - It also adds about 25 candidates for the tutor to review.
- **Order of work:**
  - The scheduler's priority (T067) already puts the smallest unavailable
    mixed size first.
  - Extension cells would rank after every mixed size of their subject, so
    they never delay the main choice.
- **Migration:**
  - `bank_batch.plan` is JSON per batch. Appending cells needs no schema
    change.
  - The append is recorded with the PO authorization.
  - `target` becomes the plan length (100 plus extensions); `build_plan` stays
    for new batches.
  - Reports that assume `target` = 100 read the plan length instead.
- **Backward compatibility:**
  - Cells 1 to 100, their links, review samples, verdicts and the batch review
    gate are untouched.
  - Rolling back means deactivating the extension cells. Their questions stay
    stored and their verdicts stay recorded.

## Conservative implementation (after PO approval only)

1. Add a `seeding.extend_plan(batch_id, cells, authorization)` that:
   - appends cells;
   - refuses any cell already planned;
   - refuses to run while the subject's seeding lock is held.
2. Add a `replenish capacity --propose` command that prints the exact cells
   from `capacity.shortfall` (read-only), for the PO to approve.
3. Apply it to one subject first (Estudios Sociales, 2 cells), then check
   production with `replenish capacity` and the tutor coverage view.
4. Follow with Ciencias and Matemáticas.
5. Every candidate stays held until the tutor approves it (ADR-034).

## Alternatives considered

- **Raise `target` for every subject.** Rejected: it renumbers every cell and
  costs 6 to 46 more cells than appending.
- **Let explicit-level practices borrow other levels.** Rejected: an explicit
  level is never substituted (D3).
- **Offer sizes the bank cannot build and generate the rest.** Rejected:
  RCA-006 and T063 require that an offered size starts complete.
