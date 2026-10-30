# T044 Plan: Preflight, Compatibility, Deploy and Rollback (ADR-033 I4)

- **Date:** 2026-10-28
- **Role:** Architect
- **Status:** APPROVED (PO, 2026-10-28) with the decisions below;
  implemented on `feature/T044-deploy-rollback` (PR #21 to `dev`, merge
  needs PO approval). No server, production, GHCR or `main` change.
- **Decision record:** [ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md)
  decisions 2, 4, 6 and 7; refinements R1, R2, R3 and R7
- **Builds on:** T041 (`status`, `smoke`, `deploy/compose.yml`), T042
  (`backup`, `verify-backup`), T043 (labels, manifest, release tags)

## Analyze

What exists after T043:

- every image built by CI carries `org.opencontainers.image.version`,
  `.revision`, `.created` and `io.mentorpro.schema.min` / `.max`;
- a release on `main` would publish `ghcr.io/jonnabio/mentor-pro` with
  `:vYYYY.MM.DD-N` and attach a validated manifest naming the digest;
  no release has been made yet, so the digest path is untested;
- `deploy/compose.yml` reads `MENTOR_PRO_IMAGE` from `release.env`;
  `deploy/mentorpro` has `status`, `smoke`, `backup`, `verify-backup`;
- the live schema state comes from `writing.schema_migration` and
  `migrations.state()`: `fresh`, `legacy`, `current` or `drifted`.

Current production runs a pre-T036 image (no labels) on a `legacy`
schema. The risk I4 closes (assessment R1): nothing stops a deployment or
a rollback whose image cannot run on the live schema. A pre-T036 image on
a migrated schema recreates `uq_submission_exercise` and breaks drafts
and submissions (ADR-032).

## Discuss (design)

### 1. Live schema, read without the target image

`mentorpro` reads the schema with `psql` inside the running `postgres`
container, read-only (`default_transaction_read_only=on`), so the answer
never depends on the image being deployed:

| Database state | Live schema | Meaning |
| --- | --- | --- |
| `fresh` or `legacy` | `none` | no writing migration applied |
| `current` | `0001` (highest id in the ledger) | migrated |
| `drifted` | refuse | needs `repair`; every I4 command stops |
| unreadable | refuse | `UNKNOWN` never counts as compatible |

### 2. Compatibility rule (ADR-033 R2, decision 4)

An image may run when `schema.min <= live <= schema.max`. An image
without the labels is treated as `min = max = none` (pre-T036). So:

| Image | live `none` | live `0001` |
| --- | --- | --- |
| pre-T036, no labels | allowed | **refused** |
| T036 or later (`0001`..`0001`) | refused: migration required (G2, I5) | allowed |

The rule is one function, tested on its own, and checked again at the
moment of change, not only in `preflight`.

### 3. Image identity: digest only

- The target is always `ghcr.io/jonnabio/mentor-pro@sha256:<digest>`;
  tags are never used to choose what runs.
- **Digest semantics (open PO item from T043).** The manifest records
  the registry digest returned for the pushed reference: the digest of
  the image manifest (or image index, if one is ever produced), not the
  local image id. `preflight` verifies that before trusting it:
  1. pull by digest;
  2. `RepoDigests` of the pulled image contains exactly that digest;
  3. `docker buildx imagetools inspect` of the version tag returns the
     same digest (the tag still points where the manifest says);
  4. the image labels equal the manifest (version, revision, schema
     range).
  Any mismatch is `PREFLIGHT FAILED`; no fallback to a tag.
- I4 proves these semantics in CI against a throwaway local registry
  (`registry:2` on an internal network), pushing synthetic images built
  in the job. It does not touch GHCR. The first real GHCR release still
  has to be checked by hand once (see "Not verified by I4").

### 4. Commands

All print codes, digests and counts only; never env files or tokens.

| Command | Does | Writes | Gate |
| --- | --- | --- | --- |
| `preflight <manifest.json>` | validates the manifest (published, not dry run), checks section 3, reads the live schema, prints the plan: `DEPLOY COMPATIBLE`, `MIGRATION REQUIRED (G2, not in I4)` or `REFUSED <reason>`; writes a preflight record | image cache, `<state>/preflight/<digest>` | none |
| `deploy <manifest.json> --window <ref>` | requires a passing preflight record for the same digest (max age to decide), a `BACKUP OK` record (max age to decide) and compatibility re-checked now; writes `release.env` atomically (temp file, then rename, previous kept as `release.env.previous`); `compose up -d --no-deps app tutor`; waits for health; runs `smoke`; appends `RELEASES` | `release.env`, `app` and `tutor` containers | G1 |
| `rollback [--to <version>] --window <ref>` | picks the newest earlier `RELEASES` entry with result `OK` whose image, pulled by digest and label-checked again, is compatible with the live schema; then as `deploy` | same | G3 (operator, same schema only) |

