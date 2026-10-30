# Release-Readiness Assessment: T036–T039 Writing Revision Release

- **Date:** 2026-10-29
- **Role:** Architect
- **Status:** PROPOSED for PO review. Assessment only: no server,
  migration, deployment, GHCR publication or merge into `main` is
  authorized by it.
- **Inputs:** ADR-030 (production), ADR-031 (tutor), ADR-032 (attempts,
  T036–T039), ADR-033 (deployment workflow, I1–I8), tracker, T032–T045
  results, repository and GitHub state on 2026-10-29

## 1. Where things stand

| Area | State | Evidence |
| --- | --- | --- |
| Production | image `sha256:5d69fe6c…1137` (T032 + T033), pre-T036, writing schema `legacy`; app on `127.0.0.1:8080` and the house Wi-Fi address, tutor on `127.0.0.1:8081` only | rollout 2026-10-28, `/opt/mentor-pro/RELEASES` |
| T032/T033 real-user acceptance | **not done**: deployed, not yet used by the student and the parent | ACTIVE_CONTEXT, T032/T033 notes |
| T036–T039 | all merged into `dev` and verified (T039: `e22d59d`, `dev` CI 40993295690, 773 passed) | results T036–T039 |
| Deployment tooling (ADR-033 I1–I5) | merged into `dev`, tested on synthetic data and local Docker only; never run on the server | results T041–T045 |
| `main` | `2f6a4b3` (2026-10-27); `dev` is **59 commits ahead** | `git rev-list --count origin/main..origin/dev` |
| `v*` tag protection | **not configured** (rulesets API returns `[]`); one old tag `v0.1.0`, no GitHub Release | GitHub API |
| Real GHCR release path | **not qualified**: version allocation, publish by version tag, digest read-back and Tag and Release have only run as skipped or dry-run steps | T043 result |
| Open defects | T035 (tutor token of 1–15 characters exits 1 instead of 78; still refuses to start); T034 (flaky test) | tracker |

## 2. Dependencies of the release

```text
T032/T033 acceptance ─┐
v* ruleset ───────────┼─> merge dev → main (first real release: GHCR, tag, manifest)
(T035 fix, optional) ─┘              │
                                     v
            I6: adopt deploy/ on the server (read-mostly: status, smoke)
                                     │
                                     v
            timing rehearsal on a real backup (maintenance window)
                                     │
                                     v
   I7: release window: maintenance start → backup → rehearse → migrate 0001
       → deploy T036–T039 image → smoke → maintenance closed
                                     │
                                     v
            real-user check of the revision flow; I8 runbook
```

- T037, T038 and T039 are released together (PO); all need migration
  `0001` (T036), and the image refuses to start on the `legacy` schema.
- The migration is only possible through `mentorpro migrate` (G2), which
  needs a production manifest from a real release (no dry-run manifest is
  accepted), `BACKUP OK`, `REHEARSAL OK` in the same window, and window
  and PO references.
- Any recovery after `apply` is a database restore (G3), a separate PO
  decision; no automatic restore or application rollback exists.

## 3. Findings

### 3.1 Real-user acceptance (T032/T033)

The writing bank and tutor service have not been used by their real
users. Doing that **before** the release:

- validates the current flow (write, reload, submit; parent review over
  the SSH tunnel; feedback after an app restart) on the version users
  already have;
- creates the real writing records the migration must preserve, so the
  rehearsal proves `0001` on real, not empty, data;
- separates "the writing feature works" from "the revision release
  works" if anything fails.

Real records are created by real use only; nothing synthetic is added to
production.

### 3.2 Repository and release identity

- The first release from `main` carries 59 commits (T034–T045 work
  included). It is the first run of the guarded publish path: version
  allocation, `refuse-taken`, push by version tag, digest read-back, tag
  and GitHub Release with the manifest.
- Without the `v*` ruleset a release tag could be moved or deleted, which
  breaks the manifest's immutability (ADR-033 PO decision 3). The ruleset
  is a repository-admin action, then verified through the API.
- A partial release (image published, tag or Release failed) has a
  documented but unexercised recovery (T043). The first release should be
  watched and its outputs checked: tag → commit, Release manifest →
  digest, `docker manifest inspect`/registry digest equal to the
  manifest, OCI labels.

