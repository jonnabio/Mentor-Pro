# T043 Plan: Release Metadata, Manifests, Tags and PR CI (ADR-033 I3)

- **Date:** 2026-10-28
- **Role:** Architect
- **Status:** PROPOSED for Product Owner review. Not implemented. I3 needs
  separate implementation and merge authorization.
- **Decision record:** [ADR-033](../adr/ADR-033-repeatable-deployment-workflow.md)
  decisions 3 and 7, refinements R2, R3 and R7

## Analyze

Current `.github/workflows/ci.yml`:

- triggers on push to `dev` and `main`, and on pull requests to `main`
  only; feature PRs into `dev` are verified locally until merge
  (assessment finding R9);
- builds the image once (`mentor-pro:candidate`), smoke-tests it, and on
  push to `main` only pushes `:testing` and `:sha-<commit>` to GHCR;
- the image has no OCI labels; the digest is found by hand; no release
  record exists outside the server's hand-written `RELEASES`.

Schema facts: the only writing migration is `0001_student_attempts`
(`app/writing/migrations.py`, `STUDENT_ATTEMPTS`). Images before T036
cannot check the schema; images with T036 refuse to start on an older
one.

## Discuss (design)

### 1. Supported-schema range (ADR-033 R2)

- One source of truth in code: `SCHEMA_MIN` and `SCHEMA_MAX` next to
  the migrations (today both `0001`; `SCHEMA_MAX` is the latest migration
  this image can apply, `SCHEMA_MIN` the oldest it can run on).
- `python -m app.writing.migrate range` prints them as JSON; a test keeps
  them consistent with the migration list.
- Images without labels are treated as `none..none` (pre-T036) by the
  later deployment commands (I4).

### 2. OCI labels

Added at the single build step (`docker/build-push-action` `labels:`),
so the smoke-tested image is the published image (RCA-005 unchanged):

| Label | Value |
| --- | --- |
| `org.opencontainers.image.revision` | commit SHA |
| `org.opencontainers.image.source` | repository URL |
| `org.opencontainers.image.created` | build time (UTC) |
| `org.opencontainers.image.version` | release tag on `main`, else `dev-<short sha>` |
| `io.mentorpro.schema.min` / `.max` | from `migrate range` |

A CI step reads the labels back with `docker inspect` and fails if any
is missing or differs from the expected values.

### 3. Release manifest and tag (decision 3, R3)

Only on push to `main`, after the existing publish step succeeds:

1. Tag `vYYYY.MM.DD-N` (UTC date, N = 1 + count of existing tags for
   that date). The job fails if the tag exists; tags are never moved or
   deleted (immutability). Protected by a GitHub tag ruleset
   (`v*`: no update, no deletion), configured once by the repository
   owner.
2. `release-manifest.json`, validated against a JSON schema in the
   repository before upload:

   ```json
   {
     "release": "v2026.11.02-1",
     "image": "ghcr.io/jonnabio/mentor-pro@sha256:<digest>",
     "commit": "<sha>",
     "ci_run": "<run id>",
     "schema": {"min": "0001", "max": "0001"},
     "smoke": {"student": "pass", "tutor": "pass"},
     "created": "<UTC>"
   }
   ```

   The digest comes from the registry response of the push, then is
   re-read with `docker buildx imagetools inspect` and compared.
3. A GitHub Release with the manifest as its only asset. The release text
   says: **"Published, not authorized for deployment"** (R3). Deployment
   authorization stays with the PO and the operator (G1, G2).

Permissions: `contents: write` only in the new release job; the build
job keeps `contents: read` and `packages: write`.

On `dev` and on pull requests the same manifest is produced as a
workflow artifact named `manifest-dry-run` with no tag, release or push,
so the logic is exercised on every integration without publishing.

### 4. CI for pull requests into `dev` (finding R9)

- `pull_request: branches: [main, dev]`.
- Tests (including the mandatory Docker tests), image build and both
  smoke tests run on every PR; GHCR login, publish, tag and release stay
  limited to push to `main`.
- Fork PRs get no secrets (default); none are needed.

## Plan (increments inside T043)

| Step | Change | Verification |
| --- | --- | --- |
| 1 | `SCHEMA_MIN`/`SCHEMA_MAX`, `migrate range`, tests | unit tests |
| 2 | OCI labels at build; label check step | dry run on the PR itself |
| 3 | `scripts/release/manifest.py` (build, validate against `docs/release/manifest.schema.json`), tests | unit tests, artifact on PR |
| 4 | Release job (tag, manifest, GitHub Release) on `main` only | logic tested by unit tests and the dry-run artifact; **first real run only at the next authorized merge to `main`** |
| 5 | `pull_request` to `dev` | the T043 PR itself is the first run |
| 6 | Runbook note: where to find the digest and manifest | doc lint |

## Verify

- ACE gate locally; the T043 PR must show a green PR run (new trigger)
  with the `manifest-dry-run` artifact and the label check.
- Not verifiable before an authorized `main` merge: the real tag,
  GitHub Release and digest re-read. These are recorded as untested
  until that merge, which itself needs PO authorization.

## Risks and constraints

- Merging T043 into `dev` publishes nothing. The release job runs only
  on `main`, and merging into `main` is not authorized.
- A tag ruleset is a repository setting, which the PO or owner must
  apply; the workflow does not depend on it to refuse an existing tag.
- No server, production, secret or GHCR change. T039 remains a release
  prerequisite; T032/T033 acceptance remains pending.

## Decisions requested

1. Approve this plan for implementation as T043.
2. Approve "Published, not authorized for deployment" as the release
   wording.
3. Confirm that the owner will add the `v*` tag ruleset (no update, no
   deletion) before the first release.
