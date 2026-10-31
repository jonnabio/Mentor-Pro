# Step D Plan: Migration Timing Rehearsal for v2026.10.30-1

- **Date:** 2026-10-30
- **Role:** Architect
- **Status:** PROPOSED for PO review. Nothing here is executed or
  authorized.
- **Inputs:** ADR-033 (I5), T045 (`maintenance`, `rehearse`), PO
  decision 4 of 2026-10-30 (separate timing rehearsal on real production
  data, approved short outage, no waiver), recovery policy (PO decisions
  5 and 6), [step C](2026-10-30-step-c-i6-plan.md) (I6 done),
  `deploy/mentorpro`, `deploy/mentorpro_migrate.py`,
  `deploy/compose.rehearsal.yml`

## Purpose

Measure, on a fresh copy of the real production data, how long each
step of the migration window takes, and prove that migration `0001`
succeeds on that data, without changing the production database. The
step E window repeats the rehearsal on its own backup (the tool accepts
only rehearsal evidence from the same window); step D tells us whether
the E window fits and how long to announce.

## What changes in production, and why

| Item | Change | Why |
| --- | --- | --- |
| app, tutor | stopped by `maintenance start` | the tool refuses `rehearse` outside an open window, and the backup must be taken without writers so its data fingerprint is stable |
| app, tutor | **recreated** by `maintenance end` on the same digest `5d69fe6c…1137`, from `deploy/compose.yml` | `maintenance end` runs `compose up -d --no-deps app tutor` with the adopted compose file; its only difference from `compose.deploy.yml` is the health checks (C5 and the comparison below), so compose recreates both containers. New container ids; health status `healthy` from then on |
| postgres | none: keeps running, never restarted (`--no-deps`) | the rehearsal uses its own private PostgreSQL |
| production database | read only (schema query, fingerprint, `pg_dump`) | |
| `release.env` | unchanged | the new image is not deployed |

The recreation at the end is a container replacement, which was not
part of step C. It needs explicit authorization (decision K0-3). The
alternative, restarting the old containers with `compose.deploy.yml`, is
the fallback in R4, not the plan: the tooling's `maintenance end` is the
only command that closes the window record.

Comparison (2026-10-30, read only): `deploy/compose.yml` and the
production `compose.deploy.yml` have the same project (`mentor-pro`),
images, `restart`, env files, environment, ports (`127.0.0.1:8080`,
`192.168.50.229:8080`, tutor `127.0.0.1:8081`), `depends_on`, the
default network and volume `mentor-pro_postgres_data`. The adopted file
adds health checks to app and tutor. Running both health-check commands
inside the current containers succeeded (app exit 0; tutor answered 403,
exit 0).

## Who runs what

- **Administrator** (interactive `sudo`; the agent never sees the
  password): D2 to D5 and `status`. They paste the output.
- **Agent** (`jonnabio`, no `sudo`): snapshots, manifest copy, image
  pre-pull, `smoke`, comparison, evidence.

## Prerequisites

| # | Prerequisite | State |
| --- | --- | --- |
| P1 | I6 adopted: `deploy/` from the tag, `release.env`, `/var/lib/mentor-pro/rehearsal` (root, 0700) | done (step C) |
| P2 | Release manifest `v2026.10.30-1` (sha256 `384d9e3e…54ff`), schema `0001..0001`, digest `7702469e…3538` | downloaded; copied to the server in D1 |
| P3 | Free space: 73 GB on `/` (Docker and the rehearsal folder); the newest dump is about 125 KB | enough |
| P4 | Tooling imports on the server (Python 3.14.4) | checked: `--help` of both modules |
| P5 | The student is told about the outage and is not using Mentor Pro | PO |
| P6 | The administrator and the PO are available for the whole window and 30 minutes after | PO |
| P7 | PO references for `--window` and `--authorization` (no spaces) | PO, at K0 |

## Steps

References used below (example values; the PO supplies them at K0):

```bash
W=stepD-2026-10-31              # --window
A=PO-stepD-<reference>          # --authorization (recorded as given, not verified)
M=/opt/mentor-pro/manifests/v2026.10.30-1.json
```

**D0. Before snapshot (agent, read only).** As C0: containers, ids,
images, start times, restart counts, `compose.deploy.yml` and `RELEASES`
checksums, `/opt/mentor-pro` listing; plus `mentorpro smoke`.