### 3.3 Server readiness (I6, not verified)

Assumptions made by T041–T045 that only the server can confirm:

- `python3` (standard library), Docker Compose plugin with
  `config --format json` and `up --wait`;
- `deploy/compose.yml` matches the running services (ports
  `127.0.0.1:8080`, the Wi-Fi address binding of ADR-030 section 10,
  tutor `127.0.0.1:8081`, env files under `/etc/mentor-pro`, volume and
  network names);
- `/var/lib/mentor-pro/rehearsal` root-owned `0700`; free space on the
  backup, rehearsal and Docker filesystems;
- `adopt-legacy` records the running pre-T036 image as the rollback
  provenance for the current release.

I6 changes no container: copy `deploy/`, create `release.env` for the
running digest, `adopt-legacy`, `status`, `smoke`. A mismatch found here
stops the plan before any window.

### 3.4 Migration window and timing

- The last production backup was 127,791 bytes; restore and migration of
  such a dump should take minutes, but the 60-minute window and the
  40-minute checkpoint were sized without a production measurement.
- `rehearse` requires an open maintenance window (PR #23 correction), so
  measuring on a real backup means a short planned outage: `maintenance
  start`, `backup`, `rehearse`, `maintenance end`. Its durations then
  feed the projection for the release window.
- With a dump this small, the PO may instead accept the release window
  itself as the measurement (the script refuses to migrate if the
  projection exceeds 60 minutes, and `maintenance end` restores service
  on the unchanged schema).

### 3.5 Recovery authorization

- Before `apply`: controlled `maintenance end`, already approved (I5).
- After `apply` failure: services stay stopped and the script prints
  DATABASE RECOVERY DECISION REQUIRED. The G3 restore (pre-migration
  backup into a new database, ADR-030 section 6) needs a PO decision.
  Pre-agreeing the decision maker, the contact path during the window and
  the maximum time before deciding avoids an open-ended outage.
- A pre-T036 image is never started on a migrated database; the T044
  rollback refuses it.

## 4. Recommended action sequence

Each step needs its own PO authorization; none is authorized by this
assessment.

| # | Step | Changes | Who | Done when |
| --- | --- | --- | --- | --- |
| 1 | T032/T033 real-user acceptance on the current production | real use only | student, parent, PO | the four acceptance checks pass and are recorded |
| 2 | `v*` tag ruleset (no deletion, no update, no force push; bypass none or admin only) | GitHub settings | repository owner | rulesets API shows it active for `refs/tags/v*` |
| 3 | (Optional) T035 fix on a feature branch into `dev` | code | Developer | merged, `dev` CI green |
| 4 | Release PR `dev` → `main`; first real release | GHCR, tag, Release | PO approves merge | `main` CI green; tag, Release, manifest and registry digest agree; labels checked |
| 5 | I6: adopt `deploy/` on the server | files under `/opt/mentor-pro`, `/var/lib/mentor-pro`; no container | administrator | `adopt-legacy`, `status`, `smoke` pass; findings in 3.3 confirmed |
| 6 | Timing rehearsal on a real backup (or PO waiver, 3.4) | short outage, no schema change | administrator | `REHEARSAL OK`, durations recorded, `maintenance end` OK |
| 7 | I7 release window | migration `0001`, app and tutor on the release digest | administrator, PO reachable | `MIGRATE OK`, `DEPLOY OK`, smoke; window ≤ 60 minutes |
| 8 | Real-user check of the revision flow | real use only | student, parent | revise, tutor re-evaluates, comparison visible |
| 9 | I8 runbook around the commands; retention review | docs | Architect | merged into `dev` |

Steps 1–3 have no server effect and can proceed in parallel. Step 4 is
the first publication and should precede the server steps, because I6
and I7 consume its manifest.

## 5. PO decisions requested

1. Approve the sequence in section 4, or reorder it (in particular:
   acceptance before the release, as recommended).
2. Step 6: a separate timing rehearsal window, or accept the release
   window as the measurement given the dump size.
3. Recovery: name the G3 decision maker and the maximum wait during the
   release window.
4. Include the T035 fix in the release (recommended; small) or defer it.
5. Authorize step 1 now (real-user acceptance), and the repository owner
   to create the `v*` ruleset (step 2).
