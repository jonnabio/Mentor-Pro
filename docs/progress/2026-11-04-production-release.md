# Production Release v2026.11.04-1 (T051)

- **Date:** 2026-11-04 (UTC; authorized 2026-11-03)
- **Role:** Architect
- **Authorization:** `PO-T051-2026-11-03`, window `T051-2026-11-03`
  (`authorization_verified=no`; a reference string does not prove the
  approval).
- **Operator:** the agent (`jonnabio`, `sudo -n` tool only).
- **Result:** `v2026.11.04-1` running in production, schema `current
  0001`, `STATUS HEALTHY`, bank-only practice **off**.

## Release identity

| Item | Value |
| --- | --- |
| Source | `dev` `3b99f02` (T051 #48, with the T050 records) plus handoff record `def1b02` (docs only) |
| Release PR | #49, head `def1b02`, CI 41750883618 green, merged with `--match-head-commit` |
| `main` commit | `6cc15dc`, CI 41751979521 green (Tag and Release included) |
| Tag | `v2026.11.04-1` (protected) → `6cc15dc` |
| Image | `ghcr.io/jonnabio/mentor-pro@sha256:6a661861f986576ccccd3f85a53ca323ab59a34dfdb9cac22b7721f16bcdc5d1` |
| Manifest | sha256 `fe357b8856599ccea3e367ff5c7d0c4e7dd1c52fe4bfae1d3950d736a6034fac`, same on GitHub and `/opt/mentor-pro/manifests/v2026.11.04-1.json`; schema `0001..0001` |

Code change since `v2026.11.02-1`: `app/practice/` only. No `deploy/`,
schema, Dockerfile or requirements change; the root-owned tool was not
reinstalled.

## Switch check

- Before: running containers (created from `/etc/mentor-pro/app.env` at
  the 2026-11-02 deploy) had no `MENTOR_PRO_BANK_ONLY_ENABLED` key (key
  names only); `/api/subjects` reported `bank_only: false`. The file is
  root-only and was not read; `/etc/mentor-pro` unchanged since
  2026-10-28.
- After: the recreated containers have no such key either, which confirms
  the file.

## Window (UTC)

| Step | Result |
| --- | --- |
| `status`, `smoke` | `STATUS HEALTHY` (`v2026.11.02-1`), `SMOKE PASS (9/9)` |
| `preflight` | `PREFLIGHT OK: DEPLOY COMPATIBLE`, schema `0001` |
| `backup` | `BACKUP OK` `mentor_pro_2026-11-04_011934.dump`, 31 tables, 945 rows, 223,161 bytes, sha256 `670447b8…2a78` |
| `verify-backup` | `VERIFY OK`; verify container, volume and network removed |
| `deploy` | 01:20:00 `DEPLOY OK: v2026.11.04-1 running and healthy, smoke passed`; previous `738af74e…547a` |
| `status`, `smoke` | `STATUS HEALTHY`, `SMOKE PASS (9/9)`; app and tutor on `6a661861…` |
| Bank-only | `/api/subjects` `bank_only: false`, sizes `[5]`; `source: bank_only` refused (422) |

Rollback target: `v2026.11.02-1` (`738af74e…547a`), same schema, with
`mentor_pro_2026-11-04_011934.dump`. Not used.