Rules common to `deploy` and `rollback`:

- **Never** touch `postgres`, its volume or network; never run
  `migrate` (that is I5, G2); never `down`, never `down -v`.
- **Idempotent (R1):** target digest already running and healthy →
  `UNCHANGED`, nothing written. Rollback with no compatible candidate →
  `REFUSED`, nothing written, prints the database-restore pointer
  (ADR-030 section 6, G3 with PO approval).
- **No automatic rollback.** A failed health check or smoke after
  `deploy` is reported as `DEPLOY FAILED` with the exact `rollback`
  command; the operator decides (proposal; PO decision 3 below).
- **Records (R7):** `RELEASES` is append-only, one line per attempt:
  UTC time, operator account, action, version, digest, live schema,
  result (`OK`, `FAILED`, `REFUSED`, `UNCHANGED`), `--window`
  reference. The script cannot invent the reference; it only records
  what the operator passes.
- A lock file prevents two `deploy`/`rollback` runs at once.

### 5. Gates kept explicit

| Gate | I4 behavior |
| --- | --- |
| G0 release | input only: a manifest with "Published, not authorized for deployment" |
| G1 deploy | refused without preflight, `BACKUP OK`, compatibility and a window reference |
| G2 migration | not implemented; a T036+ image on `none` is refused with `MIGRATION REQUIRED` |
| G3 rollback | same-schema only; crossing `0001` is refused and points to the approved restore procedure |
| G4 acceptance | unchanged, manual |

## Test plan (all isolated, synthetic)

- Unit tests (no Docker): compatibility table, label-less images, live
  schema mapping including `drifted` and unreadable, manifest checks,
  `RELEASES` parsing and candidate selection, argument refusals.
- Docker tests, mandatory in CI (`MENTORPRO_REQUIRE_DOCKER=1`), in a
  compose project `mentorpro-i4test-<id>` with its own network, volume,
  synthetic database and local registry; never production names:
  1. two synthetic releases on schema `0001`: preflight, deploy,
     `UNCHANGED` on rerun, rollback to the first, smoke each time;
  2. a label-less image on a migrated schema: preflight `REFUSED`,
     rollback `REFUSED`, nothing changed (digest and `release.env`
     unchanged);
  3. a `0001` image on a `legacy` schema: `MIGRATION REQUIRED`;
  4. digest checks: wrong digest, retagged tag, label mismatch, dry-run
     manifest → each `PREFLIGHT FAILED`;
  5. failed smoke after deploy: `DEPLOY FAILED`, no automatic change,
     rollback command printed;
  6. cleanup verified: no `mentorpro-i4test-*` resource remains.
- Text checks on the script: no `down -v`, no `postgres` in an `up` or
  `rm` command, no `migrate` call.

## Not in I4

`rehearse` and `migrate` (I5), database restore, any server
installation or run, the GHCR release itself, the `v*` tag ruleset,
T039, automated retention.

## Not verified by I4

- The real GHCR digest path: needs one authorized release, then a
  read-only `preflight` of it on the server.
- The `v*` tag ruleset: still not configured; must exist and be verified
  before the first release.
- Partial-release recovery outside automated tests (T043).

## PO decisions (2026-10-28)

1. Manifest supplied by the operator as a local file; the server needs
   no GitHub credential. APPROVED.
2. Preflight and verified-backup evidence expire after six hours.
   APPROVED.
3. Manual rollback only; no automatic rollback. APPROVED.
4. Every deploy and rollback needs a release-window reference **and** a
   PO authorization reference (stronger than proposed). REQUIRED. They
   are recorded, not verified.
5. Implementation on a feature branch, PR to `dev`. APPROVED; merge
   needs separate approval.

## Decisions as proposed

1. **Manifest source on the server:** the operator downloads the
   release manifest and passes the file (proposed; the server needs no
   GitHub credential), or the script fetches it.
2. **Freshness windows:** preflight record and `BACKUP OK` must be from
   the last 6 hours and for the same digest (proposed).
3. **Failure after deploy:** manual rollback with the printed command
   (proposed) or automatic rollback.
4. **`--window` reference** required for `deploy` and `rollback`
   (proposed), though R7 requires it only for migration and restore.
5. Approve I4 as task T044 on a feature branch, PR to `dev`, not merged
   without approval.
