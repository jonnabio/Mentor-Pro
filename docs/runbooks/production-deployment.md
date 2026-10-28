# Runbook: Production Deployment on macedonianserver

## Overview

**Decision:** [ADR-030](../adr/ADR-030-production-provisioning-and-deployment.md)
**Server:** macedonianserver (`100.64.84.15`, Tailscale), `/opt/mentor-pro`
**Access:** SSH key login as `jonnabio`; compose commands with `sudo`

Never paste passwords, `DATABASE_URL`, API keys or `docker compose config`
output into logs, commits or chat. Use the redaction commands below.

Set these shell variables first, in every server session (`DIGEST` is the
digest being deployed):

```bash
set -o pipefail
cd /opt/mentor-pro
COMPOSE="sudo docker compose -f /opt/mentor-pro/compose.deploy.yml"
WB=PNE-Tracker-2026-workbook.xlsx
WB_SHA=cce57db40afacdb2f6d2492c39ba9df6c1bc398941c1c7fb9cff8ec28bcc19d3
DIGEST=sha256:...   # e.g. the digest published by the main run
```

---

## A. Pre-flight (read-only)

```bash
cd /opt/mentor-pro
docker ps --format '{{.Names}} {{.ID}} {{.Status}}' | tee /tmp/pre-containers.txt
systemctl is-active smbd nmbd | tee /tmp/pre-samba.txt
$COMPOSE exec -T postgres \
  psql -U mentor_pro_admin -d mentor_pro -c '\dn' \
  -c "SELECT count(*) AS curriculum_tables FROM information_schema.tables WHERE table_schema='curriculum'"
```

Record the schemas that already exist. If `curriculum` already has a
`source_document` row for `PNE2026-SUM-v1.0`, the import below must report
`unchanged`; anything else is a stop.

## B. Backup

```bash
sudo install -d -m 700 -o root -g root /var/backups/mentor-pro
DUMP=/var/backups/mentor-pro/mentor_pro_$(date +%F_%H%M%S).dump
$COMPOSE exec -T postgres pg_dump -U mentor_pro_admin -d mentor_pro -Fc </dev/null \
  | sudo sh -c "umask 077 && cat > $DUMP" \
  && sudo test -s "$DUMP" \
  && sudo chmod 600 "$DUMP" \
  && sudo cat "$DUMP" | $COMPOSE exec -T postgres pg_restore --list >/dev/null \
  && echo "BACKUP OK $DUMP" || echo "BACKUP FAILED - STOP"
sudo ls -l "$DUMP"
```

**Gate:** continue only after `BACKUP OK`. With `pipefail`, a failed
`pg_dump` fails the pipeline; the file must be non-empty, `0600`, and
readable by `pg_restore --list`.

## C. Secrets (once)

Move the values already in `compose.deploy.yml` (do not change them).
First look at what exists; never overwrite a file without reading it:

```bash
sudo ls -la /etc/mentor-pro/ 2>/dev/null || echo "no /etc/mentor-pro yet"
for f in /etc/mentor-pro/app.env /etc/mentor-pro/postgres.env; do
  sudo test -f "$f" && { echo "$f exists, keys:"; sudo sed -E 's/=.*/=<set>/' "$f"; }
done
ls -la /opt/mentor-pro/
```

Then:

```bash
sudo install -d -m 700 -o root -g root /etc/mentor-pro
sudo cp -n compose.deploy.yml compose.deploy.yml.pre-adr030   # -n: never overwrite
sudoedit /etc/mentor-pro/postgres.env   # add POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
sudoedit /etc/mentor-pro/app.env        # add/keep DATABASE_URL, OPENROUTER_API_KEY, ...
for f in /etc/mentor-pro/*.env compose.deploy.yml.pre-adr030 compose.deploy.yml.bak; do
  sudo test -f "$f" && sudo chown root:root "$f" && sudo chmod 600 "$f"
done
```

