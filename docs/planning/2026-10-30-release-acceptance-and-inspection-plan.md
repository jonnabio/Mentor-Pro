# Release Preparation: Acceptance, Tag Protection, Server Inspection

- **Date:** 2026-10-30
- **Role:** Architect
- **Status:** PREPARED. Part 1 (acceptance) and Part 2 (`v*` tag
  protection) are approved by the PO decision of 2026-10-30. Part 3 (server
  inspection) is a plan only and needs separate PO authorization.
- **Inputs:** [release-readiness assessment](2026-10-29-release-readiness-assessment.md)
  (PR #27, merged as `c3dc5da`; `dev` CI 41061369939 green, 773
  passed, 111 skipped, publish skipped), runbook sections H and J, T032/T033
  results.

## PO decisions of 2026-10-30

| # | Decision |
| --- | --- |
| 1 | APPROVED: T032/T033 real-user acceptance on the currently deployed production version |
| 2 | APPROVED: the repository owner configures and verifies `v*` tag protection |
| 3 | REORDER: a strictly read-only server inspection before asking to publish to GHCR for the first time |
| 4 | REQUIRED: a separate timing rehearsal on real production data before the release window (separate authorization, approved short outage); no waiver |
| 5 | Recovery owner: the Product Owner |
| 6 | Recovery decision target: 10 minutes after a failure during or after `migrate apply`; no automatic restore, rollback or forward correction |
| 7 | DEFER T035 until after this release, unless acceptance shows a material safety or reliability issue |

Revised sequence (each step separately authorized): acceptance and
`v*` protection now; A read-only server inspection; B release PR
`dev` → `main`, GHCR publication and verification; C I6 adoption without
replacing containers; D timing rehearsal on a real backup in a
maintenance window; E I7 backup, same-window rehearsal, migration `0001`,
deployment and health checks; F the student and the parent complete a
full revision cycle on production; G I8 runbook and release records.

Not authorized: production migration, backup runs, new maintenance
windows, server configuration changes, GHCR publication, release tags,
deployment, merges into `main`. Scope frozen to the writing revision
milestone.

## Part 1. T032/T033 real-user acceptance

On the version in production (`sha256:5d69fe6c…1137`, legacy writing
schema). Real use only: no synthetic drafts, submissions or evaluations,
no scripts against the database. Record what is observed, including
failures; a step not performed is recorded as "not performed".

### Who and what

- **Student:** own device, house Wi-Fi.
- **Parent:** own computer, SSH access to the server, tutor token from
  the password manager.
- **Recorder:** fills the evidence table below as the steps happen.

### Checklist

| # | Who | Step | Expected |
| --- | --- | --- | --- |
| 1 | Student | Open `http://192.168.50.229:8080`, go to Producción escrita, pick an exercise | Levels with counts; the exercise opens with Spanish instructions; no rubric codes or tutor text visible |
| 2 | Student | Type a short text and wait | "Guardado" appears |
| 3 | Student | Reload the page | The text is still there |
| 4 | Student | Submit | Status "Pendiente de revisión del tutor"; a second click does not create a second submission |
| 5 | Parent | `ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15`, open `http://127.0.0.1:8081/tutor`, enter the token | The submission is in the queue |
| 6 | Parent | Score the rubric, write feedback, mark complete | Saved without error |
| 7 | Student | Reload the exercise and the "Producción escrita" progress tab | Feedback visible; progress shows the evaluated criteria |
| 8 | Student | Close the browser, open it again (or use a second device) | Submission and feedback still shown |
| 9 | Student (optional) | Open `http://192.168.50.229:8081/` from the student device | Refused (tutor not reachable from the Wi-Fi) |

The earlier plan also checked persistence across `docker restart
mentor-pro-app-1`. That is a service restart and is **not** part of this
acceptance (PO: no disruptive restarts without explicit operational
approval). Step 8 checks persistence from the user side; the restart check
is listed as "not performed" unless separately approved.

### Result

**Functional acceptance PASSED (steps 1–8)** on 2026-10-30, on
`sha256:5d69fe6c…1137`. Not performed: step 9 (optional Wi-Fi refusal
of the tutor port) and the `docker restart` persistence check (needs
operational approval). New finding: T046, tutor page has no navigation
back to Mentor Pro (usability, not safety; T035 deferral unchanged).

### Evidence record

Source: the PO's acceptance report of 2026-10-30 (observed by the
student and the parent; the agent did not observe the session). Times
were not reported.

