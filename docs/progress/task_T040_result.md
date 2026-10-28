# T040 Result: Deployment Simplification and Repeatability Assessment

- **Date:** 2026-10-28
- **Role:** Architect
- **Branch:** `docs/T040-deployment-assessment` (from `dev` at `b0a3509`)
- **Status:** assessment delivered for Product Owner review; nothing
  implemented, no server, database, image or workflow change

## Thought

Precondition: T038 merged as `b0a3509` (head `13851f4` unchanged, scope
as reviewed); `dev` CI
[40760514180](https://github.com/jonnabio/Mentor-Pro/actions/runs/40760514180)
green (524 passed, 102 skipped; image built, both smoke tests passed;
GHCR login and publish skipped). T038 is integrated.

## Action

Analyzed ADR-030/031/032, the production runbook (A to K), `ci.yml`,
`Dockerfile`, the local compose file, `app/writing/migrate.py` and the
start-up schema guard. Produced:

- `docs/planning/2026-10-28-deployment-simplification-assessment.md`:
  inventory and current workflow, ten findings (R1 to R10), proposed
  architecture, command interface, backup/migration/rollback design,
  gates G0 to G4, increments I1 to I8, open questions;
- `docs/adr/ADR-033-repeatable-deployment-workflow.md` (Proposed).

## Observation

Highest risks: no compatibility check before deployment or rollback
(rollback to a pre-T036 image on a migrated schema breaks writing);
backups are listed, never restored; the production compose file is not
in Git. Kept: digest pinning, secrets handling, tutor boundary, explicit
migrations, start-up schema guard.

Verification: documentation only; `bash .ace/scripts/verify.sh`
`VERIFY_RESULT=pass gate=all` (log `.ace/logs/verify/20261028-141229-2432`).

## Next

PO review of ADR-033 and the open questions; then I1 to I5 as separate
tasks (no production change); T039 before the T037+T038 release.
