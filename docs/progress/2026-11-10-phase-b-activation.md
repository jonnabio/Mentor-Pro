# Phase B Operational Activation (v2026.11.10-1)

- **Directive:** PO, operational completion only (no release, code change
  or PR). Record carried into the next functional PR.
- **Date:** 2026-11-10/11 (UTC 2026-11-11 01:00–01:45).
- **Release:** `v2026.11.10-1`, image `sha256:a07867c8…3aef`, deployed
  2026-11-10T22:31:41Z (window `PHASE-B-2026-11-10`, authorization
  `PO-PHASE-B-PROD-2026-11-09`, backup sha256 `5d6b6759…74ed6`,
  previous `0cede5a3…f5de9c`). `STATUS HEALTHY`, schema `current:0001`.

## 1. Configuration

- `MENTOR_PRO_BANK_ONLY_SUBJECTS` is present; the running app parses it
  as `{'matematicas': (5,)}` (checked with `bank_only_config(None)`
  inside `mentor-pro-app-1`, value not printed).
- The administrator change to `matematicas:5,10,15,20,25,30` is **not yet
  applied**. Pending: administrator edit, then reload through the
  standard sequence (preflight, backup, verify-backup, deploy of the same
  digest) and re-check `bank_only_config` and `/api/subjects`.

## 2. Inventory and Generation

Bounded free runs (`replenish run --max-calls 20`), all exit 0, stop
`run_call_limit`, requests left open (resumable):

| Subject | Calls | New candidates |
| --- | --- | --- |
| espanol | 20 | 0 |
| ciencias | 20 | 3 |
| estudios_sociales | 20 | 3 |
| matematicas | 20 | 2 |

Usage UTC 2026-11-11: 80 calls sent, 9 never sent, 0 paid, 0 USD (limit
200 requests). Yield is low (8 candidates from 80 calls).

Inventory after the runs (`replenish inventory`):

| Subject | Eligible | Pending review |
| --- | --- | --- |
| espanol | 8 | 0 |
| matematicas | 30 | 5 |
| ciencias | 5 | 3 |
| estudios_sociales | 14 | 3 |

Pending questions are not eligible inventory.

## 3. Tutor Review

- Files exported with `seed_bank item-review-sample`, kept private
  (mode 600) in `~/mentor-pro-review/PHASE-B-<subject>-2026-11-11.json`;
  container copies deleted.
- matematicas: M02 hard/easy/medium, M03 hard/easy; ciencias: C01
  hard/easy/medium; estudios_sociales: ES01 hard/easy, ES02 medium.
- No verdict recorded. Awaiting the tutor.

## 4. Quiz Sizes

`/api/subjects`: every subject offers `[5]`; matematicas `bank_only:
true`, others generation (five-question fallback preserved).

## 5. Tutor API

`/api/tutor/practice/bank` on `127.0.0.1:8081`: 403 without the token;
200 with it (token read from the tutor container environment into curl
on stdin, never printed). Response: 4 subjects, 227 pending and 1 closed
requests.

## 6. Reload Attempt After the Administrator Edit (2026-11-11)

- `preflight` on `/opt/mentor-pro/manifests/v2026.11.10-1.json`
  (sha256 `9aaa307c…29e8`): `DEPLOY COMPATIBLE`.
- `backup`: `mentor_pro_2026-11-11_035231.dump` (35 tables, 1622 rows,
  sha256 `c22243c8…7b3a`); `verify-backup`: `VERIFY OK`.
- `deploy` (window `PHASE-B-ACTIVATION-2026-11-11`, authorization
  `PO-PHASE-B-ACTIVATION-2026-11-11`): `UNCHANGED` (same digest running
  and healthy, by design no recreate). `STATUS HEALTHY`, smoke 13/13.
- The app still parses `{'matematicas': (5,)}`: the container (created
  2026-11-10T22:31Z) keeps the environment it started with. The agent
  cannot recreate it (`docker compose` must read root-only
  `/etc/mentor-pro/*.env`; passwordless sudo covers only `mentorpro`).
  Administrator action needed (see Outstanding).

### Administrator Recreate (2026-11-11)

- The administrator confirmed the line (`grep -c` = 1) and ran
  `docker compose … up -d --no-deps --force-recreate app` (app only;
  tutor and PostgreSQL untouched). Container created
  2026-11-11T12:56:09Z, same digest `a07867c8…3aef`.
- `STATUS HEALTHY`, smoke 13/13.
- Loaded: `{'matematicas': (5, 10, 15, 20, 25, 30)}`; `/api/subjects`
  matematicas `bank_only: true`, permitted `[5..30]`; other subjects
  `[5]`, generation.
- `POST /api/practice/availability` (read-only), matematicas subject
  simulation: mixed `[5]` (bank composes 5); easy, medium, hard `[5]`
  (bank composes none; size 5 generates). Ciencias `[5]`. No size above
  5 is offered: the inventory cannot compose 10 yet.

## 7. Low-Yield Diagnosis (records only, no new runs)

Window UTC 2026-11-11 (80 sent calls + 9 blocked by the run limit),
`llm.usage_record` and `generation.question_attempt`:

- 22 attempts: 8 accepted (27 calls), 10 rejected by checks, 4 cut by
  the 20-call run limit.
- Difficulty mismatch (review rubric `difficulty_match` 0 or 1): 6
  attempts, 35 calls; all 3 Español rejections and both Matemáticas
  rejections.
- Grounding F01/F02 (support terms absent from sources or key): 4
  attempts (Ciencias 3, Estudios Sociales 1).
- Truncation: 3 calls (Español generation 2 at 4,000 tokens, Ciencias
  solve 1 at 2,000).
- Provider failures (HTTP 429/5xx): 0. Duplicates: 0. Independent-solve
  disagreement: 0 (2 attempts lost the solve to the run limit).
- Cost per attempt: 3–6 calls (generation 38–59 s average, high
  reasoning-token use).

## Outstanding

- Administrator: done (edit and app recreate, 2026-11-11).
- Tutor: review 11 candidates; record only actual verdicts, then
  recount inventory and delete the review files.
- Rerun free generation on a later UTC day; Español produced nothing.
