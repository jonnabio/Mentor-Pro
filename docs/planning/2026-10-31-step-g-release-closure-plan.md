# Step G Plan: I8 Release Closure for v2026.10.30-1

- **Date:** 2026-10-31
- **Role:** Architect
- **Status:** APPROVED (PO, 2026-10-31) and done in the I8 PR. Docs
  only; no server, migration or deployment change.
- **Inputs:** ADR-033 (I8: "rewrite the runbook around the commands;
  keep the manual blocks as an appendix; doc lint"),
  [release record](../progress/2026-10-31-production-release.md),
  `docs/runbooks/production-deployment.md`

## Deliverables

| # | Deliverable | Content |
| --- | --- | --- |
| G1 | Runbook rewrite (`docs/runbooks/production-deployment.md`) | Main path as `deploy/mentorpro` commands: `status`, `smoke`, `backup`, `verify-backup`, `preflight`, `deploy`, `maintenance start/end`, `rehearse`, `migrate`, `rollback`; who runs each (administrator with interactive `sudo`, or the agent); expected outputs and stop rules as used in steps C–E. Sections B, F, G and K shrink to one command each; the manual compose and `pg_dump` blocks move to an appendix |
| G2 | Section K update | Migration `0001` is done (2026-10-31). Remove "not yet authorized"; state that a pre-T036 image must never start again and that recovery is the G3 database restore, a separate PO decision |
| G3 | Recovery note | G3 restore steps from ADR-030 section 6, with the pre-migration dump `mentor_pro_2026-10-31_170927.dump` named as the restore point; not executed |
| G4 | Retention review | 4 dumps (528K) kept; ADR-033 rule (ten routine plus all pre-migration dumps, no automatic deletion) confirmed; nothing deleted |
| G5 | Release records | ADR-033 status (Proposed → Accepted, if the PO agrees); tracker: T036–T039 and T045 released in `v2026.10.30-1`; ACTIVE_CONTEXT flush |
| G6 | Server tidy-up list (proposal only) | `compose.deploy.yml` and its `.bak`/`.pre-*` copies are no longer used by the tooling; `deploy/__pycache__/`. Listed for a later, separately authorized clean-up; nothing removed in G |

## Out of scope

- No code change (feature freeze).
- No server change, backup, migration, deployment or container change.
- T034, T035 and T046 stay deferred.

## Acceptance

- `VERIFY_RESULT=pass gate=all` (doc lint).
- Every command in the runbook exists in `deploy/mentorpro` at tag
  `v2026.10.30-1`.
- No secret, token, tutor reference or student name in the documents.
- Merged into `dev` with PO approval, with green post-merge CI.

## Decisions requested

1. Approve G1–G6 as scoped.
2. ADR-033: mark Accepted (recommended; I1–I7 are now done in production).