**D1. Preparation (agent, before the window).** Needs K0-2.

```bash
# manifest from the GitHub Release, checksum compared before and after
gh release download v2026.10.30-1 -R jonnabio/Mentor-Pro -p release-manifest.json
sha256sum release-manifest.json          # 384d9e3e3e3ab007e1cd6d4c769ec3fbb85310b2c3840f74ebe7a58d1ffb54ff
ssh jonnabio@100.64.84.15 'mkdir -p /opt/mentor-pro/manifests && test ! -e /opt/mentor-pro/manifests/v2026.10.30-1.json'
scp release-manifest.json jonnabio@100.64.84.15:/opt/mentor-pro/manifests/v2026.10.30-1.json
ssh jonnabio@100.64.84.15 'sha256sum /opt/mentor-pro/manifests/v2026.10.30-1.json'
# pre-pull, so the download is not inside the outage; adds an image, deploys nothing
ssh jonnabio@100.64.84.15 'docker pull -q ghcr.io/jonnabio/mentor-pro@sha256:7702469e442596d56b1425bfc5a0d189bcc1f21a2fd3972d47f079b932423538 && docker image inspect -f "{{json .RepoDigests}}" ghcr.io/jonnabio/mentor-pro@sha256:7702469e442596d56b1425bfc5a0d189bcc1f21a2fd3972d47f079b932423538'
```

**K1. PO go/no-go** for the window, with D0 and D1 results.

**D2. Start the window (administrator). Downtime begins.**

```bash
date -u +%FT%TZ
sudo /opt/mentor-pro/deploy/mentorpro maintenance start --window "$W" --authorization "$A"; echo "exit $?"
```

Expected: `MAINTENANCE STARTED <time>: app and tutor stopped, PostgreSQL
running; …`, exit 0. The tool checks the schema is `legacy`, records the
window (`/opt/mentor-pro/state/maintenance.json`) and a `RELEASES` line.

**D3. Fresh, verified backup (administrator).**

```bash
date -u +%FT%TZ
sudo /opt/mentor-pro/deploy/mentorpro backup; echo "exit $?"
date -u +%FT%TZ
```

Expected: `dump: <n> tables, <n> rows, <n> bytes` and `BACKUP OK
/var/backups/mentor-pro/mentor_pro_<stamp>.dump sha256:<…>`, exit 0. The
tool fingerprints every table before and after `pg_dump -Fc` (counts and
md5 digests only), restores the dump into a disposable, unpublished
PostgreSQL container, compares the fingerprint, removes the container and
writes `<dump>.verify`. The dump is never overwritten or deleted.

**D4. Rehearsal (administrator).**

```bash
D=/var/backups/mentor-pro/mentor_pro_<stamp>.dump    # the dump from D3
sudo /opt/mentor-pro/deploy/mentorpro rehearse "$M" "$D" --window "$W" --authorization "$A"; echo "exit $?"
```

Before it starts anything, the tool:

- verifies the manifest, the registry digest, the tag mapping and the
  image labels;
- checks the backup record (BACKUP OK, at most six hours old, checksum);
- checks the free space.

Then it:

1. creates the project `mentorpro-rehearsal-<id>` from
   `compose.rehearsal.yml`, on an internal network with no published
   ports, its own volume and generated credentials;
2. copies the dump into the rehearsal folder (mode 0600) and checks the
   copy's checksum;
3. restores the copy and compares its fingerprint with the backup record;
4. classifies the schema (`legacy`);
5. runs `app.writing.migrate apply --dry-run`, then `apply`;
6. verifies schema `current 0001`, the counts and that only the expected
   tables changed;
7. starts app and tutor and runs smoke tests from a checker container on
   the internal network;
8. removes every container, the volume, the network and the dump copy,
   and verifies the removal.

Expected:

- `durations (s): isolation check …, copy …, start postgres …, restore …,
  schema before …, dry run …, apply …, verify …, start app and tutor …,
  smoke …, cleanup …, total …`;
- `cleanup verified`;
- `REHEARSAL OK: v2026.10.30-1 on <dump>`, exit 0.