`sudoedit` keeps existing content; add only the missing keys. The
`.pre-adr030` and `.bak` copies contain the old inline secrets: root-only
`0600`, deleted after the deployment is verified.

After editing the compose file (below), prove the credentials still work
before going further:

```bash
$COMPOSE run --rm --no-deps app python -c \
  "import psycopg; from curriculum import db; psycopg.connect(db.database_url()).close(); print('DB OK')"
```

**Gate:** continue only after `DB OK`. Otherwise restore
`compose.deploy.yml.pre-adr030` and stop.

Target `compose.deploy.yml` (no secret values, no `${…}`):

```yaml
name: mentor-pro

services:
  app:
    image: ghcr.io/jonnabio/mentor-pro@sha256:<digest>  # literal value, no ${}
    restart: unless-stopped
    env_file:
      - /etc/mentor-pro/app.env
    environment:
      CURRICULUM_BASELINE: PNE2026-SUM-v1.0
      MENTOR_PRO_DEV_ENDPOINTS: "false"
    ports:
      - "127.0.0.1:8080:8000"
      - "192.168.50.229:8080:8000"   # house Wi-Fi only (ADR-030 section 10)
    depends_on:
      postgres:
        condition: service_healthy

  postgres:
    image: postgres:17.6
    restart: unless-stopped
    env_file:
      - /etc/mentor-pro/postgres.env
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mentor_pro_admin -d mentor_pro"]
      interval: 10s
      timeout: 5s
      retries: 10

volumes:
  postgres_data:
```

Check that no secret remains in the file (expect no output):

```bash
grep -inE 'password|postgres(ql)?://|api_key|token' compose.deploy.yml
```

Do not recreate `postgres` for this change unless needed; if Compose
recreates it, the volume and password are kept (the password is read only
when a volume is first initialized).

## D. Workbook transfer and checksum

On Windows (PowerShell), from the folder holding the workbook:

```powershell
ssh jonnabio@100.64.84.15 "install -d -m 700 /opt/mentor-pro/baseline"
scp .\PNE-Tracker-2026-workbook.xlsx jonnabio@100.64.84.15:/opt/mentor-pro/baseline/
```

On the server:

```bash
chmod 600 "/opt/mentor-pro/baseline/$WB"
echo "$WB_SHA  /opt/mentor-pro/baseline/$WB" | sha256sum -c -
```

**Stop** unless the output is `…: OK`. Delete the copied file, keep the
database as it is, and check the source workbook on Windows.

## E. Import (one-time, idempotent)

```bash
$COMPOSE pull app
run_import() {
  $COMPOSE run --rm --no-deps -v /opt/mentor-pro/baseline:/baseline:ro app \
    python -m curriculum.importer --workbook "/baseline/$WB" --version PNE2026-SUM-v1.0
}
run_import    # expect "status": "imported" (or "unchanged" if already present)
run_import    # expect "status": "unchanged"
```

`"status": "failed"` stops the deployment; the importer wrote nothing.
Keep the JSON output (it holds counts and checksums, no secrets).

## F. Start and verify

```bash
docker rm -f mentor-pro-preview 2>/dev/null
$COMPOSE up -d app
for p in / /api/subjects /api/dashboard /api/writing/levels; do
  printf '%s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8080$p"
done
docker inspect mentor-pro-app-1 --format '{{.Config.Image}}'   # must show @$DIGEST
$COMPOSE restart app            # then repeat the curl loop
$COMPOSE up -d --force-recreate app  # repeat loop + counts
```

Curriculum counts (before and after recreation must match):

```bash
$COMPOSE exec -T postgres psql -U mentor_pro_admin -d mentor_pro \
  -c "SELECT (SELECT count(*) FROM curriculum.assertion) AS assertions, (SELECT count(*) FROM curriculum.evidence) AS evidences"
```

Other services unchanged:

```bash
docker ps --format '{{.Names}} {{.ID}} {{.Status}}' | grep -v '^mentor-pro' ; grep -v '^mentor-pro' /tmp/pre-containers.txt
systemctl is-active smbd nmbd
```

