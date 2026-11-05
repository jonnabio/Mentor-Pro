# Production Release Record: v2026.11.05-1 (T053)

- **Date:** 2026-11-05 (UTC)
- **Authorization:** `PO-T053-2026-11-05`, window `T053-2026-11-05`
- **Change:** T053, explicit question-generation model list (ADR-009
  amendment). No schema, `deploy/`, Dockerfile or requirements change.

## Release

- Release PR #51 (head `b931847`, CI 42056387499) merged into `main` as
  `27fd409`; `main` CI 42057883562 green, including Tag and Release.
- Tag `v2026.11.05-1` on `27fd409`; GitHub Release published.
- Digest `sha256:c1e6ba1a840934021b28f848570b45da83bba17951838780eee3cd6b186ae112`.
- Manifest sha256 `65f2610b055390ef0e86aa3389de5c86c606af76be4c894290dee81c277496a7`,
  identical locally and on the server; schema `0001..0001`.

## Pre-deployment

- Production `v2026.11.04-1` (`6a661861…c5d1`), `STATUS HEALTHY`, smoke
  9/9; `PREFLIGHT OK: DEPLOY COMPATIBLE`.
- Both generation models listed, free and text-chat compatible.
- Administrator: `app.env.bak-T053` created (607 bytes, root `0600`);
  `OPENROUTER_QUESTION_GENERATION_MODELS` count 0 → 1, value exactly
  `nvidia/nemotron-3-ultra-550b-a55b:free,google/gemma-4-26b-a4b-it:free`;
  `app.env` 715 bytes (607 plus the 108-byte line);
  `MENTOR_PRO_BANK_ONLY_ENABLED` count 0.

## Deployment

- Backup `mentor_pro_2026-11-05_185406.dump` (sha256
  `0a202cde…3d04`, 31 tables, 970 rows); `VERIFY OK`.
- `DEPLOY OK: v2026.11.05-1 running and healthy, smoke passed`.
- After: `STATUS HEALTHY`, schema current, smoke 9/9; app and tutor on
  `c1e6ba1a…e112`; `postgres:17.6` healthy.
- App container: the model list above is set; no
  `MENTOR_PRO_BANK_ONLY_ENABLED` key. `/api/subjects`:
  `practice: {bank_only: false, question_counts: [5]}`.
- Rollback target: `v2026.11.04-1` (`6a661861…c5d1`), same schema, with
  the backup above. Configuration undo: restore `app.env.bak-T053`.
