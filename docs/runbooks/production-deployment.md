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
$COMPOSE exec -T postgres pg_dump -U mentor_pro_admin -d mentor_pro -Fc \
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

Browser: `ssh -N -L 8080:127.0.0.1:8080 jonnabio@100.64.84.15`, then
`http://127.0.0.1:8080/`.

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

## H. Diagnostics without credentials

```bash
docker logs --tail 100 mentor-pro-app-1 2>&1 | sed -E 's#(postgres(ql)?://)[^@ ]*@#\1<redacted>@#g'
$COMPOSE ps
sudo sed -E 's/=.*/=<set>/' /etc/mentor-pro/app.env    # which keys exist, never values
```

Do not share `docker compose config`, `docker inspect` (`.Config.Env`) or
`env` output: they contain the secrets.