Browser: any device on the house Wi-Fi opens `http://192.168.50.229:8080/`
or `http://macedonianserver.local:8080/` (ADR-030 section 10). The SSH
tunnel (`ssh -N -L 8080:127.0.0.1:8080 jonnabio@100.64.84.15`, then
`http://127.0.0.1:8080/`) remains for administrators away from home.

Wi-Fi publication (once), then confirm the bindings:

```bash
echo 'net.ipv4.ip_nonlocal_bind=1' | sudo tee /etc/sysctl.d/99-mentor-pro.conf
sudo sysctl --system | grep ip_nonlocal_bind
$COMPOSE up -d app
docker port mentor-pro-app-1   # 127.0.0.1:8080 and 192.168.50.229:8080 only
```

After a server reboot, check `curl -I http://192.168.50.229:8080/` from
another Wi-Fi device.

Record the release:

```bash
echo "$(date -Is) $DIGEST <git-commit> $(whoami) <result>" >> /opt/mentor-pro/RELEASES
```

## G. Rollback

```bash
PREVIOUS_DIGEST=sha256:...   # from /opt/mentor-pro/RELEASES
sudo sed -i "s#mentor-pro@sha256:[0-9a-f]*#mentor-pro@$PREVIOUS_DIGEST#" compose.deploy.yml
$COMPOSE up -d app
```

**Limit:** this rolls back the application only. It is safe only when the
earlier image is compatible with the current database (true while schema
changes are additive). Database rollback is a separate, deliberate
operation: follow the ADR of the release that changed the schema, or
restore the dump from section B with `pg_restore` into a new database after
a review. Never restore over the live database as part of an app rollback.

## H. Writing exercise bank (administrative, repeatable)

Provisions the approved (eligible, ADR-027) Producción escrita exercises
from the local database (ADR-030 section 7) with `python -m app.writing.bank`
(T032). Never run at startup or from a student page. The bundle carries
exercises, editorial revisions, tutor-only references, the accepted
generation attempt, eligibility history, independent validations and the
usage rows that name generator and reviewer (RCA-004). Quarantined
exercises, drafts, submissions and evaluations are never exported.

Requires an image that contains `app/writing/bank.py` (T032 or later).

On Windows (local database):

```powershell
.venv/Scripts/python.exe -m app.writing.bank inventory
.venv/Scripts/python.exe -m app.writing.bank export --out writing-bank.json
scp writing-bank.json jonnabio@100.64.84.15:/tmp/writing-bank.json
```

On the server (after section B gives `BACKUP OK`):

```bash
# owner uid 1000 = the container user `mentor` (like the workbook); root-owned fails with Permission denied
sudo install -m 600 -o 1000 -g 1000 /tmp/writing-bank.json /opt/mentor-pro/baseline/writing-bank.json
rm /tmp/writing-bank.json
bank() {
  $COMPOSE run --rm --no-deps -T -v /opt/mentor-pro/baseline:/baseline:ro app     python -m app.writing.bank "$@" </dev/null
}
bank inventory                                    # before: expect 0 eligible
bank import /baseline/writing-bank.json --dry-run # expect imported 11, rejected []
bank import /baseline/writing-bank.json           # expect imported 11
bank import /baseline/writing-bank.json           # expect imported [], unchanged 11
bank inventory                                    # L1 3, L2 3, L3 3, L4 2; quarantined []
curl -s http://127.0.0.1:8080/api/writing/levels | grep -o '"exercise_count":[0-9]*'
```

**Gates:** stop on any `rejected` entry (exit code 1) or
`student_records_untouched: false`. The import is one transaction: a
failure writes nothing. Existing exercises are never overwritten; a
different record with the same id is rejected. Keep the printed report
(no secrets, no student data).

**Rollback:** imported exercises have no student work at first. Before any
student has used them, restore is not needed; afterwards they must stay
(submissions reference them). Never delete exercises by hand; restore the
section B dump into a new database for review if the import must be
undone.