The record goes to
`/opt/mentor-pro/state/rehearsal/<digest>.<dump sha>.json`. It holds
counts, durations and references only, never rows or credentials.

**D5. End the window (administrator). Downtime ends.**

```bash
sudo /opt/mentor-pro/deploy/mentorpro maintenance end --window "$W" --authorization "$A"; echo "exit $?"
date -u +%FT%TZ
```

The tool refuses unless the schema and `release.env` are as at D2. It
recreates app and tutor on `5d69fe6c…1137`, waits up to 180 s for both
to be `healthy`, then runs `smoke`. Expected: smoke lines, then
`MAINTENANCE ENDED: previous release … running and healthy, smoke passed;
schema unchanged (legacy); downtime <n> min`, exit 0.

**D6. Status and smoke.**

```bash
sudo /opt/mentor-pro/deploy/mentorpro status; echo "exit $?"     # administrator
sudo cat /opt/mentor-pro/state/rehearsal/*.json                  # administrator: counts and durations only
/opt/mentor-pro/deploy/mentorpro smoke; echo "exit $?"           # agent
```

Expected `status`: app and tutor `OK … running healthy` (new); postgres
`OK`; schema `UNKNOWN` (the pre-T036 image does not report it); student
and tutor 200; `RELEASES` shows the new `maintenance-start`, `rehearse`
and `maintenance-end` lines; `dumps 3`; **`STATUS INCOMPLETE (1 item(s)
unknown)`**, exit 3. Expected `smoke`: `SMOKE PASS (9/9)`.

**D7. After snapshot (agent).** Compare with D0:

- postgres: the same container id and start time, with 0 restarts;
- app and tutor: new container ids, the same image digest, `restart`
  `unless-stopped`, and the same ports;
- the `compose.deploy.yml` checksum is unchanged;
- `release.env` is unchanged.

**D8. Evidence (agent).** Record the following in the next meaningful
ACE update:

- the timings;
- the result lines;
- the counts (no rows);
- the RELEASES lines;
- the dump name and checksum;
- the deviations.

## Timing measurements

All objective, recorded by the tools or by `date -u`:

| Measure | Source |
| --- | --- |
| Outage start, end, minutes | `RELEASES` `maintenance-start` time; `maintenance-end` `downtime_minutes` |
| Backup duration | `date -u` before and after D3 |
| Rehearsal per step and total (s) | `durations (s)` line and the rehearsal record |
| Restart to healthy and smoke | time between D5's start and its `MAINTENANCE ENDED` |

Estimate (database about 125 KB compressed; the image is pulled in D1):

| Phase | Expected |
| --- | --- |
| D2 stop app and tutor | under 30 s |
| D3 backup with restore check | 1 to 2 min |
| D4 rehearsal | 2 to 5 min |
| D5 recreate, healthy (first check after 30 s), smoke | 1 to 2 min |
| Commands, reading and pasting between steps | 5 to 10 min |
| **Outage** | **about 10 to 20 min; announce 30 min** |

Time limits within the window:

- If D4 has not finished 30 minutes after D2, the administrator presses
  Ctrl-C. The tool then runs its cleanup and records `REHEARSAL FAILED
  interrupted`. Then they go to D5.
- The ADR-033 limit of 60 minutes applies to E. In step D it is the
  absolute ceiling.

For step E, the projection is: elapsed time plus 2 × (dry run + apply +
verify + start app and tutor + smoke). The E window also needs its own
`maintenance start` and backup.

## Student data and credentials

- The production dump is written only to `/var/backups/mentor-pro`
  (root, 0700; file 0600). The rehearsal copy lives in
  `/var/lib/mentor-pro/rehearsal/<project>` (root, 0700; file 0600) and
  is deleted afterwards, and the deletion is verified. Backups are never
  deleted.
- The rehearsal never reads `/etc/mentor-pro/*.env`. Its database
  password and tutor token are generated randomly, used only inside the
  rehearsal folder, and deleted with it. The rehearsal tutor allows no
  client (`192.0.2.1`).
- The rehearsal has no published port. Its network is
  `internal: true`, with no route to the host, the production network
  or the internet. The tool checks this before and after start and stops
  on any difference.
- Output, records and `RELEASES` hold only counts, md5 digests, checksums,
  names and durations. No row, essay text, name or credential is
  printed, pasted or committed. The agent never reads the dump.
