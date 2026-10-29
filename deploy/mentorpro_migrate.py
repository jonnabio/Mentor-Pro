"""Isolated migration rehearsal, maintenance window and gated migration (T045, ADR-033 increment I5).
Run through `deploy/mentorpro`.

    deploy/mentorpro maintenance start --window <ref> --authorization <ref>   (app and tutor stop)
    deploy/mentorpro backup                                                    (I2: BACKUP OK, services stopped)
    deploy/mentorpro rehearse <manifest.json> <dump> --window <ref> --authorization <ref>
    deploy/mentorpro migrate <manifest.json> --backup <dump> --window <ref> --authorization <ref>
    deploy/mentorpro maintenance end --window <ref> --authorization <ref>     (only while the schema is unchanged)

Standard library only; uses the T044 helper (identity, schema, evidence, lock, RELEASES, deploy).

Rules (PO, 2026-10-29; corrections of the PR #23 review):
- window: `maintenance start` gives the window an identity (reference, start time, random id); `rehearse`,
  `migrate` and `maintenance end` refuse a --window that does not name the open window before changing anything,
  and `migrate` accepts only rehearsal evidence recorded in that same window;
- rehearse: the release migrates and runs on a copy of this dump in a private compose project
  mentorpro-rehearsal-<id>: internal network, own volume, no published ports, generated credentials, never a
  production env file, network, volume or database; smoke tests from a short-lived checker on that network; every
  container, volume, network and the dump copy removed and the removal verified, on success and failure. Backups
  are never deleted. Space for the copy, the restore, the migration and the volumes is checked first; fail closed;
- migrate: under the T044 lock (re-entrant here, so the deploy path runs inside it). Needs the maintenance window
  of the same --window, app and tutor stopped and no other database session, BACKUP OK taken after the window
  started, REHEARSAL OK for the same release digest and the same dump checksum, both at most six hours old, the
  live schema `legacy` and the live data unchanged since that dump (fingerprint), the full image identity check,
  window and PO authorization references. PostgreSQL keeps running. Only the explicit
  `python -m app.writing.migrate apply` changes the schema (dry run first); then the schema transition, the
  migrated data against the rehearsal and the scope of the change are verified, then the T044 deploy path (health,
  smoke);
- time: at most 60 minutes of student downtime; the migration does not begin after the 40-minute checkpoint, or
  when the projection from the rehearsal's measured durations exceeds 60 minutes (abort and reassess); every
  remaining step needs a finite, non-negative measured duration, and incomplete timing evidence refuses;
- recovery: a failure before `apply` leaves the old schema; `maintenance end` restarts the previous release after
  checking it. A failure during or after `apply` stops app and tutor, keeps them stopped and requires a separate
  database-recovery decision; there is no automatic restore or rollback, and a pre-T036 image never runs on a
  migrated database;
- references are recorded as given (authorization_verified=no); the script cannot prove a PO approval.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mentorpro_deploy as md  # noqa: E402

PREFIX = "mentorpro-rehearsal-"
PROJECT = re.compile(r"mentorpro-rehearsal-[0-9a-z]+(?:-[0-9a-z]+)*")
MARKER = ".mentorpro-rehearsal"
LABEL = "com.docker.compose.project"
SERVICES = {"postgres", "app", "tutor"}
TARGET = md.KNOWN_MIGRATIONS[-1][:4]  # the schema `apply` brings a database to
DOWNTIME_LIMIT = timedelta(minutes=60)  # PO 2026-10-29: fixed, not configurable
CHECKPOINT = timedelta(minutes=40)
PROJECTION_FACTOR = 2  # the remaining steps may take twice as long as in the rehearsal
REMAINING = ("dry run", "apply", "verify", "start app and tutor", "smoke")
RESTORE_FACTOR = 10  # restored database estimate: ten times the compressed dump, plus a fresh cluster
CLUSTER_BYTES = 256 * 2**20
MARGIN_BYTES = 2**30
SCOPE = ("writing.draft", "writing.submission")  # rewritten by 0001 (compared by the migration's own report)
NEW_TABLES = ("writing.student_attempt", "writing.schema_migration")
UNREACHABLE_FROM_REHEARSAL = "192.0.2.1"  # TEST-NET-1: the rehearsal tutor allows no client
INTERNET_PROBE = "1.1.1.1"


class Failed(Exception):
    """A step failed after the rehearsal or the migration started."""

    def __init__(self, step: str, reason: str):
        super().__init__(f"{step}: {reason}")
        self.step, self.reason = step, reason


def settings() -> dict:
    cfg = md.settings()
    cfg.update(rehearsal=Path(md.env("MENTORPRO_REHEARSAL_DIR", "/var/lib/mentor-pro/rehearsal")),
               rehearsal_compose=Path(md.env("MENTORPRO_REHEARSAL_COMPOSE", str(md.HERE / "compose.rehearsal.yml"))),
               reserve=max(0, int(md.env("MENTORPRO_REHEARSAL_RESERVE_BYTES", "0"))))  # can only add
    return cfg


@contextlib.contextmanager
def step(name: str, times: dict):
    print(f"-- {name}", flush=True)
    started = time.monotonic()
    try:
        yield
    except Failed:
        raise
    except (md.Refused, OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise Failed(name, md.one_line(str(exc))) from None
    times[name] = round(time.monotonic() - started, 1)


# ---------------------------------------------------------------- data checks (counts and digests, never rows)

# Identical to FINGERPRINT_SQL in deploy/mentorpro (I2), so a live database compares with its backup record.
FINGERPRINT_SQL = r"""SET TimeZone = 'UTC'; SET DateStyle = 'ISO, YMD'; SET IntervalStyle = 'postgres';
SET extra_float_digits = 1;
SELECT format('SELECT %L, count(*), md5(coalesce(string_agg(t::text, E''\n'' ORDER BY t::text COLLATE "C"), '''')) FROM %I.%I t',
              n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p') AND n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
ORDER BY 1 \gexec
"""

COUNTS_SQL = """SET default_transaction_read_only = on;
SELECT json_build_object(
  'exercises_with_work', (SELECT count(*) FROM (SELECT exercise_id FROM writing.draft
                                                UNION SELECT exercise_id FROM writing.submission) w),
  'drafts', (SELECT count(*) FROM writing.draft),
  'submissions', (SELECT count(*) FROM writing.submission),
  'evaluations', (SELECT count(*) FROM writing.evaluation),
  'criterion_scores', (SELECT count(*) FROM writing.criterion_score),
  'evaluations_of_submissions', (SELECT count(*) FROM writing.evaluation v JOIN writing.submission s
                                 USING (submission_id)),
  'scores_of_evaluations', (SELECT count(*) FROM writing.criterion_score c JOIN writing.evaluation v
                            USING (evaluation_id)));
"""

ATTEMPTS_SQL = """SET default_transaction_read_only = on;
SELECT json_build_object(
  'attempts', (SELECT count(*) FROM writing.student_attempt),
  'attempts_not_first', (SELECT count(*) FROM writing.student_attempt
                         WHERE attempt_number <> 1 OR previous_attempt_id IS NOT NULL),
  'drafts_on_attempt_one', (SELECT count(*) FROM writing.draft d JOIN writing.student_attempt a
                            USING (attempt_id, exercise_id) WHERE a.attempt_number = 1),
  'submissions_on_attempt_one', (SELECT count(*) FROM writing.submission s JOIN writing.student_attempt a
                                 USING (attempt_id, exercise_id) WHERE a.attempt_number = 1),
  'attempts_without_work', (SELECT count(*) FROM writing.student_attempt a
                            WHERE NOT EXISTS (SELECT 1 FROM writing.draft d WHERE d.attempt_id = a.attempt_id)
                              AND NOT EXISTS (SELECT 1 FROM writing.submission s WHERE s.attempt_id = a.attempt_id)));
"""

SESSIONS_SQL = """SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()
  AND pid <> pg_backend_pid() AND backend_type = 'client backend';
"""


def fingerprint_digest(text: str) -> str:
    """As `digest` in deploy/mentorpro: sha256 of the psql output with one final newline."""
    return hashlib.sha256((text.replace("\r", "").rstrip("\n") + "\n").encode("utf-8")).hexdigest()


def tables(text: str) -> dict[str, str]:
    return {line.split("|", 1)[0]: line for line in text.replace("\r", "").splitlines() if "|" in line}


def scope_problems(before: str, after: str) -> list[str]:
    """Tables outside the migration scope must be byte-identical; only the two new tables may appear."""
    b, a = tables(before), tables(after)
    problems = [f"{t} disappeared" for t in b if t not in a]
    problems += [f"unexpected new table {t}" for t in a if t not in b and t not in NEW_TABLES]
    problems += [f"{t} changed outside the migration scope" for t in b if t in a and t not in SCOPE and a[t] != b[t]]
    return problems


def migration_problems(before: dict, after: dict, attempts: dict) -> list[str]:
    """Records and relationships kept; attempt 1 backfilled for every exercise with work, nothing else."""
    problems = [f"{k} changed ({before[k]} -> {after.get(k)})" for k in before if after.get(k) != before[k]]
    expected = {"attempts": before.get("exercises_with_work"), "attempts_not_first": 0,
                "drafts_on_attempt_one": before.get("drafts"), "submissions_on_attempt_one": before.get("submissions"),
                "attempts_without_work": 0}
    problems += [f"{k} is {attempts.get(k)}, expected {v}" for k, v in expected.items() if attempts.get(k) != v]
    return problems


def report_problems(report: dict, before: dict) -> list[str]:
    problems = []
    if report.get("status") != "applied":
        problems.append(f"migration status {report.get('status')!r}, not 'applied'")
    if report.get("before") != report.get("after"):
        problems.append("draft, submission, evaluation or criterion_score rows differ before and after")
    if report.get("attempts_created") != before.get("exercises_with_work"):
        problems.append(f"{report.get('attempts_created')} attempts created for {before.get('exercises_with_work')} "
                        "exercises with work")
    return problems


def psql(cfg: dict, container: str, sql: str) -> str:
    cmd = [*cfg["docker"], "exec", "-i", "-e", "PGCLIENTENCODING=UTF8", container, "psql", "-U", cfg["pg_user"],
           "-d", cfg["pg_db"], "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    out = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=3600)
    if out.returncode != 0:
        raise md.Refused(f"psql in {container} failed: {md.one_line(out.stderr)}")
    return out.stdout


def counts(cfg: dict, container: str, sql: str = COUNTS_SQL) -> dict:
    return json.loads(psql(cfg, container, sql).strip())


# ---------------------------------------------------------------- evidence

def dump_state(record: dict) -> tuple[str, str, str]:
    state = (record.get("schema_state") or "").split()
    if state not in (["legacy", "none"], ["current", TARGET]):
        raise md.Refused(f"backup schema state {record.get('schema_state')!r} is not legacy or current")
    return state[0], state[1], ""


def rehearsal_path(cfg: dict, digest: str, dump_sha: str) -> Path:
    return cfg["state"] / "rehearsal" / f"{digest.split(':', 1)[1]}.{dump_sha}.json"


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_rehearsal(record: dict | None, digest: str, dump_sha: str, now: datetime, window: dict) -> None:
    if not record:
        raise md.Refused("no rehearsal of this release on this dump; run `mentorpro rehearse <manifest> <dump>`")
    if record.get("result") != "REHEARSAL OK":
        raise md.Refused(f"rehearsal result was {record.get('result')!r} ({record.get('step')}: "
                         f"{record.get('reason')})")
    if record.get("digest") != digest or record.get("dump_sha256") != dump_sha:
        raise md.Refused("rehearsal record is for another release digest or another dump")
    if (record.get("window"), record.get("window_id")) != (window.get("window"), window.get("window_id")):
        raise md.Refused(f"rehearsal was made in another maintenance window ({record.get('window')} "
                         f"{record.get('window_id')}); rehearse again in this window")
    if record.get("cleanup") != "verified":
        raise md.Refused("rehearsal cleanup was not verified")
    if record.get("schema_after") != f"current {TARGET}":
        raise md.Refused(f"rehearsal ended on schema {record.get('schema_after')!r}, not current {TARGET}")
    try:
        finished = md.parse_stamp(record.get("finished_at", ""))
    except ValueError:
        raise md.Refused("rehearsal record has no valid timestamp") from None
    md.fresh_enough(finished, now, "rehearsal")


def timing_problems(durations) -> list[str]:
    """Every remaining step needs a measured, finite, non-negative duration; incomplete evidence never passes."""
    if not isinstance(durations, dict):
        return ["rehearsal record has no measured durations"]
    problems = []
    for key in REMAINING:
        value = durations.get(key)
        if value is None:
            problems.append(f"rehearsal duration of {key!r} is missing")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            problems.append(f"rehearsal duration of {key!r} is not a valid measurement ({value!r})")
    return problems


def window_problems(started: datetime, now: datetime, durations) -> list[str]:
    """The 40-minute checkpoint and the 60-minute limit, projected from the rehearsal's measured durations."""
    elapsed = now - started
    minutes = round(elapsed.total_seconds() / 60, 1)
    if elapsed > CHECKPOINT:
        return [f"40-minute checkpoint passed ({minutes} min since maintenance start) and the migration has not "
                "begun: abort and reassess"]
    problems = timing_problems(durations)
    if problems:
        return problems + ["incomplete timing evidence: the 60-minute projection cannot be made; rehearse again"]
    remaining = timedelta(seconds=PROJECTION_FACTOR * sum(durations[k] for k in REMAINING))
    if elapsed + remaining > DOWNTIME_LIMIT:
        total = round((elapsed + remaining).total_seconds() / 60, 1)
        return [f"projected downtime {total} min ({minutes} elapsed + {PROJECTION_FACTOR} x the rehearsal) exceeds "
                "60 min: abort and reassess"]
    return []


# ---------------------------------------------------------------- storage

def free_space(path: Path) -> tuple[int, int]:
    """(device, free bytes) of the filesystem holding an existing path."""
    if not path.exists():
        raise md.Refused(f"{path} does not exist; free space cannot be checked")
    return os.stat(path).st_dev, shutil.disk_usage(path).free


def space_problems(needs: list[tuple[str, Path, int]], probe=free_space) -> list[str]:
    """Needs on the same filesystem add up; each filesystem must hold all of its needs."""
    filesystems: dict = {}
    for what, path, size in needs:
        device, free = probe(path)
        entry = filesystems.setdefault(device, {"path": path, "free": free, "need": 0, "what": []})
        entry["need"] += size
        entry["what"].append(f"{what} {size}")
    return [f"filesystem of {e['path']} needs {e['need']} bytes ({', '.join(e['what'])}), {e['free']} free"
            for e in filesystems.values() if e["need"] > e["free"]]


def restore_estimate(dump_bytes: int) -> int:
    return CLUSTER_BYTES + RESTORE_FACTOR * dump_bytes


def docker_root(cfg: dict) -> Path:
    out = md.docker(cfg, "info", "--format", "{{.DockerRootDir}}", check=False)
    if out.returncode != 0 or not out.stdout.strip():
        raise md.Refused("Docker data directory unknown; free space cannot be checked")
    return Path(out.stdout.strip())


def private_dir(path: Path) -> None:
    """The rehearsal directory: owned by the operator account (root on the server), no group or other access."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if os.name == "posix" and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
        raise md.Refused(f"{path} must be owned by this account (root on the server) with mode 0700")


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


# ---------------------------------------------------------------- rehearsal isolation and cleanup

def check_config(config: dict, project: str, workdir: Path, ref: str) -> list[str]:
    """The resolved compose configuration: only rehearsal services, networks and volumes; nothing published."""
    problems = []
    if config.get("name") != project:
        problems.append(f"project name {config.get('name')!r} is not {project}")
    services = config.get("services") or {}
    if set(services) != SERVICES:
        problems.append(f"services {sorted(services)} are not {sorted(SERVICES)}")
    networks, volumes = config.get("networks") or {}, config.get("volumes") or {}
    for key, net in networks.items():
        net = net or {}
        if net.get("external") or net.get("name") != f"{project}_{key}":
            problems.append(f"network {key} is not this project's own ({net.get('name')})")
        if net.get("internal") is not True:
            problems.append(f"network {key} is not internal")
    for key, vol in volumes.items():
        vol = vol or {}
        if vol.get("external") or vol.get("name") != f"{project}_{key}":
            problems.append(f"volume {key} is not this project's own ({vol.get('name')})")
    root = workdir.resolve()
    for name, svc in services.items():
        for key in ("ports", "network_mode", "container_name", "extra_hosts", "privileged", "pid", "ipc"):
            if svc.get(key):
                problems.append(f"{name} sets {key}")
        if set(svc.get("networks") or {}) != set(networks) or not networks:
            problems.append(f"{name} joins networks {sorted(svc.get('networks') or {})}")
        for mount in svc.get("volumes") or []:
            if not isinstance(mount, dict) or mount.get("type") != "volume" or mount.get("source") not in volumes:
                problems.append(f"{name} mounts {mount!r}, not a rehearsal volume")
        for entry in svc.get("env_file") or []:
            path = Path(entry["path"] if isinstance(entry, dict) else entry).resolve()
            if root not in path.parents:
                problems.append(f"{name} reads env file {path} outside the rehearsal directory")
        if name != "postgres" and svc.get("image") != ref:
            problems.append(f"{name} image {svc.get('image')} is not the release digest")
    return problems


def check_containers(infos: list[dict], project: str, network: str) -> list[str]:
    """The running rehearsal: own names, own network only, no published port, own volumes only."""
    problems = []
    for info in infos:
        name = (info.get("Name") or "").lstrip("/")
        settings_ = info.get("NetworkSettings") or {}
        if not name.startswith(project + "-"):
            problems.append(f"container {name} is not named for {project}")
        joined = set(settings_.get("Networks") or {})
        if joined != {network}:
            problems.append(f"{name} joins networks {sorted(joined)}")
        if (info.get("HostConfig") or {}).get("PortBindings") or any((settings_.get("Ports") or {}).values()):
            problems.append(f"{name} publishes a port")
        for mount in info.get("Mounts") or []:
            if mount.get("Type") != "volume" or not str(mount.get("Name", "")).startswith(project + "_"):
                problems.append(f"{name} mounts {mount.get('Type')} {mount.get('Name') or mount.get('Source')}")
    return problems


def project_ids(cfg: dict, project: str) -> dict[str, list[str]]:
    found = {}
    for kind, args in (("containers", ("ps", "-aq")), ("volumes", ("volume", "ls", "-q")),
                       ("networks", ("network", "ls", "-q"))):
        ids = md.docker(cfg, *args, "--filter", f"label={LABEL}={project}", check=False).stdout.split()
        ids += md.docker(cfg, *args, "--filter", f"name={project}", check=False).stdout.split()
        found[kind] = sorted(set(ids))
    return found


def remove_workdir(base: Path, workdir: Path) -> None:
    """Only a marked rehearsal directory directly under the rehearsal base (holds the dump copy, never a backup)."""
    if workdir.parent.resolve() != base.resolve() or not PROJECT.fullmatch(workdir.name):
        raise md.Refused(f"cleanup refused: {workdir} is not a rehearsal directory")
    if workdir.exists():
        if not (workdir / MARKER).is_file():
            raise md.Refused(f"cleanup refused: {workdir} has no rehearsal marker")
        shutil.rmtree(workdir)


def cleanup(cfg: dict, project: str, workdir: Path) -> str:
    """Removes this rehearsal's containers, volumes and networks (by its compose project) and its directory, then
    lists them again. Returns 'verified', or what remains."""
    if not PROJECT.fullmatch(project):
        raise md.Refused(f"cleanup refused: {project} is not a rehearsal project")
    found = project_ids(cfg, project)
    for kind, args in (("containers", ("rm", "-f")), ("volumes", ("volume", "rm")), ("networks", ("network", "rm"))):
        if found[kind]:
            md.docker(cfg, *args, *found[kind], check=False)
    try:
        remove_workdir(cfg["rehearsal"], workdir)
    except (md.Refused, OSError) as exc:
        print(f"CLEANUP: {exc}")
    left = [f"{len(ids)} {kind}" for kind, ids in project_ids(cfg, project).items() if ids]
    if workdir.exists():
        left.append(f"directory {workdir}")
    return "verified" if not left else "remaining: " + ", ".join(left)


CHECKER = r'''import socket, sys, urllib.error, urllib.request
def code(url):
    try:
        return urllib.request.urlopen(url, timeout=5).status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return 0
def reachable(host, port):
    try:
        socket.create_connection((host, port), timeout=3).close()
        return True
    except OSError:
        return False
checks = [("student " + p, code("http://app:8000" + p), 200) for p in
          ("/", "/api/subjects", "/api/dashboard", "/api/writing/levels")]
checks += [("student service has no tutor routes", code("http://app:8000/api/tutor/queue"), 404),
           ("tutor page refused to a host that is not allowed", code("http://tutor:8000/tutor"), 403),
           ("tutor API refuses without the token", code("http://tutor:8000/api/tutor/queue"), 403),
           ("production database not reachable", reachable(sys.argv[1], 5432), False),
           ("no route out of the rehearsal network", reachable(sys.argv[2], 443), False)]
failed = 0
for label, got, want in checks:
    failed += got != want
    print(("PASS" if got == want else "FAIL") + f" {label} ({got})")
print(f"SMOKE PASS ({len(checks)}/{len(checks)})" if not failed else f"SMOKE FAIL ({failed} of {len(checks)} failed)")
sys.exit(1 if failed else 0)
'''


class Rehearsal:
    """One rehearsal project: compose commands against deploy/compose.rehearsal.yml only."""

    def __init__(self, cfg: dict, project: str, workdir: Path):
        if not PROJECT.fullmatch(project):
            raise md.Refused(f"{project} is not a rehearsal project name")
        self.cfg, self.project, self.workdir = cfg, project, workdir
        self.postgres = f"{project}-postgres-1"
        self.network = ""

    def compose(self, *args: str, timeout: int = 900) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k not in ("MENTOR_PRO_IMAGE", "REHEARSAL_DIR")}
        cmd = [*self.cfg["docker"], "compose", "-p", self.project, "-f", str(self.cfg["rehearsal_compose"]),
               "--env-file", str(self.workdir / "compose.env"), *args]
        return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)

    def checked(self, *args: str, timeout: int = 900) -> str:
        out = self.compose(*args, timeout=timeout)
        if out.returncode != 0:
            raise md.Refused(f"compose {args[0]} exited {out.returncode}: "
                             f"{md.one_line(out.stderr or out.stdout)}")
        return out.stdout

    def write_env(self, ref: str) -> None:
        cfg, password = self.cfg, secrets.token_hex(24)
        write_private(self.workdir / "compose.env",
                      f"MENTOR_PRO_IMAGE={ref}\nREHEARSAL_DIR={self.workdir.resolve().as_posix()}\n")
        write_private(self.workdir / "postgres.env", f"POSTGRES_USER={cfg['pg_user']}\nPOSTGRES_PASSWORD={password}\n"
                                                     f"POSTGRES_DB={cfg['pg_db']}\n")
        write_private(self.workdir / "app.env",
                      f"DATABASE_URL=postgresql://{cfg['pg_user']}:{password}@postgres:5432/{cfg['pg_db']}\n")
        write_private(self.workdir / "tutor.env", f"MENTOR_PRO_TUTOR_TOKEN={secrets.token_hex(32)}\n"
                                                  f"MENTOR_PRO_TUTOR_ALLOWED_HOSTS={UNREACHABLE_FROM_REHEARSAL}\n")

    def check_config(self, ref: str) -> None:
        config = json.loads(self.checked("config", "--format", "json"))
        problems = check_config(config, self.project, self.workdir, ref)
        if problems:
            raise md.Refused("isolation: " + "; ".join(problems))
        self.network = config["networks"]["rehearsal"]["name"]

    def check_running(self) -> int:
        ids = md.docker(self.cfg, "ps", "-aq", "--filter", f"label={LABEL}={self.project}").stdout.split()
        infos = json.loads(md.docker(self.cfg, "inspect", *ids).stdout) if ids else []
        problems = check_containers(infos, self.project, self.network)
        if problems:
            raise md.Refused("isolation: " + "; ".join(problems))
        return len(infos)

    def restore(self, dump: Path) -> None:
        with dump.open("rb") as handle:
            out = subprocess.run([*self.cfg["docker"], "exec", "-i", self.postgres, "pg_restore", "--exit-on-error",
                                  "--single-transaction", "--no-owner", "--no-privileges", "-U", self.cfg["pg_user"],
                                  "-d", self.cfg["pg_db"]], stdin=handle, capture_output=True, timeout=7200)
        if out.returncode != 0:
            raise md.Refused(f"pg_restore exited {out.returncode}: "
                             f"{md.one_line(out.stderr.decode('utf-8', 'replace'))}")

    def migrate(self, *args: str) -> dict:
        out = self.compose("run", "--rm", "--no-deps", "-T", "app", "python", "-m", "app.writing.migrate", *args,
                           timeout=7200)
        if out.returncode != 0:
            raise md.Refused(md.one_line(out.stderr or out.stdout))
        return json.loads(out.stdout)

    def smoke(self, ref: str) -> None:
        out = md.docker(self.cfg, "run", "--rm", "--name", f"{self.project}-checker", "--label",
                        f"{LABEL}={self.project}", "--network", self.network, ref, "python", "-c", CHECKER,
                        self.cfg["pg_container"], INTERNET_PROBE, check=False)
        print(out.stdout.rstrip())
        if out.returncode != 0:
            raise md.Refused("smoke tests failed inside the rehearsal network")


def copy_private(source: Path, target: Path) -> str:
    """Copies with mode 0600 from the start; returns the sha256 of what was written."""
    digest = hashlib.sha256()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
        for chunk in iter(lambda: src.read(2**20), b""):
            digest.update(chunk)
            dst.write(chunk)
    return digest.hexdigest()


def rehearse(args, cfg: dict) -> int:
    md.check_references(args.window, args.authorization)
    with md.deploy_lock(cfg):
        window = open_window(cfg, args.window)
        manifest, _ = md.load_manifest(Path(args.manifest), cfg["repository"])
        digest = manifest["image"]["digest"]
        ref = f"{cfg['repository']}@{digest}"
        declared = md.verify_release_image(cfg, manifest)
        dump = Path(args.dump)
        record = md.read_backup_record(dump)
        before_state = dump_state(record)
        dump_sha = md.check_backup(dump, record, cfg["pg_db"], before_state, md.utc_now())
        if not re.fullmatch(r"[0-9a-f]{64}", record.get("fingerprint", "")):
            raise md.Refused("backup record has no data fingerprint")
        verdict = md.compatibility(declared, before_state[1])
        if verdict == "incompatible" or md.compatibility(declared, TARGET) != "compatible":
            raise md.Refused(f"image schema {declared[0]}..{declared[1]} cannot run on this dump after migration")
        migration = verdict == "migration required"
        base = cfg["rehearsal"]
        private_dir(base)
        size = dump.stat().st_size
        problems = space_problems([("dump copy", base, size), ("margin", base, MARGIN_BYTES + cfg["reserve"]),
                                   ("restored database", docker_root(cfg), restore_estimate(size)),
                                   ("migration overhead", docker_root(cfg), restore_estimate(size))])
        if problems:
            raise md.Refused("insufficient space: " + "; ".join(problems))

        project = f"{PREFIX}{md.utc_now().strftime('%Y%m%dt%H%M%S')}-{os.getpid()}"
        workdir = base / project
        workdir.mkdir(mode=0o700)
        (workdir / MARKER).write_text(f"{project}\n", encoding="utf-8")
        run = Rehearsal(cfg, project, workdir)
        result: dict = {"release": manifest["release"], "digest": digest, "image": ref, "dump": dump.name,
                        "dump_sha256": dump_sha, "database": cfg["pg_db"],
                        "schema_before": f"{before_state[0]} {before_state[1]}", "migration": migration,
                        "started_at": md.stamp(md.utc_now()), "operator": md.operator(), "window": args.window,
                        "window_id": window["window_id"], "authorization": args.authorization, "authorization_verified": "no"}
        times: dict = {}
        started, failure = time.monotonic(), None
        print(f"rehearsal {project}: release {manifest['release']} on {dump.name} ({before_state[0]})")
        try:
            with step("isolation check", times):
                run.write_env(ref)
                run.check_config(ref)
            with step("copy", times):
                if copy_private(dump, workdir / "backup.dump") != dump_sha:
                    raise md.Refused("the copy differs from the backup")
            with step("start postgres", times):
                run.checked("up", "-d", "--wait", "--wait-timeout", "300", "postgres")
                run.check_running()
            with step("restore", times):
                run.restore(workdir / "backup.dump")
                restored = psql(cfg, run.postgres, FINGERPRINT_SQL)
                if fingerprint_digest(restored) != record["fingerprint"]:
                    raise md.Refused("restored data differs from the backup record")
            with step("schema before", times):
                live = md.classify(psql(cfg, run.postgres, md.SCHEMA_SQL))
                if live[:2] != before_state[:2]:
                    raise md.Refused(f"restored schema {live[0]} {live[1]} differs from the backup record")
                result["counts_before"] = counts(cfg, run.postgres)
            if migration:
                with step("dry run", times):
                    dry = run.migrate("apply", "--dry-run")
                    if dry.get("status") != "dry_run_rolled_back":
                        raise md.Refused(f"dry run status {dry.get('status')!r}")
                with step("apply", times):
                    report = run.migrate("apply")
                    problems = report_problems(report, result["counts_before"])
                    if problems:
                        raise md.Refused("; ".join(problems))
                    result["attempts_created"] = report["attempts_created"]
                with step("verify", times):
                    after = md.classify(psql(cfg, run.postgres, md.SCHEMA_SQL))
                    if after[:2] != ("current", TARGET):
                        raise md.Refused(f"schema after migration is {after[0]} {after[1]}")
                    result["counts_after"] = counts(cfg, run.postgres)
                    result["attempts"] = counts(cfg, run.postgres, ATTEMPTS_SQL)
                    problems = migration_problems(result["counts_before"], result["counts_after"],
                                                  result["attempts"])
                    problems += scope_problems(restored, psql(cfg, run.postgres, FINGERPRINT_SQL))
                    if problems:
                        raise md.Refused("; ".join(problems))
            result["schema_after"] = f"current {TARGET}"
            with step("start app and tutor", times):
                run.checked("up", "-d", "--wait", "--wait-timeout", "300", "app", "tutor")
                print(f"isolation verified: {run.check_running()} containers, network {run.network} only, "
                      "no published port")
            with step("smoke", times):
                run.smoke(ref)
        except Failed as exc:
            failure = exc
        except KeyboardInterrupt:
            failure = Failed("interrupted", "operator interrupt")
        finally:
            with contextlib.suppress(Failed):
                with step("cleanup", times):
                    result["cleanup"] = cleanup(cfg, project, workdir)
            result.setdefault("cleanup", "not verified")
        times["total"] = round(time.monotonic() - started, 1)
        result.update(durations=times, finished_at=md.stamp(md.utc_now()))
        if failure is None and result["cleanup"] != "verified":
            failure = Failed("cleanup", result["cleanup"])
        if failure:
            result.update(result="REHEARSAL FAILED", step=failure.step, reason=failure.reason)
            result.pop("schema_after", None)
        else:
            result["result"] = "REHEARSAL OK"
        path = rehearsal_path(cfg, digest, dump_sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
        md.record_release(cfg, action="rehearse", result="OK" if not failure else "FAILED",
                          **({"step": failure.step, "error": failure.reason} if failure else {}),
                          version=manifest["release"], image=ref, backup_sha256=dump_sha, window=args.window,
                          authorization=args.authorization, authorization_verified="no")
        print("durations (s): " + ", ".join(f"{k} {v}" for k, v in times.items()))
        print(f"cleanup {result['cleanup']}: {project} containers, volumes, network and dump copy")
        if failure:
            print(f"REHEARSAL FAILED at {failure.step}: {failure.reason} (record {path})")
            return 1
        print(f"REHEARSAL OK: {manifest['release']} on {dump.name} (record {path}, valid six hours)")
        return 0


# ---------------------------------------------------------------- maintenance window

def maintenance_path(cfg: dict) -> Path:
    return cfg["state"] / "maintenance.json"


def marker_path(cfg: dict) -> Path:
    return cfg["state"] / "migration.json"


def archive(cfg: dict, path: Path) -> None:
    history = cfg["state"] / "history"
    history.mkdir(parents=True, exist_ok=True)
    os.replace(path, history / f"{path.stem}.{md.utc_now().strftime('%Y%m%dT%H%M%SZ')}.json")


def running(cfg: dict, service: str) -> bool:
    out = md.docker(cfg, "inspect", md.container(cfg, service), "--format", "{{.State.Running}}", check=False)
    return out.returncode == 0 and out.stdout.strip() == "true"


def stop_services(cfg: dict) -> str:
    """Stops app and tutor (PostgreSQL keeps running); empty when both are verified stopped."""
    env = {k: v for k, v in os.environ.items() if k != "MENTOR_PRO_IMAGE"}
    out = subprocess.run([*cfg["docker"], "compose", "-p", cfg["project"], "-f", str(cfg["compose"]), "--env-file",
                          str(cfg["release_env"]), "stop", "app", "tutor"], env=env, capture_output=True, text=True,
                         timeout=600)
    still = [s for s in ("app", "tutor") if running(cfg, s)]
    if still:
        return f"still running: {', '.join(still)}" + (f" ({md.one_line(out.stderr)})" if out.returncode else "")
    return ""


def read_maintenance(cfg: dict) -> dict:
    record = read_json(maintenance_path(cfg))
    if not record:
        raise md.Refused("no maintenance window is open; run `mentorpro maintenance start` first")
    return record


def open_window(cfg: dict, ref: str) -> dict:
    """The open maintenance window, only when --window names it; nothing changes on a mismatch."""
    record = read_maintenance(cfg)
    if record.get("window") != ref:
        raise md.Refused(f"--window {ref} is not the open maintenance window ({record.get('window')}); "
                         "nothing changed")
    if not record.get("window_id"):
        raise md.Refused("the open maintenance window has no identity; nothing changed")
    return record


def maintenance(args, cfg: dict) -> int:
    md.check_references(args.window, args.authorization)
    refs = {"window": args.window, "authorization": args.authorization, "authorization_verified": "no"}
    with md.deploy_lock(cfg):
        if args.action == "start":
            if maintenance_path(cfg).exists():
                raise md.Refused(f"a maintenance window is already open since {read_maintenance(cfg)['started_at']}")
            live = md.read_live(cfg)
            md.require_ok_state(live)
            now = md.utc_now()
            record = {"started_at": md.stamp(now), "window_id": f"{md.stamp(now)}/{secrets.token_hex(8)}", "image": md.current_image(cfg) or "none", "state": live[0],
                      "schema": live[1], "operator": md.operator(), **refs}
            maintenance_path(cfg).parent.mkdir(parents=True, exist_ok=True)
            maintenance_path(cfg).write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
            error = stop_services(cfg)
            if error or not running(cfg, "postgres"):
                error = error or "PostgreSQL is not running"
                md.record_release(cfg, action="maintenance-start", result="FAILED", error=error, **refs)
                print(f"MAINTENANCE START FAILED: {error}; the window stays open, nothing else changed")
                return 1
            md.record_release(cfg, action="maintenance-start", result="OK", image=record["image"],
                              window_id=record["window_id"],
                              schema=f"{live[0]}:{live[1]}", **refs)
            print(f"MAINTENANCE STARTED {record['started_at']}: app and tutor stopped, PostgreSQL running; "
                  f"migration must begin by {md.stamp(now + CHECKPOINT)} (40-minute checkpoint), "
                  f"planned end by {md.stamp(now + DOWNTIME_LIMIT)} (60 minutes)")
            return 0

        record = open_window(cfg, args.window)
        if marker_path(cfg).exists():
            raise md.Refused("a migration was started in this window; the database may be migrated. DATABASE "
                             "RECOVERY DECISION REQUIRED (separate PO authorization); services stay stopped")
        live = md.read_live(cfg)
        if live[:2] != (record["state"], record["schema"]):
            raise md.Refused(f"live schema {live[0]} {live[1]} differs from the start of the window "
                             f"({record['state']} {record['schema']}); services stay stopped")
        image = md.current_image(cfg) or "none"
        if image != record["image"]:
            raise md.Refused(f"release.env changed during the window ({record['image']} -> {image})")
        error = md.compose_up(cfg, False)
        if not error:
            error = "" if md.wait_healthy(cfg, image) else "app or tutor not healthy in time"
            if not error and not md.smoke():
                error = "smoke test failed"
        downtime = round((md.utc_now() - md.parse_stamp(record["started_at"])).total_seconds() / 60, 1)
        if error:
            md.record_release(cfg, action="maintenance-end", result="FAILED", error=error, image=image, **refs)
            print(f"MAINTENANCE END FAILED: {error}; the window stays open ({downtime} min so far)")
            return 1
        archive(cfg, maintenance_path(cfg))
        md.record_release(cfg, action="maintenance-end", result="OK", image=image, downtime_minutes=str(downtime),
                          schema=f"{live[0]}:{live[1]}", **refs)
        print(f"MAINTENANCE ENDED: previous release {image} running and healthy, smoke passed; schema unchanged "
              f"({live[0]}); downtime {downtime} min")
        return 0


# ---------------------------------------------------------------- migrate (gate G2)

def run_migration(cfg: dict, ref: str, *args: str) -> dict:
    """`python -m app.writing.migrate` in a one-off app container of the target image (no ports, no restart)."""
    env_file = cfg["state"] / "migrate-target.env"
    env_file.write_text(f"MENTOR_PRO_IMAGE={ref}\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "MENTOR_PRO_IMAGE"}
    out = subprocess.run([*cfg["docker"], "compose", "-p", cfg["project"], "-f", str(cfg["compose"]), "--env-file",
                          str(env_file), "run", "--rm", "--no-deps", "-T", "app", "python", "-m",
                          "app.writing.migrate", *args], env=env, capture_output=True, text=True, timeout=7200)
    if out.returncode != 0:
        raise md.Refused(md.one_line(out.stderr or out.stdout))
    return json.loads(out.stdout)


def after_apply_failure(cfg: dict, args, refs: dict, failure: Failed, dump: Path) -> int:
    """No restore, no rollback: stop app and tutor, report, and leave the decision to the PO."""
    error = stop_services(cfg)
    live = md.read_live(cfg)
    md.record_release(cfg, action="migrate", result="FAILED", step=failure.step, error=failure.reason,
                      schema=f"{live[0]}:{live[1]}", services="stopped" if not error else error, **refs)
    print(f"MIGRATE FAILED at {failure.step}: {failure.reason}")
    print(f"app and tutor: {'stopped, and they stay stopped' if not error else error}; PostgreSQL running; "
          f"live schema {live[0]} {live[1] or '?'} ({live[2]})")
    print("No automatic database restore and no application rollback (PO decision); a pre-T036 image never runs "
          "on a migrated database. `maintenance end` is refused while state/migration.json exists.")
    print("DATABASE RECOVERY DECISION REQUIRED (separate PO authorization): restore the pre-migration backup "
          f"{dump.name} into a new database (ADR-030 section 6, G3), or a corrected forward deployment.")
    return 1


def migrate(args, cfg: dict) -> int:
    md.check_references(args.window, args.authorization)
    refs = {"window": args.window, "authorization": args.authorization, "authorization_verified": "no"}
    with md.deploy_lock(cfg):
        window = open_window(cfg, args.window)
        if marker_path(cfg).exists():
            raise md.Refused("a migration was already started in this window; DATABASE RECOVERY DECISION REQUIRED")
        started, now = md.parse_stamp(window["started_at"]), md.utc_now()
        writers = [f"{s} is running" for s in ("app", "tutor") if running(cfg, s)]
        if not writers and (n := psql(cfg, cfg["pg_container"], SESSIONS_SQL).strip()) != "0":
            writers.append(f"{n} other database session(s)")
        if writers:
            raise md.Refused("application writers active: " + "; ".join(writers))
        manifest, manifest_sha = md.load_manifest(Path(args.manifest), cfg["repository"])
        digest = manifest["image"]["digest"]
        ref = f"{cfg['repository']}@{digest}"
        declared = md.verify_release_image(cfg, manifest)
        live = md.read_live(cfg)
        md.require_ok_state(live)
        if live[:2] != ("legacy", "none"):
            raise md.Refused(f"live schema is {live[0]} {live[1]}: nothing to migrate (use deploy)")
        if md.compatibility(declared, "none") != "migration required" or \
                md.compatibility(declared, TARGET) != "compatible":
            raise md.Refused(f"image schema {declared[0]}..{declared[1]} does not need migration {TARGET}")
        dump = Path(args.backup)
        record = md.read_backup_record(dump)
        backup_sha = md.check_backup(dump, record, cfg["pg_db"], live, now)
        try:
            taken = md.parse_stamp(record.get("created", ""))
        except ValueError:
            raise md.Refused("backup record has no creation time") from None
        if taken < started:
            raise md.Refused("the backup was taken before the maintenance window started (services were running)")
        rehearsal = read_json(rehearsal_path(cfg, digest, backup_sha))
        check_rehearsal(rehearsal, digest, backup_sha, now, window)
        before_fp = psql(cfg, cfg["pg_container"], FINGERPRINT_SQL)
        if fingerprint_digest(before_fp) != record.get("fingerprint"):
            raise md.Refused("live data changed since the backup; take a new backup and rehearse again")
        before = counts(cfg, cfg["pg_container"])
        if before != rehearsal.get("counts_before"):
            raise md.Refused("live writing counts differ from the rehearsal")
        size = dump.stat().st_size
        problems = space_problems([("migration overhead", docker_root(cfg), restore_estimate(size)),
                                   ("margin", docker_root(cfg), MARGIN_BYTES + cfg["reserve"])])
        problems += window_problems(started, now, rehearsal.get("durations") or {})
        if problems:
            raise md.Refused("; ".join(problems))

        times: dict = {}
        print(f"migrating {cfg['pg_db']} to {TARGET} with {manifest['release']}; rehearsal "
              f"{rehearsal['finished_at']}, backup {dump.name}")
        try:
            with step("dry run", times):
                dry = run_migration(cfg, ref, "apply", "--dry-run")
                if dry.get("status") != "dry_run_rolled_back" or dry.get("attempts_created") != \
                        rehearsal.get("attempts_created"):
                    raise md.Refused(f"dry run differs from the rehearsal ({dry.get('status')}, "
                                     f"{dry.get('attempts_created')} attempts)")
            problems = window_problems(started, md.utc_now(), rehearsal.get("durations") or {})
            if problems:
                raise Failed("checkpoint", "; ".join(problems))
        except Failed as failure:
            unchanged = md.read_live(cfg)[:2] == ("legacy", "none") and \
                fingerprint_digest(psql(cfg, cfg["pg_container"], FINGERPRINT_SQL)) == record["fingerprint"]
            md.record_release(cfg, action="migrate", result="REFUSED", step=failure.step, error=failure.reason,
                              version=manifest["release"], image=ref, backup_sha256=backup_sha,
                              schema="legacy:none" if unchanged else "unknown", **refs)
            print(f"MIGRATE REFUSED before apply at {failure.step}: {failure.reason}")
            print("old schema unchanged (legacy, data fingerprint equal to the backup); app and tutor stay stopped "
                  "until `mentorpro maintenance end`" if unchanged else
                  "WARNING: the database no longer matches the backup; services stay stopped")
            return 1

        marker_path(cfg).write_text(json.dumps({"started_at": md.stamp(md.utc_now()), "digest": digest,
                                                "backup_sha256": backup_sha, **refs}, indent=1) + "\n",
                                    encoding="utf-8")
        try:
            with step("apply", times):
                report = run_migration(cfg, ref, "apply")
                problems = report_problems(report, before)
                if problems:
                    raise md.Refused("; ".join(problems))
            with step("verify", times):
                after_live = md.read_live(cfg)
                if after_live[:2] != ("current", TARGET):
                    raise md.Refused(f"schema after migration is {after_live[0]} {after_live[1]}")
                after = counts(cfg, cfg["pg_container"])
                attempts = counts(cfg, cfg["pg_container"], ATTEMPTS_SQL)
                problems = migration_problems(before, after, attempts)
                problems += scope_problems(before_fp, psql(cfg, cfg["pg_container"], FINGERPRINT_SQL))
                if (after, attempts) != (rehearsal.get("counts_after"), rehearsal.get("attempts")):
                    problems.append("migrated counts differ from the rehearsal")
                if problems:
                    raise md.Refused("; ".join(problems))
            with step("deploy", times):
                md.write_preflight(cfg, manifest, manifest_sha, after_live)
                if md.deploy_locked(args, cfg, backup_live=live, propose_rollback=False) != 0:
                    raise md.Refused("the deployment after the migration failed (see above)")
        except Failed as failure:
            return after_apply_failure(cfg, args, refs, failure, dump)
        except KeyboardInterrupt:
            return after_apply_failure(cfg, args, refs, Failed("interrupted", "operator interrupt"), dump)
        downtime = round((md.utc_now() - started).total_seconds() / 60, 1)
        archive(cfg, marker_path(cfg))
        archive(cfg, maintenance_path(cfg))
        md.record_release(cfg, action="migrate", result="OK", version=manifest["release"], image=ref,
                          schema=f"legacy:none->current:{TARGET}", backup_sha256=backup_sha,
                          attempts_created=str(report["attempts_created"]), downtime_minutes=str(downtime), **refs)
        print("durations (s): " + ", ".join(f"{k} {v}" for k, v in times.items()))
        print(f"MIGRATE OK: schema current {TARGET}, {report['attempts_created']} attempt-1 records, all writing "
              f"records and relationships kept, nothing changed outside the migration; {manifest['release']} "
              f"running; downtime {downtime} min (limit 60)")
        if downtime > DOWNTIME_LIMIT.total_seconds() / 60:
            print("WARNING: the downtime exceeded the 60-minute plan; report it to the PO")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mentorpro")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("rehearse")
    p.add_argument("manifest")
    p.add_argument("dump")
    for name in ("--window", "--authorization"):
        p.add_argument(name)
    p = sub.add_parser("maintenance")
    p.add_argument("action", choices=("start", "end"))
    for name in ("--window", "--authorization"):
        p.add_argument(name)
    p = sub.add_parser("migrate")
    p.add_argument("manifest")
    for name in ("--backup", "--window", "--authorization"):
        p.add_argument(name)
    args = parser.parse_args(argv)
    cfg = settings()
    try:
        if args.command == "migrate" and not args.backup:
            raise md.Refused("--backup <restore-verified dump taken in this window> is required")
        return {"rehearse": rehearse, "maintenance": maintenance, "migrate": migrate}[args.command](args, cfg)
    except md.Refused as exc:
        label = f"{args.command} {args.action}" if args.command == "maintenance" else args.command
        print(f"{label.upper()} REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