| # | Date and time | Observed | Pass / fail / not performed | Notes |
| --- | --- | --- | --- | --- |
| 1 | 2026-10-30 | Exercise opened and completed | pass | Implied by the submission (PO report) |
| 2 | 2026-10-30 | Autosave | pass | PO report: draft autosave |
| 3 | 2026-10-30 | Text kept after reload | pass | PO report: autosave and reload |
| 4 | 2026-10-30 | Submitted, pending tutor review | pass | PO report; the double-submit check was not reported separately |
| 5 | 2026-10-30 | Tutor reached over the tunnel, submission in queue | pass | Implied by the completed evaluation |
| 6 | 2026-10-30 | Evaluation completed | pass | PO report and screenshot; finding T046 (no way back to Mentor Pro) |
| 7 | 2026-10-30 | Feedback and writing progress visible | pass | PO report |
| 8 | 2026-10-30 | Still shown after reopening the browser | pass | PO report |
| 9 | 2026-10-30 | — | not performed | Optional Wi-Fi refusal check of port 8081 |

Do not record the student's text, the token or screenshots showing
either. Acceptance is complete only when steps 1–8 pass from observation.
A failure opens a focused defect with its evidence; if it is a material
safety or reliability issue, the T035 deferral (PO decision 7) is
reconsidered.

## Part 2. `v*` release tag protection (repository owner)

Goal: once a `v*` tag exists it cannot be moved or deleted, so a
release manifest keeps pointing at one commit and one digest (ADR-033).
Tag creation stays allowed so the release workflow can create the tag.

GitHub web: Settings → Rules → Rulesets → New ruleset → New tag ruleset.

- Name: `release-tags`; Enforcement: Active.
- Bypass list: empty.
- Target tags: Include by pattern `v*`.
- Rules: Restrict updates, Restrict deletions, Block force pushes. Leave
  "Restrict creations" off.

Or with the CLI as the owner:

```bash
gh api -X POST repos/jonnabio/Mentor-Pro/rulesets --input - <<'EOF'
{"name": "release-tags", "target": "tag", "enforcement": "active",
 "bypass_actors": [],
 "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
 "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}]}
EOF
```

Verification (read-only, anyone with access):

```bash
gh api repos/jonnabio/Mentor-Pro/rulesets \
  --jq '.[] | {id, name, target, enforcement}'
gh api repos/jonnabio/Mentor-Pro/rulesets/<id> \
  --jq '{target, enforcement, bypass: .bypass_actors, include: .conditions.ref_name.include, rules: [.rules[].type]}'
```

Expected: `target` `tag`, `enforcement` `active`, `bypass` `[]`,
`include` `["refs/tags/v*"]`, rules `update`, `deletion`,
`non_fast_forward`. No test tag is pushed and `v0.1.0` is not touched
(release tagging is not authorized). The first real release (step B)
confirms the workflow can still create its tag.

## Part 3. Read-only server inspection plan (step A, needs authorization)

Purpose: confirm the assumptions of assessment section 3.3 before asking
to publish to GHCR. Nothing is created, copied, started, stopped or
changed; no `deploy/` files are copied (that is I6); no backup is taken.

### By the agent (SSH as `jonnabio`, no `sudo`)

```bash
ssh jonnabio@100.64.84.15 '
  uname -a; cat /etc/os-release | head -3
  command -v python3 && python3 --version
  ls -la /opt/mentor-pro
  tail -5 /opt/mentor-pro/RELEASES
  sha256sum /opt/mentor-pro/compose.deploy.yml
  df -h / /opt /var /var/lib /var/backups 2>/dev/null
  ls -ld /var/lib/mentor-pro /var/lib/mentor-pro/rehearsal /var/backups/mentor-pro 2>&1
  ls -ld /etc/mentor-pro
'
```

### By the administrator (read-only commands that need `sudo`)

```bash
sudo docker version --format '{{.Server.Version}}'
sudo docker compose version
sudo docker compose -f /opt/mentor-pro/compose.deploy.yml config --format json >/dev/null && echo CONFIG_JSON_OK
sudo docker ps --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
sudo docker inspect mentor-pro-app-1 mentor-pro-tutor-1 --format '{{.Name}} {{.Image}}'
sudo docker volume ls --format '{{.Name}}' | grep mentor
sudo docker network ls --format '{{.Name}}' | grep mentor
sudo docker system df
sudo ls -l /var/backups/mentor-pro
sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/app.env /etc/mentor-pro/tutor.env
```

The last command prints only key names (values masked). No `config`
output with values, token or password is copied into the record.

### Compared against

| Item | Expected (assessment 3.3) |
| --- | --- |
| `python3` | present; version recorded (`deploy/` states no minimum, so a version older than the one CI tests with is flagged for review) |
| Compose plugin | supports `config --format json` and `up --wait` |
| Running images | app and tutor on `sha256:5d69fe6c…1137` |
| Ports | app `127.0.0.1:8080` and the Wi-Fi address; tutor `127.0.0.1:8081` only |
| Env files | `/etc/mentor-pro/app.env` (no tutor key), `tutor.env` |
| Volume and network | names match `deploy/compose.yml` |
| Rehearsal root | absent (I6 creates it) or root-owned `0700` |
| Free space | enough for a dump, a restored rehearsal database and one new image |

Output: an inspection record (observed values, mismatches, each one
classified as blocking or not) for PO review before step B.