- The production database is only read. Nothing is written to it; no
  synthetic submissions or evaluations are created.

## Isolated rehearsal database: creation and removal

- **Created** by `rehearse` as the service `postgres` of the project
  `mentorpro-rehearsal-<UTC stamp>-<pid>` (image `postgres:17.6`, its own
  volume, internal network), and restored from the dump copy.
- **Removed** by `rehearse` in a `finally` block, on success, failure and
  Ctrl-C:
  - the project's containers, volume and network, by project label
    (never `down -v` on any other project);
  - the dump copy;
  - the working folder, but only if it carries the rehearsal marker.

  The tool then checks that no resource of the project remains (`cleanup
  verified`).
- **Manual check** (administrator, read only), if cleanup reports
  anything else:

  ```bash
  sudo docker ps -a --filter label=com.docker.compose.project --format '{{.Names}} {{.Label "com.docker.compose.project"}}' | grep mentorpro-rehearsal-
  sudo docker volume ls --filter name=mentorpro-rehearsal-
  sudo docker network ls --filter name=mentorpro-rehearsal-
  sudo ls -la /var/lib/mentor-pro/rehearsal
  ```

## How `0001` is tested without changing production

The migration runs only inside the rehearsal project
(`docker compose run --rm --no-deps app python -m app.writing.migrate
apply`) against the rehearsal PostgreSQL. Its `DATABASE_URL` names the
service `postgres` on the internal network, and production PostgreSQL is
not reachable from it. `migrate` (the production command) is not run in
step D. After D5 the tool confirms the live schema is still `legacy`.

## Success criteria

1. `MAINTENANCE STARTED`, `BACKUP OK`, `REHEARSAL OK` with `cleanup
   verified`, and `MAINTENANCE ENDED`, each with exit 0.
2. In the rehearsal: the schema goes from `legacy` to `current 0001`;
   drafts, submissions, evaluations and scores keep their counts; every
   attempt is attempt 1; nothing outside the scope of `0001` changes.
3. After the rehearsal: the live schema is still `legacy`, postgres has
   not been restarted, and `release.env` is unchanged.
4. Outage at most 30 minutes; every rehearsal step has a finite duration.
5. `status` shows exactly 1 unknown (schema); `smoke` 9/9.

## Stop conditions

Stop and report; the agent does not recover anything.

- D0/D1:
  - production differs from the step C result;
  - the manifest checksum or the pulled digest differs;
  - `smoke` fails.
- D2: `MAINTENANCE START FAILED` or `REFUSED`. Go to R1.
- D3: `BACKUP FAILED`. Do not rehearse; go to K2 and then D5.
- D4: `REHEARSAL REFUSED` or `FAILED`; cleanup not `verified`; any
  isolation message. Go to R3, then D5.
- D5: `MAINTENANCE END FAILED` or `REFUSED`. Go to R4.
- D6/D7:
  - more than 1 unknown, or any `PROBLEM`, `UNHEALTHY` or `FAIL`;
  - any change to postgres, `release.env` or `compose.deploy.yml`.
- Any time: an unexpected message, the outage reaching 30 minutes, or
  a student request to use the app.

## Recovery

The policy is unchanged: no automatic restore, rollback or forward
correction. The PO owns recovery, with a 10-minute decision target.

Step D never writes to the production database, so no database
restoration can be needed. Every recovery below restores the application
service only.

| # | Situation | State | Procedure (each needs the PO's go) |
| --- | --- | --- | --- |
| R1 | `maintenance start` failed | window record open; app/tutor maybe partly stopped | administrator: `sudo .../mentorpro maintenance end --window "$W" --authorization "$A"` (restarts them, checks health, smoke) |
| R2 | backup failed | app/tutor stopped; nothing else changed | do not retry without the PO; D5 |
| R3 | rehearsal failed or interrupted | cleanup ran; production untouched | if cleanup is not `verified`, the manual check above; never remove a non-rehearsal resource; D5 |
| R4 | `maintenance end` failed (not healthy in 180 s, or smoke failed) | window stays open; app/tutor may be down | (a) administrator reads `sudo docker ps -a` and `sudo docker logs --tail 50 mentor-pro-app-1` (and tutor) and reports, without pasting secrets; (b) PO decides: retry `maintenance end` once, or (c) fall back to the old configuration: `sudo docker compose -p mentor-pro -f /opt/mentor-pro/compose.deploy.yml up -d --no-deps app tutor`, then agent `smoke`. After (c) the window record stays open; it is closed later with `maintenance end` at a time the PO approves |
| R5 | postgres stopped, or Docker or the server fails | out of plan | stop; PO and administrator decide; no restore of the database without a separate decision (it was not changed) |

