# Step B Plan: First Real Release from `main`

- **Date:** 2026-10-30
- **Role:** Architect
- **Status:** PROPOSED for PO review. Nothing here is authorized: no
  merge into `main`, GHCR publication or tag until the PO approves step B.
- **Inputs:** [release preparation](2026-10-30-release-acceptance-and-inspection-plan.md),
  [server inspection](../progress/2026-10-30-server-inspection.md),
  `.github/workflows/ci.yml` (T043), ADR-033

## Scope

Release PR `dev` → `main`: about 75 commits, 63 files (T034 to T045 work,
T036 to T039 writing revision milestone, deployment tooling). Scope
frozen: no new feature work; T035 and T046 deferred.

The release image refuses to start on the production `legacy` schema
(T036). Step B publishes it only; it is not deployed until step E (I7),
after C and D.

## Preconditions (all must hold before the PO approves the merge)

| # | Condition | State on 2026-10-30 |
| --- | --- | --- |
| P1 | T032/T033 functional acceptance | PASSED (PO observations) |
| P2 | `v*` tag ruleset active, verified through the API | **done** 2026-10-30: ruleset `release-tags` (id 26236844), see below |
| P3 | `dev` CI green on the release PR head | checked on the release PR |
| P4 | Release PR scope = `origin/main..origin/dev`, nothing else | checked on the release PR (`main` is an ancestor of `dev`; nothing on `main` missing from `dev`) |
| P5 | Server inspection: no blocker for B | done (A1, A2 needed before C only) |

## P2 evidence: `v*` tag ruleset

Created 2026-10-30 by the agent with the `gh` account `jonnabio`
(repository admin) under explicit PO authorization, using the Part 2
command of the release preparation plan unchanged. Read back with
`gh api repos/jonnabio/Mentor-Pro/rulesets/26236844`:

| Field | Value |
| --- | --- |
| Name, id | `release-tags`, 26236844 |
| Target, enforcement | `tag`, `active` |
| Include | `["refs/tags/v*"]` (exclude `[]`) |
| Bypass actors | `[]`; `current_user_can_bypass` `never` |
| Rules | `update`, `deletion`, `non_fast_forward` |
| Tag creation | allowed (no `creation` rule) |

No tag was created, moved or deleted; `v0.1.0` untouched.

## Integration evidence since the plan

| PR | Merge | `dev` CI |
| --- | --- | --- |
| #30 ACE merge record | `5afbe7e` | 41076093767 green (773 passed, 111 skipped, labels and manifest OK) |
| #31 session handoff | `7ecd1da` | 41103503792 green (773 passed, 111 skipped, `MANIFEST OK dev-7ecd1da`) |

## What the merge triggers (push to `main`)

1. `identity`: release mode; version `vYYYY.MM.DD[-N]` from the UTC
   date, skipping numbers already tagged or already in GHCR.
2. `test`: full suite including Docker tests.
3. Build the candidate with OCI labels (version, revision, created,
   schema range); `check-labels`; app and tutor smoke tests.
4. "Refuse a version that is already taken" (GHCR and git tag).
5. Push `ghcr.io/jonnabio/mentor-pro:<version>`, `:sha-<commit>` and
   `:testing`; read back the digest.
6. `release`: create tag `<version>` on the merge commit and a GitHub
   Release carrying `release-manifest.json` (version, commit, digest,
   run).

## Verification after the run (read-only, recorded in ACE)

- Tag `<version>` points at the merge commit; it is protected (P2).
- Release manifest digest = digest of `ghcr.io/jonnabio/mentor-pro:<version>`
  (`docker buildx imagetools inspect`) = `:sha-<commit>`.
- OCI labels on the pulled image match the manifest (version,
  revision, created).
- `main` CI run green; tests count, `LABELS OK`, smoke, `MANIFEST OK`.
- Nothing on the server changed; production still on
  `sha256:5d69fe6c…1137`.

## If the run fails part way

- Before the push (steps 1–4): nothing published; fix on `dev` with a new
  PR, then a new release PR.
- Image pushed, tag or Release failed: re-run only the `release` job
  (T043 recovery: an existing tag must point at the same commit, an
  existing Release must carry the same manifest). The version is never
  reused by a new run.
- No tag is moved or deleted (ruleset).

## Notes

- `main` has no branch protection (API 404). Not a blocker for step B;
  merges stay PO-gated by process. A `main` ruleset is a possible
  later owner action.
- The merge method is a merge commit (as for `dev`), pinned to the
  reviewed head with `--match-head-commit`.

## Decision requested

Approve step B once P2 is verified: open the release PR, check P3/P4,
then merge into `main` and verify as above.
