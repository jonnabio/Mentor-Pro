# T043 Plan: Release Metadata, Manifests, Tags and PR CI (ADR-033 I3)

- **Date:** 2026-10-28
- **Role:** Architect
- **Status:** APPROVED for implementation (PO, 2026-10-28) with the
  refinements below; implemented on `feature/T043-release-metadata`.
  Merge needs PO approval. No `main` merge, publication or deployment.
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

## Refinements required by the PO (2026-10-28)

### Release identity before the build

A new `identity` job (read-only: `contents: read`, `packages: read`)
decides version and build time **before** the image is built:

- push to `main`: `vYYYY.MM.DD-N`, N one above the highest N that day
  among git tags; a number already present in GHCR (published by a run
  that never tagged it) is skipped, never reused;
- anything else: `dev-<sha7>` or `pr<N>-<sha7>` (dry run).

The single build (`load: true, push: false`) receives these labels; a
label check compares them with the code-defined schema range before the
smoke tests. The smoke-tested image is the one pushed (RCA-005 kept).
The build time comes from `identity`, so every later step, and every
retry, uses the same values.

### Concurrent runs

- `concurrency: ci-${{ github.ref }}` with cancellation only for pull
  requests: runs on `main` queue one after another and are never
  cancelled midway.
- The git tag is created with a plain `git push` of a new ref, which
  fails if the ref exists: two runs can never hold the same version.

### Failure and retry matrix

| Situation | Behavior | Recovery |
| --- | --- | --- |
| Tests, label check or smoke test fail | nothing published, no tag | fix on a branch; new run |
| Version already in GHCR or as a git tag before publishing | `docker-build` stops before any push | new run (allocates the next number) |
| Publication fails partway (some image tags pushed) | job fails; no git tag, no release | new run; the partly used number is burned (skipped by `identity`) and never deployable |
| Published, but tag or release creation fails | `release` job fails | **re-run only the `release` job**: it reuses the recorded version, build time and digest |
| `release` re-run, tag exists | accepted only if it points at this commit; otherwise fails | investigate; never move the tag |
| `release` re-run, GitHub Release exists | accepted only if its manifest is byte-identical | investigate; never replace the asset |
| `docker-build` re-run after a successful publish | refused (version taken): a rebuild would have another digest | re-run `release` only, or start a new run |

A version counts as **released** only with all three: the image in
GHCR, the git tag on the commit, and the GitHub Release with a valid
manifest. The later deployment commands (I4) accept nothing else.

### Least privilege

| Job | Permissions |
| --- | --- |
| workflow default, `tests` | `contents: read` |
| `identity` | `contents: read`, `packages: read` |
| `docker-build` | `contents: read`, `packages: write` (used only by the publish steps, pushes to `main` only) |
| `release` (pushes to `main` only) | `contents: write` |

### Tag ruleset

Checked read-only on 2026-10-28: `GET /repos/jonnabio/Mentor-Pro/rulesets`
returned `[]`. **No `v*` ruleset exists.** It must be created by the
owner and verified before the first authorized release; the workflow
itself never moves or deletes tags either way.

## Plan (increments inside T043)

| Step | Change | Verification |
| --- | --- | --- |
| 1 | `SCHEMA_MIN`/`SCHEMA_MAX`, `migrate range`, tests | unit tests |
| 2 | OCI labels at build; label check step | dry run on the PR itself |
| 3 | `scripts/release/release.py` (identity, labels, manifest, validation against `docs/release/manifest.schema.json`), tests | unit tests, artifact on PR |
| 4 | Release job (tag, manifest, GitHub Release) on `main` only | logic tested by unit tests and the dry-run artifact; **first real run only at the next authorized merge to `main`** |
| 5 | `pull_request` to `dev` | the T043 PR itself is the first run |
| 6 | Runbook note: where to find the digest and manifest | deferred to I8 (runbook rewrite) |

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
  Not configured as of 2026-10-28.
- No server, production, secret or GHCR change. T039 remains a release
  prerequisite; T032/T033 acceptance remains pending.

## PO decisions (2026-10-28)

1. PR #18 merged; T043 implementation approved on a feature branch.
2. Release wording: "Published, not authorized for deployment".
3. The `v*` ruleset (no update, no deletion) must be verified before the
   first authorized release; not configured yet.
4. Not authorized: merge into `main`, GHCR publication, deployment,
   migration, server changes.
