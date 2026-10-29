# T044 Result: Preflight, Compatibility, Deploy and Rollback (ADR-033 I4)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T044-deploy-rollback` (from `dev` at `0bcf64d`)
- **Status:** PO corrections applied and verified; PR #21 to `dev`
  (merge authorized once corrections pass). Nothing run on the server
  or production; nothing published.

## Thought

PR #20 (documentation only, head `0352f2f` unchanged) merged as
`0bcf64d`. The PO approved the I4 plan with decisions: manifest as a
local file, six-hour evidence, manual rollback only, window and PO
authorization references on every deploy and rollback.

## Action

- `deploy/mentorpro_deploy.py` (python3 standard library), called by
  `deploy/mentorpro preflight|deploy|rollback`:
  - manifest validation as `docs/release/manifest.schema.json` for a
    published release; dry-run, wrong repository, malformed or
    mismatched manifests refused;
  - registry: content at the digest hashes to the digest; the version
    tag maps to exactly that digest (anonymous bearer token when asked);
    pull by digest; `RepoDigests` must contain it; labels must equal the
    manifest (version, revision, created, schema range); never a tag;
  - live schema read-only with `psql` in the PostgreSQL container:
    `fresh`, `legacy` (schema `none`), `current` (`0001`), `drifted`,
    `corrupt` (empty or unknown ledger, ledger without tables) and
    `unreadable`; only the first three pass;
  - compatibility `min <= live <= max`; label-less images `none..none`;
  - preflight record per digest (digest, manifest file checksum, live
    state, time); backup evidence from `<dump>.verify` (database,
    archive checksum recomputed, schema state, newest successful
    verification, no later failure); both at most six hours old;
  - `deploy`/`rollback`: references required, lock (`flock`),
    live schema re-read and compatibility rechecked inside the lock,
    `UNCHANGED` only when the target runs, is healthy and passes smoke;
    atomic `release.env` with `release.env.previous` and a history copy;
    `compose up -d --no-deps app tutor`; health wait; smoke; failure
    prints a proposed rollback, never runs it;
  - `rollback`: previous configuration or `--to <version>` (stored
    manifest); incompatible targets refused before anything changes,
    with the database-restore pointer (G3);
  - append-only `RELEASES` lines with operator, result, digest, schema,
    backup checksum, window, authorization, `authorization_verified=no`.
- `deploy/mentorpro`: dispatch; backup record gains `database`,
  `schema_state` and `verified`.
- `tests/app/test_deploy_rollout.py`: 67 unit tests and one Docker cycle
  test; `test_deploy.py` and `test_deploy_backup.py` adjusted.
- ADR-033 (I4 decisions), plan status, `.gitattributes`.

## Observation

| Check | Result |
| --- | --- |
| Unit tests (local) | 67 passed, Docker test skipped (no Docker locally) |
| Deploy and backup tests (local) | 25 passed, 2 skipped (Docker) |
| PR CI [40811750620](https://github.com/jonnabio/Mentor-Pro/actions/runs/40811750620) | success: 636 passed, 111 skipped with Docker mandatory (+68 = 67 unit + Docker cycle; skips unchanged); `LABELS OK`; both smoke tests; `MANIFEST OK` (`pr21-df21dd0`); publish and release skipped |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 744 passed, 3 skipped (Docker), 3.5 min (log `.ace/logs/verify/20261028-212753-11462`) |

The Docker cycle test, in project `mentorpro-i4test-<id>` with a local
`registry:2`, synthetic images and a synthetic writing schema:

- legacy schema: `MIGRATION REQUIRED`; drifted schema refused;
- missing preflight, missing authorization, preflight of another digest,
  stale preflight, stale/mismatched-database/mismatched-schema backup:
  each refused;
- compatible deploy, repeat `UNCHANGED`, deploy of a second release,
  rollback `--to` the first;
- rollback to the label-less image across `0001`: refused, app
  container, PostgreSQL container and `release.env` unchanged;
- retagged version tag, unknown digest, commit mismatch, dry-run
  manifest: each refused;
- failed smoke: `DEPLOY FAILED`, proposed rollback printed, no automatic
  change; manual rollback restored the previous release;
- `RELEASES` results in order; PostgreSQL container never recreated;
  all test resources removed and verified; production-named resources
  unchanged.

Parallel locking is tested by a second process holding the lock.

## PO corrections (review of PR #21, 2026-10-29)

Conditional approval; three corrections before merge.

1. **Compose failure.** `compose_up` returns the error; `deploy` and
   `rollback` record `FAILED` with the target image, `previous` and
   `error`, keep `release.env.previous`, print the proposed rollback and
   never report OK or run a health wait. Unit test with an injected
   failing `docker compose`; Docker test with a missing compose file.
2. **Final identity check.** Under the lock, `deploy` re-reads the
   registry content, the version-tag mapping, labels, commit and schema
   range (`verify_release_image`), then compatibility, preflight and
   backup evidence. An unreachable registry is a refusal. Docker test:
   tag moved after preflight, and registry stopped after preflight; both
   refused with containers unchanged.
3. **Rollback provenance.** A target needs a stored, valid release
   manifest, or the pre-script image captured once by the new
   `adopt-legacy` command (release.env pins it by digest, app and tutor
   run exactly it and are healthy, local image carries the repository
   digest; PO references recorded; no container change). Either way the
   target must have an `OK` or `UNCHANGED` line in `RELEASES`. Unit
   tests: ordinary manifest, approved legacy, unknown image, never-OK
   target, failed previous deployment, another repository, a tag.
   Docker test: adopted legacy candidate refused across `0001`;
   `release.env.previous` naming the failed release refused.

| Check | Result |
| --- | --- |
| Unit tests (local) | 77 passed, Docker test skipped |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 754 passed, 3 skipped (Docker), 205 s (log `.ace/logs/verify/20261029-081844-49`) |
| PR CI [40890220768](https://github.com/jonnabio/Mentor-Pro/actions/runs/40890220768) (head `70fa714`) | success: 646 passed, 111 skipped, Docker mandatory (+10 unit tests; skips unchanged, so the Docker cycle ran and passed); `LABELS OK`; both smoke tests; `MANIFEST OK`; publish and release skipped |

## Not verified

- Nothing ran on the server; python3, the compose plugin and anonymous
  GHCR reads there are assumptions until an authorized dry run (if the
  package is private, preflight refuses: an open item).
- Real GHCR digest semantics, the `v*` ruleset and partial-release
  recovery remain open release-qualification items (T043).

## Next

PO review of PR #21. I5 (rehearsal, migration) needs its own approval;
T039 remains a release prerequisite; T032/T033 acceptance pending.
