# T043 Result: Release Metadata, Manifests, Tags and PR CI (ADR-033 I3)

- **Date:** 2026-10-28
- **Role:** Developer
- **Branch:** `feature/T043-release-metadata` (from `dev` at `22a6847`)
- **Status:** implemented; local gate and PR CI green; PR #19 to `dev`
  awaiting PO approval. Nothing published, tagged or released.

## Thought

PR #18 (plan, documentation only, head `165f65d` unchanged) merged as
`22a6847`; `dev` CI 40790275976 green (542 passed). The PO approved the
plan with refinements: identity before the build, concurrent and partial
release handling, least privilege, PR CI for `dev`.

## Action

- `app/writing/migrations.py`: `MIGRATIONS`, `SCHEMA_MIN`, `SCHEMA_MAX`
  (both `0001`); `python -m app.writing.migrate range` prints them
  without a database.
- `scripts/release/release.py`: `identity` (version and build time,
  `$GITHUB_OUTPUT` format), `check-labels`, `manifest`, `validate`.
- `docs/release/manifest.schema.json`: JSON Schema (draft 2020-12),
  separate rules for published and dry-run manifests; the exact wording
  "Published, not authorized for deployment".
- `.github/workflows/ci.yml`:
  - `pull_request` to `dev`; concurrency per ref, never cancelling
    `main`;
  - `identity` job (read-only) before the build; labels at the single
    build; label check; dry-run manifest artifact off `main`;
  - on pushes to `main` only: refuse a taken version, publish
    (`:vYYYY.MM.DD-N`, `:sha-<commit>`, `:testing`), digest re-read from
    the registry; `release` job (the only `contents: write`): atomic
    annotated tag, idempotent GitHub Release with the manifest.
- Plan updated with the failure/retry matrix and recovery procedure.
- `tests/app/test_release.py` (26 tests): schema range, `migrate range`
  without a database, version allocation, identity, labels, manifests
  (valid, eight invalid kinds, byte-identical retries) and the workflow
  rules (triggers, concurrency, mandatory Docker tests, publication only
  on `main`, no force/tag deletion, least privilege, build-once order,
  release wording).

## Observation

| Check | Result |
| --- | --- |
| `tests/app/test_release.py` | 26 passed |
| `bash .ace/scripts/verify.sh` | `VERIFY_RESULT=pass gate=all`, 677 passed, 2 skipped (Docker), 14.9 min (log `.ace/logs/verify/20261028-180032-8689`) |
| PR CI [40792928230](https://github.com/jonnabio/Mentor-Pro/actions/runs/40792928230) (first `pull_request` run into `dev`) | success: tests 568 passed, 111 skipped (Docker tests mandatory); identity `pr19-3468731`; build with six labels; `LABELS OK`; both smoke tests passed; `MANIFEST OK`; artifact `manifest-dry-run`; GHCR login, refuse-taken, publish and `Tag and Release` skipped |
| `v*` tag ruleset | **not configured**: `GET /repos/jonnabio/Mentor-Pro/rulesets` returned `[]` |

Not verifiable before an authorized merge to `main`: the real version
allocation against GHCR, publication with the version tag, digest
re-read, git tag and GitHub Release, and the retry paths. They are
covered only by unit tests and the workflow rule tests until then.

No server, production, GHCR or `main` change.

## Next

PO review of PR #19. Before the first authorized release: the owner
creates the `v*` ruleset and it is verified. I4 and I5 need separate
tasks and approvals; T039 remains a release prerequisite.
