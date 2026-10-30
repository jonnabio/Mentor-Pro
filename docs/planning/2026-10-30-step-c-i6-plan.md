# Step C Plan: I6 Adoption of the Deployment Tooling

- **Date:** 2026-10-30
- **Role:** Architect
- **Status:** PROPOSED for PO authorization. Nothing here is executed.
- **Inputs:** ADR-033 (I6: "check out `deploy/`, create `release.env`
  for the running digest, `status` and `smoke` only"),
  [server inspection](../progress/2026-10-30-server-inspection.md),
  release `v2026.10.30-1`, `deploy/mentorpro`,
  `deploy/mentorpro_deploy.py`

## Prerequisites A1 and A2: INCONCLUSIVE

Both folders are `root:root 0700`. As `jonnabio` without `sudo` (the
agent's standing restriction) every listing answers `Permission
denied`. Nothing was bypassed (no `sudo`, no Docker mounts).

| Check | Result | Needed |
| --- | --- | --- |
| A1 backup folder | INCONCLUSIVE: `/var/backups/mentor-pro` `root:root 700`, contents not readable | administrator: `sudo ls -l /var/backups/mentor-pro` |
| A2 env key names | INCONCLUSIVE: `/etc/mentor-pro` `root:root 700`, not readable | the key-name-only check below, with `sudo` |

A1 passes when the folder holds the 2026-10-28 dump (about 127,791
bytes). Both run as step C1 below.

### A2 check (PO amendment 2026-10-30)

`awk` reads the files as root; values stay in memory and are never
printed. Blank lines and `#` comments are skipped; every other line must
be `KEY=…`. A malformed line is reported by file and line number only.
The program is sent on standard input; nothing is written on the server.

```awk
{ n = split(FILENAME, p, "/"); f = p[n] }
/^[ \t]*$/ || /^[ \t]*#/ { next }
/^[A-Za-z_][A-Za-z0-9_]*=/ {
  k = substr($0, 1, index($0, "=") - 1)
  seen[f, k]++; keys[f] = keys[f] " " k
  next
}
{ print "A2 MALFORMED " f " line " FNR " (content not shown)"; bad++ }
END {
  for (x in seen) { split(x, q, SUBSEP)
    if (seen[x] > 1) { print "A2 DUPLICATE " q[1] " " q[2]; bad++ }
    if (q[1] == "app.env" && q[2] ~ /^MENTOR_PRO_TUTOR_/) { print "A2 TUTOR KEY IN app.env: " q[2]; bad++ }
    if (q[1] == "tutor.env" && q[2] != "MENTOR_PRO_TUTOR_TOKEN" && q[2] != "MENTOR_PRO_TUTOR_ALLOWED_HOSTS") { print "A2 UNEXPECTED KEY in tutor.env: " q[2]; bad++ }
  }
  if (!seen["tutor.env", "MENTOR_PRO_TUTOR_TOKEN"]) { print "A2 MISSING tutor.env MENTOR_PRO_TUTOR_TOKEN"; bad++ }
  if (!seen["tutor.env", "MENTOR_PRO_TUTOR_ALLOWED_HOSTS"]) { print "A2 MISSING tutor.env MENTOR_PRO_TUTOR_ALLOWED_HOSTS"; bad++ }
  if (!("app.env" in keys)) { print "A2 MISSING app.env keys"; bad++ }
  for (f in keys) print "A2 KEYS " f ":" keys[f]
  print (bad ? "A2 FAIL (" bad " issue(s))" : "A2 PASS")
  exit (bad ? 1 : 0)
}
```

```bash
ssh jonnabio@100.64.84.15 'sudo -n awk -f /dev/stdin /etc/mentor-pro/app.env /etc/mentor-pro/tutor.env /etc/mentor-pro/postgres.env' < a2.awk
```

A2 passes (`A2 PASS`, exit 0) when every line is well formed, no key
repeats, `app.env` holds no `MENTOR_PRO_TUTOR_*` key, and `tutor.env`
holds exactly `MENTOR_PRO_TUTOR_TOKEN` and
`MENTOR_PRO_TUTOR_ALLOWED_HOSTS`. Tested locally on sample files with
marker values: no value appeared in the output in either the passing or
the failing case.

## Deviation D1: `adopt-legacy` cannot run in I6 (decision needed)

`adopt-legacy` refuses unless app and tutor report Docker health
`healthy` (`running_healthy` in `deploy/mentorpro_deploy.py`). The
running containers come from `/opt/mentor-pro/compose.deploy.yml`, which
has no health checks; observed `health=[]` for both on 2026-10-30.
Adding health checks needs the containers recreated, which I6 must not
do.

Recommendation: **omit `adopt-legacy`.** Its only use is an application
rollback to the pre-T036 image; after migration `0001` that rollback is
refused by design (T044), and recovery after `apply` is the G3 database
restore. `migrate` deploys with `propose_rollback=False` and needs no
legacy record. The alternative (recreate app and tutor on the same
digest with `deploy/compose.yml` to gain health checks, a short outage)
is not proposed.

## Who runs what

- **Agent** (`jonnabio`, no `sudo`): snapshots, copy `deploy/`, write
  `release.env` (`/opt/mentor-pro` is owned by `jonnabio`), `smoke`.
- **Administrator** (`sudo`): A1, A2, the rehearsal folder,
  `compose config`, `status` (reads the backup folder).

## Steps

Release references: tag `v2026.10.30-1`; running digest
`sha256:5d69fe6c2560626afe78a61b04e64e5c81b59eff4b2a73f6bd0327756a6e1137`.

**C0. Snapshot (agent, read-only).** Containers, images, start times,
`compose.deploy.yml` checksum, last `RELEASES` line; kept for C7.

**C1. A1 and A2 (administrator).** Commands above. Stop on a tutor key in
`app.env` or no dump.

**C2. Copy the tooling (agent),** from the release tag, not a working
tree:

```bash
git archive v2026.10.30-1 deploy | ssh jonnabio@100.64.84.15 'tar -x -C /opt/mentor-pro'
git ls-tree -r v2026.10.30-1 deploy        # expected blob ids and modes
ssh jonnabio@100.64.84.15 'cd /opt/mentor-pro && ls -l deploy && for f in deploy/*; do echo "$(git hash-object "$f") $f"; done'
```

Creates `/opt/mentor-pro/deploy/` (5 files, `mentorpro` executable).
Stop if any blob id differs.

**C3. `release.env` (agent).** No secret. Refuses if the file exists.

```bash
ssh jonnabio@100.64.84.15 'set -e; umask 022; test ! -e /opt/mentor-pro/release.env
  echo "MENTOR_PRO_IMAGE=ghcr.io/jonnabio/mentor-pro@sha256:5d69fe6c2560626afe78a61b04e64e5c81b59eff4b2a73f6bd0327756a6e1137" > /opt/mentor-pro/release.env
  cat /opt/mentor-pro/release.env'
```

**C4. Rehearsal folder (administrator).** Empty; first used in step D.

```bash
sudo install -d -m 755 -o root -g root /var/lib/mentor-pro
sudo install -d -m 700 -o root -g root /var/lib/mentor-pro/rehearsal
```

**C5. Compose check (administrator).** Validates only; prints no values.

```bash
C="docker compose -p mentor-pro -f /opt/mentor-pro/deploy/compose.yml --env-file /opt/mentor-pro/release.env"
sudo $C config --quiet && echo CONFIG OK
sudo $C config --services          # app, tutor, postgres
sudo $C config --images            # the running digest twice, postgres:17.6
```

Never `up`, `pull`, `restart`, `stop` or `down`. Stop if config fails or
an image differs.

**C6. `status` and `smoke`.**

```bash
sudo /opt/mentor-pro/deploy/mentorpro status; echo "exit $?"   # administrator
/opt/mentor-pro/deploy/mentorpro smoke; echo "exit $?"         # agent
```

Expected `status`: `release.env` shows the running digest; postgres
`OK`; app and tutor `UNKNOWN … (no health check)`; schema `UNKNOWN` (the
pre-T036 image has no migrate module); student `/` 200; tutor `/tutor`
200; backups readable; **`STATUS INCOMPLETE (3 item(s) unknown)`, exit
3**. Expected `smoke`: all `PASS`, including the tutor port refused on
the Wi-Fi address; exit 0. Stop on any `PROBLEM`, `STATUS UNHEALTHY` or
`FAIL`.

**C7. After snapshot (agent).** Compare with C0: same containers,
digest, start times, compose checksum and `RELEASES` (without
`adopt-legacy`, I6 writes no `RELEASES` line).

## Filesystem changes (complete list)

| Path | Change |
| --- | --- |
| `/opt/mentor-pro/deploy/` | new: 5 files from `v2026.10.30-1` |
| `/opt/mentor-pro/release.env` | new: one line, the running digest |
| `/var/lib/mentor-pro/` (`755`) and `/var/lib/mentor-pro/rehearsal/` (`700`) | new, empty, root |

Nothing else: no container, image, volume, network, env file, backup,
`compose.deploy.yml` or `RELEASES` change. Undo: remove these paths; no
service impact.

## Stop conditions (stop and report; no recovery by the agent)

- A tutor key in `app.env`, or no dump in the backup folder.
- A copied file differs from the tag, or `release.env` already exists.
- `compose config` fails, or the services or images differ from the
  above.
- `status` reports any `PROBLEM`, or unknowns other than the three
  expected; `smoke` reports any `FAIL`.
- Any container start time or image changes between C0 and C7.

## Decisions requested

1. Authorize step C (C0–C7) as above.
2. Accept D1: omit `adopt-legacy` (recommended).
3. Confirm the administrator runs C1, C4, C5 and the `status` part of
   C6, or explicitly authorize the agent to run those commands with
   `sudo`.