## PO checkpoints and authorizations

| Checkpoint | When | Decision |
| --- | --- | --- |
| K0 | before anything | 1. Authorize step D as written. 2. Authorize D1 (manifest copy to `/opt/mentor-pro/manifests/`, pre-pull of `7702469e…3538` without deploying it). 3. Authorize the recreation of app and tutor on the same digest at D5 (health checks adopted). 4. Authorize the outage and its window (date, time, 30 minutes announced). 5. Window and authorization references. 6. Authorize a new production backup (D3) and the rehearsal on that real data. |
| K1 | after D0 and D1 | go/no-go for D2 |
| K2 | only on a failure in D2 to D4 | which recovery (R1 to R3); D5 |
| K3 | only on a failure in D5 | R4 option (b) or (c); 10-minute target |
| K4 | after D8 | accept step D; durations as the basis for the E window |

On the expected path (every step gives exactly the result listed), the
administrator continues from D2 to D5 without waiting for the PO between
steps, which keeps the outage short. Any other result stops at K2 or K3.

## Filesystem and service changes (complete list)

| Where | Change |
| --- | --- |
| `/opt/mentor-pro/manifests/v2026.10.30-1.json` | new (agent) |
| Docker images | `ghcr.io/jonnabio/mentor-pro@sha256:7702469e…3538` pulled (about 250 MB), not run except inside the rehearsal |
| `/opt/mentor-pro/state/` | new (root): `deploy.lock`, `history/maintenance.<stamp>.json`, `rehearsal/<digest>.<dump sha>.json` |
| `/opt/mentor-pro/RELEASES` | three new lines: `maintenance-start`, `rehearse`, `maintenance-end` |
| `/var/backups/mentor-pro/` | new dump and its `.verify` record (kept; never deleted) |
| `/var/lib/mentor-pro/rehearsal/` | empty again after the rehearsal |
| app, tutor | recreated on the same digest with health checks (new container ids) |

Not changed:

- the production database, postgres, the volume and the network;
- `release.env`, `compose.deploy.yml` and `/etc/mentor-pro`;
- no migration on production; the new image is not deployed.

## Risks

| Risk | Mitigation |
| --- | --- |
| First production use of `deploy/compose.yml`; the recreated app or tutor does not become healthy | compose files compared (only health checks differ); health commands tested inside the current containers; R4 fallback to `compose.deploy.yml` |
| The tutor health check depends on `MENTOR_PRO_TUTOR_ALLOWED_HOSTS` excluding 127.0.0.1 | checked now: the running tutor answers 403 from inside the container |
| First real run of `maintenance`, `backup` and `rehearse` on Python 3.14 (CI runs 3.12) | both modules import on the server; any refusal before D4's start changes nothing |
| The rehearsal leaves containers or volumes behind | cleanup verified by the tool; manual read-only check; resources are internal and unpublished |
| The student uses the app during the outage | announce; choose a time the student does not study; stop if asked |
| The image pull in the window lengthens the outage | pre-pull in D1 |
| Monitoring on the server (Uptime Kuma) reports the outage | expected; note the window |
| A failure leaves the window record open | R1/R4; `maintenance start` refuses a second window until it is closed, so nothing runs twice |
| References are taken as approval | they are recorded as given (`authorization_verified=no`); approval is this document and the PO's message |

## Recommended execution window

Saturday 2026-10-31, 10:00–10:45 local time, announced as 30 minutes.
This assumes the student does not study on Saturday morning; the PO
confirms. The PO and the
administrator should both be present, plus 30 minutes afterwards in case
recovery is needed. D0 and D1 run the evening before, after K0.

## Decisions requested

1. K0 items 1 to 6.
2. Confirm the administrator continues D2 to D5 without pausing when
   every result is as expected.
3. Confirm the window, or name another.