## I. Diagnostics without credentials

```bash
docker logs --tail 100 mentor-pro-app-1 2>&1 | sed -E 's#(postgres(ql)?://)[^@ ]*@#\1<redacted>@#g'
$COMPOSE ps
sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/app.env    # which keys exist, never values
```

Do not share `docker compose config`, `docker inspect` (`.Config.Env`) or
`env` output: they contain the secrets.

## J. Tutor service (ADR-031)

The student service (`app`) never holds the tutor token. A separate
`tutor` service runs `python -m app.tutor_main` (tutor routes only) from
the same digest, published on the server's loopback only. It refuses to
start without a token of at least 32 characters or with an allowed-hosts
value that is not a list of exact IP addresses.

Pre-checks (read-only):

```bash
sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/app.env | grep -c MENTOR_PRO_TUTOR   # expect 0
GW=$(docker network inspect mentor-pro_default --format '{{range .IPAM.Config}}{{.Gateway}}{{end}}')
echo "$GW"                                                                        # 172.19.0.1 on 2026-10-27
docker ps -q | xargs docker inspect --format '{{.Name}} {{.HostConfig.NetworkMode}}' | grep -w host  # expect none
```

**Stop** if `app.env` holds a tutor key (remove it first) or a container
uses host networking (it could reach `127.0.0.1:8081` as the gateway; it
would still need the token, but the design assumes none).

Token file (once; the token is never printed, logged or committed):

```bash
sudo sh -c "umask 077 && { printf 'MENTOR_PRO_TUTOR_TOKEN=%s\n' \"\$(openssl rand -hex 24)\"; \
  printf 'MENTOR_PRO_TUTOR_ALLOWED_HOSTS=%s\n' '$GW'; } > /etc/mentor-pro/tutor.env"
sudo chmod 600 /etc/mentor-pro/tutor.env && sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/tutor.env
```

The parent reads the token once with `sudo cat /etc/mentor-pro/tutor.env`
over SSH and keeps it in a password manager.

Add to `compose.deploy.yml` (same digest as `app`):

```yaml
  tutor:
    image: ghcr.io/jonnabio/mentor-pro@sha256:<digest>  # same literal as app
    command: ["python", "-m", "app.tutor_main"]
    restart: unless-stopped
    env_file:
      - /etc/mentor-pro/app.env     # database settings; no tutor key
      - /etc/mentor-pro/tutor.env   # token and allowed hosts (tutor only)
    environment:
      MENTOR_PRO_DEV_ENDPOINTS: "false"
    ports:
      - "127.0.0.1:8081:8000"       # never the Wi-Fi or wired address
    depends_on:
      postgres:
        condition: service_healthy
```

Start and verify:

```bash
$COMPOSE up -d tutor
docker port mentor-pro-tutor-1                       # 127.0.0.1:8081 only
for p in /api/tutor/queue /tutor; do printf '%s ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:8081$p"; done
                                                     # /api/tutor/queue 403 (no token), /tutor 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/tutor/queue   # 404: student service
docker logs --tail 5 mentor-pro-tutor-1 2>&1 | grep -c "$GW"                     # requests come from the gateway
```

From another device on the house Wi-Fi: `http://192.168.50.229:8081/`
must be refused and `http://192.168.50.229:8080/api/tutor/queue` must
answer 404.

Tutor use (from the parent's computer):

```bash
ssh -N -L 8081:127.0.0.1:8081 jonnabio@100.64.84.15
# then open http://127.0.0.1:8081/tutor and enter the token
```

A refused start exits 78 (`tutor configuration rejected: …`); a token of 1–15
characters currently exits 1 with `ValueError` from the student module
import (still refused; T035). A start failure with `TutorConfigurationError` means the token or the
allowed hosts are wrong; fix `tutor.env` (never widen it to a range). If
the compose network is recreated, recheck the gateway: a wrong address
answers 403 to everything. `docker compose stop tutor` disables review
without affecting students.
