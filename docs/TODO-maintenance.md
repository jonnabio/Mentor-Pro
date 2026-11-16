# Maintenance Backlog

Status: **open**. Started 2026-11-16 under PO-QBANK-CLOSE-2026-11-16, when
the Question Bank development initiative closed after T070 acceptance.

Minor, non-blocking technical issues. Nothing here is a mandatory acceptance
failure. Each item needs its own authorization before work starts, and none
reopens the Question Bank initiative.

| # | Item | Impact | Smallest fix | Source |
| --- | --- | --- | --- | --- |
| M1 | `replenishment.run` marks every difficulty of a request `candidates_generated`; cells that got no candidate are later closed as `reviewed` | Mislabels request records only; no effect on eligibility, practices or spending | Mark only the difficulties that received a candidate | T066, T070 |
| M2 | `tests/app/test_practice_browser.py` (T048 shortage retry in the browser) is opt-in and not run in CI | Test gap; the T069 browser tests in CI cover sizes, the practice and the result | Add the test to the CI browser step and raise the executed minimum | T048, T070 |
| M3 | The `mentorpro` sudo rule is broader than the helper needs | Hardening; pending a PO decision | Narrow the rule to the helper's subcommands | Deployment stages |
| M4 | Workstation only: Windows Application Control blocks `initdb.exe`, so 5 `test_deploy_backup.py` tests fail in the local gate | The local gate cannot pass; CI (Linux) runs the tests and passes | Allow `initdb.exe` in the workstation's App Control policy (the owner's decision) | T069 |

## Operational follow-ups (not development)

- **Authentic tutor-dashboard review:** the tutor's first real decision
  through "Revisión de preguntas" completes the production proof of
  dashboard verdicts (T070 criterion 7). It is operational acceptance, not a
  development blocker.
- **Remaining three subjects:** monitor Español, Ciencias and Estudios
  Sociales with `replenish capacity`. Report to the PO when the real
  composer builds a five-question practice. Request PO authorization before
  changing any subject's bank-only configuration.
