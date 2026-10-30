"""Preflight, deploy and rollback by digest (T044, ADR-033 increment I4). Run through `deploy/mentorpro`.

    deploy/mentorpro preflight <manifest.json>
    deploy/mentorpro deploy <manifest.json> --backup <dump> --window <ref> --authorization <ref>
    deploy/mentorpro rollback [--to <version>] --backup <dump> --window <ref> --authorization <ref>
    deploy/mentorpro adopt-legacy --window <ref> --authorization <ref>   (once: the pre-script image)

Standard library only (the server needs python3, Docker and the compose plugin; no GitHub credential). The
manifest is the GitHub Release asset, downloaded by the operator and passed as a local file.

Rules (PO, 2026-10-28):
- the image is chosen by digest only, never by a tag; the version tag is read only to prove it maps to the digest;
- the live writing schema is read from PostgreSQL, read-only, never from the target image; fresh, legacy, current,
  drifted, corrupt and unreadable are distinct, and only fresh, legacy and current can pass;
- an image runs only when schema.min <= live schema <= schema.max (images without labels: none..none);
- deploy needs a preflight record and a verified backup record, both for this deployment and at most six hours
  old; compatibility is checked again inside the lock just before any container changes;
- deploy and rollback touch only the app and tutor containers and release.env; never PostgreSQL, its volume,
  network or migrations; there is no automatic rollback;
- window and authorization references are recorded as given; the script cannot prove a PO approval.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVIDENCE_MAX_AGE = timedelta(hours=6)  # PO decision 4: fixed, not configurable
CLOCK_SKEW = timedelta(minutes=5)
PUBLISHED = "Published, not authorized for deployment"
# Writing migrations in order; must equal app.writing.migrations.MIGRATIONS (checked by the tests).
KNOWN_MIGRATIONS = ("0001_student_attempts",)
OK_STATES = ("fresh", "legacy", "current")
LABEL_MIN, LABEL_MAX = "io.mentorpro.schema.min", "io.mentorpro.schema.max"
ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json"])


class Refused(Exception):
    """A check failed; nothing has been changed."""


def env(name: str, default: str) -> str:
    return os.environ.get(name) or default


def settings() -> dict:
    return {
        "repository": env("MENTORPRO_REPOSITORY", "ghcr.io/jonnabio/mentor-pro"),
        "release_env": Path(env("MENTORPRO_RELEASE_ENV", "/opt/mentor-pro/release.env")),
        "releases": Path(env("MENTORPRO_RELEASES", "/opt/mentor-pro/RELEASES")),
        "state": Path(env("MENTORPRO_STATE", "/opt/mentor-pro/state")),
        "compose": Path(env("MENTORPRO_COMPOSE", str(HERE / "compose.yml"))),
        "project": env("MENTORPRO_PROJECT", "mentor-pro"),
        "pg_container": env("MENTORPRO_POSTGRES_CONTAINER", "mentor-pro-postgres-1"),
        "pg_user": env("MENTORPRO_POSTGRES_USER", "mentor_pro_admin"),
        "pg_db": env("MENTORPRO_POSTGRES_DB", "mentor_pro"),
        "docker": shlex.split(env("MENTORPRO_DOCKER", "docker")),
        "health_timeout": int(env("MENTORPRO_HEALTH_TIMEOUT", "180")),
    }


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def fresh_enough(at: datetime, now: datetime, what: str) -> None:
    if at > now + CLOCK_SKEW:
        raise Refused(f"{what} is dated in the future ({stamp(at)})")
    if now - at > EVIDENCE_MAX_AGE:
        raise Refused(f"{what} is older than six hours ({stamp(at)}); run it again")


# ---------------------------------------------------------------- manifest

def validate_manifest(data: object, repository: str) -> list[str]:
    """The rules of docs/release/manifest.schema.json for a published release, without jsonschema."""
    if not isinstance(data, dict):
        return ["manifest is not a JSON object"]
    problems = []
    keys = {"manifest_version", "release", "dry_run", "status", "image", "commit", "ci_run", "created", "schema",
            "smoke"}
    if set(data) != keys:
        problems.append(f"fields differ from the manifest schema: {sorted(set(data) ^ keys)}")
    if data.get("dry_run") is not False:
        problems.append("dry-run manifest: not a published release")
    if data.get("manifest_version") != 1:
        problems.append("manifest_version is not 1")
    if data.get("status") != PUBLISHED:
        problems.append(f"status is not {PUBLISHED!r}")
    if not re.fullmatch(r"v\d{4}\.\d{2}\.\d{2}-\d+", str(data.get("release"))):
        problems.append("release is not vYYYY.MM.DD-N")
    image = data.get("image") if isinstance(data.get("image"), dict) else {}
    if image.get("repository") != repository:
        problems.append(f"image repository is not {repository}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image.get("digest"))):
        problems.append("image digest is missing or malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", str(data.get("commit"))):
        problems.append("commit is not a full SHA")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", str(data.get("created"))):
        problems.append("created is not a UTC timestamp")
    schema = data.get("schema") if isinstance(data.get("schema"), dict) else {}
    low, high = schema.get("min"), schema.get("max")
    if not (isinstance(low, str) and isinstance(high, str) and re.fullmatch(r"\d{4}", low)
            and re.fullmatch(r"\d{4}", high) and low <= high):
        problems.append("schema range is missing, malformed or empty")
    if data.get("smoke") != {"student": "pass", "tutor": "pass"}:
        problems.append("smoke tests did not pass")
    return problems


def load_manifest(path: Path, repository: str) -> tuple[dict, str]:
    """(manifest, sha256 of the file bytes); refuses anything that is not a valid published manifest."""
    try:
        raw = path.read_bytes()
        data = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refused(f"manifest not readable as JSON: {exc}") from None
    problems = validate_manifest(data, repository)
    if problems:
        raise Refused("invalid manifest: " + "; ".join(problems))
    return data, hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- live schema (read-only, never via the image)

SCHEMA_SQL = r"""SET default_transaction_read_only = on;
SELECT to_regclass('writing.draft') IS NOT NULL AS d, to_regclass('writing.schema_migration') IS NOT NULL AS l,
       to_regclass('writing.uq_submission_exercise') IS NOT NULL AS u \gset
\if :l
SELECT :'d' || '|' || :'l' || '|' || :'u' || '|' || coalesce(string_agg(migration_id, ',' ORDER BY migration_id), '')
  FROM writing.schema_migration;
\else
SELECT :'d' || '|' || :'l' || '|' || :'u' || '|';
\endif
"""


def classify(answer: str) -> tuple[str, str, str]:
    """(state, live schema, detail) from the one-line answer of SCHEMA_SQL.

    fresh/legacy -> schema 'none'; current -> the last migration number; drifted, corrupt and unreadable can
    never pass a check."""
    lines = [line for line in answer.replace("\r", "").split("\n") if line.strip()]
    if len(lines) != 1 or not re.fullmatch(r"[tf]\|[tf]\|[tf]\|[0-9a-z_,]*", lines[0]):
        return "unreadable", "", "unexpected answer from PostgreSQL"
    draft, ledger, unique, ids = lines[0].split("|")
    applied = [i for i in ids.split(",") if i]
    if ledger == "f":
        if unique == "t" and draft == "f":
            return "corrupt", "", "uq_submission_exercise exists without writing tables"
        return ("legacy", "none", "writing tables without migration ledger") if draft == "t" else \
            ("fresh", "none", "no writing tables")
    if draft == "f":
        return "corrupt", "", "migration ledger without writing tables"
    if not applied:
        return "corrupt", "", "migration ledger is empty"
    if tuple(applied) != KNOWN_MIGRATIONS[:len(applied)]:
        return "corrupt", "", f"unexpected migration ledger entries: {','.join(applied)}"
    if unique == "t":
        return "drifted", "", "uq_submission_exercise recreated after migration (run `migrate repair`, G3)"
    return "current", applied[-1][:4], f"migrations {','.join(applied)}"


def read_live(cfg: dict) -> tuple[str, str, str]:
    cmd = [*cfg["docker"], "exec", "-i", cfg["pg_container"], "psql", "-U", cfg["pg_user"], "-d", cfg["pg_db"],
           "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"]
    try:
        out = subprocess.run(cmd, input=SCHEMA_SQL, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return "unreadable", "", "PostgreSQL container not reachable"
    if out.returncode != 0:
        return "unreadable", "", "PostgreSQL did not answer the schema query"
    return classify(out.stdout)


def require_ok_state(live: tuple[str, str, str]) -> None:
    state, _, detail = live
    if state not in OK_STATES:
        raise Refused(f"database schema {state}: {detail}")


# ---------------------------------------------------------------- compatibility

def rank(schema: str) -> int:
    return -1 if schema == "none" else int(schema)


def image_range(labels: dict | None) -> tuple[str, str]:
    """Supported schema range from OCI labels; an image without both labels is pre-T036 (none..none)."""
    labels = labels or {}
    low, high = labels.get(LABEL_MIN), labels.get(LABEL_MAX)
    if low is None and high is None:
        return "none", "none"
    if not (low and high and re.fullmatch(r"\d{4}", low) and re.fullmatch(r"\d{4}", high) and low <= high):
        raise Refused(f"image schema labels are inconsistent: min={low!r} max={high!r}")
    return low, high


def compatibility(declared: tuple[str, str], live_schema: str) -> str:
    """'compatible', 'migration required' (image newer than the database) or 'incompatible' (image older)."""
    low, high = declared
    if rank(live_schema) < rank(low):
        return "migration required"
    if rank(live_schema) > rank(high):
        return "incompatible"
    return "compatible"


# ---------------------------------------------------------------- registry and image identity

def _get(url: str, headers: dict) -> tuple[bytes, dict]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as answer:
        return answer.read(), dict(answer.headers)


def registry_manifest(repository: str, reference: str) -> bytes:
    """Raw manifest bytes for a tag or digest; anonymous bearer token when the registry asks for one."""
    host, name = repository.split("/", 1)
    scheme = "http" if re.match(r"(localhost|127\.0\.0\.1)(:\d+)?$", host) else "https"
    url = f"{scheme}://{host}/v2/{name}/manifests/{reference}"
    headers = {"Accept": ACCEPT}
    try:
        return _get(url, headers)[0]
    except urllib.error.HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "") if exc.code == 401 else ""
        if not challenge.lower().startswith("bearer "):
            raise Refused(f"registry answered {exc.code} for {repository}:{reference}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise Refused(f"registry not reachable for {repository}:{reference}: {exc}") from None
    params = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    query = "&".join(f"{k}={params[k]}" for k in ("service", "scope") if k in params)
    try:
        token = json.loads(_get(f"{params['realm']}?{query}", {})[0])
        headers["Authorization"] = "Bearer " + (token.get("token") or token.get("access_token") or "")
        return _get(url, headers)[0]
    except (KeyError, ValueError, urllib.error.URLError) as exc:
        raise Refused(f"registry not readable without credentials for {repository}:{reference}: {exc}") from None


def content_digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def docker(cfg: dict, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    out = subprocess.run([*cfg["docker"], *args], capture_output=True, text=True, timeout=600)
    if check and out.returncode != 0:
        raise Refused(f"docker {args[0]} failed: {out.stderr.strip()[:300]}")
    return out


def pull_and_inspect(cfg: dict, ref: str, digest: str) -> dict:
    """Pull by digest; the local image must carry exactly that repository digest. Returns its labels."""
    try:
        docker(cfg, "pull", "-q", ref)
    except Refused:
        if docker(cfg, "image", "inspect", ref, check=False).returncode != 0:
            raise
    info = json.loads(docker(cfg, "image", "inspect", ref).stdout)[0]
    repository = ref.split("@", 1)[0]
    if f"{repository}@{digest}" not in (info.get("RepoDigests") or []):
        raise Refused(f"pulled image does not carry repository digest {digest}")
    return (info.get("Config") or {}).get("Labels") or {}


def verify_release_image(cfg: dict, manifest: dict) -> tuple[str, str]:
    """Registry digest, version-tag mapping, commit and labels; returns the declared schema range."""
    repository, digest = manifest["image"]["repository"], manifest["image"]["digest"]
    if content_digest(registry_manifest(repository, digest)) != digest:
        raise Refused("registry content does not hash to the manifest digest")
    tagged = content_digest(registry_manifest(repository, manifest["release"]))
    if tagged != digest:
        raise Refused(f"tag {manifest['release']} points to {tagged}, the manifest names {digest} (retagged?)")
    labels = pull_and_inspect(cfg, f"{repository}@{digest}", digest)
    expected = {"org.opencontainers.image.version": manifest["release"],
                "org.opencontainers.image.revision": manifest["commit"],
                "org.opencontainers.image.created": manifest["created"],
                LABEL_MIN: manifest["schema"]["min"], LABEL_MAX: manifest["schema"]["max"]}
    wrong = [f"{k}={labels.get(k)!r} (manifest {v!r})" for k, v in expected.items() if labels.get(k) != v]
    if wrong:
        raise Refused("image labels differ from the manifest: " + "; ".join(wrong))
    return image_range(labels)


# ---------------------------------------------------------------- evidence records

def preflight_path(cfg: dict, digest: str) -> Path:
    return cfg["state"] / "preflight" / (digest.split(":", 1)[1] + ".json")


def check_preflight(record: dict | None, digest: str, manifest_sha: str, live: tuple, now: datetime) -> None:
    if not record:
        raise Refused("no preflight record for this digest; run `mentorpro preflight <manifest>` first")
    if record.get("result") != "DEPLOY COMPATIBLE":
        raise Refused(f"preflight result was {record.get('result')!r}")
    if record.get("digest") != digest or record.get("manifest_sha256") != manifest_sha:
        raise Refused("preflight record is for another digest or manifest file")
    if (record.get("state"), record.get("schema")) != live[:2]:
        raise Refused(f"live schema changed since preflight ({record.get('state')} -> {live[0]})")
    try:
        checked = parse_stamp(record.get("checked_at", ""))
    except ValueError:
        raise Refused("preflight record has no valid timestamp") from None
    fresh_enough(checked, now, "preflight")


def read_backup_record(dump: Path) -> dict:
    record = Path(str(dump) + ".verify")
    try:
        lines = record.read_text(encoding="utf-8").splitlines()
    except OSError:
        raise Refused(f"backup record {record} is missing or not readable") from None
    fields: dict = {"reverified": []}
    for line in lines:
        key, _, value = line.partition(" ")
        if key == "reverified":
            fields["reverified"].append(value)
        elif key in ("database", "sha256", "schema_state", "verified", "result", "created", "fingerprint"):
            fields[key] = value  # the last one counts
    return fields


def check_backup(dump: Path, record: dict, database: str, live: tuple, now: datetime) -> str:
    """Binds a restore-verified backup to this deployment; returns the archive sha256."""
    if record.get("result") != "BACKUP OK":
        raise Refused(f"backup result is {record.get('result')!r}, not BACKUP OK")
    if record.get("database") != database:
        raise Refused(f"backup is of database {record.get('database')!r}, not {database!r}")
    if record.get("schema_state") != f"{live[0]} {live[1]}":
        raise Refused(f"backup schema state {record.get('schema_state')!r} differs from live '{live[0]} {live[1]}'")
    times = [record.get("verified", "")]
    for entry in record["reverified"]:
        at, _, outcome = entry.partition(" ")
        if outcome != "OK":
            raise Refused(f"backup failed a later verification ({entry})")
        times.append(at)
    try:
        newest = max(parse_stamp(t) for t in times if t)
    except ValueError:
        raise Refused("backup record has no valid verification timestamp") from None
    fresh_enough(newest, now, "backup verification")
    try:
        with dump.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else \
                hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        raise Refused(f"backup archive {dump} is not readable") from None
    if actual != record.get("sha256"):
        raise Refused("backup archive checksum differs from its record")
    return actual


REF = re.compile(r"[\w.:/#@+-]{1,200}")


def check_references(window: str | None, authorization: str | None) -> None:
    for name, value in (("--window", window), ("--authorization", authorization)):
        if not value or not REF.fullmatch(value):
            raise Refused(f"{name} reference is required (1-200 characters, no spaces)")


# ---------------------------------------------------------------- state, lock and records

_LOCK_DEPTH = [0]  # re-entrant within one process: `migrate` (I5) runs the deploy path under its own lock


@contextlib.contextmanager
def deploy_lock(cfg: dict):
    if _LOCK_DEPTH[0]:
        _LOCK_DEPTH[0] += 1
        try:
            yield
        finally:
            _LOCK_DEPTH[0] -= 1
        return
    cfg["state"].mkdir(parents=True, exist_ok=True)
    handle = open(cfg["state"] / "deploy.lock", "a+")
    try:
        try:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:  # Windows (tests only)
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise Refused("another deploy or rollback holds the lock; nothing changed") from None
    _LOCK_DEPTH[0] = 1
    try:
        yield
    finally:
        _LOCK_DEPTH[0] = 0
        handle.close()


def operator() -> str:
    return os.environ.get("SUDO_USER") or getpass.getuser()


def record_release(cfg: dict, **fields: str) -> None:
    line = "\t".join(["mentorpro", f"time={stamp(utc_now())}", f"operator={operator()}"] +
                     [f"{k}={v}" for k, v in fields.items()])
    with cfg["releases"].open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def current_image(cfg: dict) -> str | None:
    try:
        for line in cfg["release_env"].read_text(encoding="utf-8").splitlines():
            if line.startswith("MENTOR_PRO_IMAGE="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def previous_image(cfg: dict) -> str | None:
    path = Path(str(cfg["release_env"]) + ".previous")
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("MENTOR_PRO_IMAGE="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


def write_release_env(cfg: dict, ref: str) -> None:
    """Atomic replace; the configuration it replaces is kept as release.env.previous and in state/history."""
    target = cfg["release_env"]
    old = target.read_text(encoding="utf-8") if target.exists() else None
    new = f"MENTOR_PRO_IMAGE={ref}\n"
    if old == new:
        return
    if old is not None:
        history = cfg["state"] / "history"
        history.mkdir(parents=True, exist_ok=True)
        (history / f"release.env.{utc_now().strftime('%Y%m%dT%H%M%SZ')}.{os.getpid()}").write_text(old, "utf-8")
        Path(str(target) + ".previous").write_text(old, encoding="utf-8")
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    os.replace(tmp, target)


def container(cfg: dict, service: str) -> str:
    return f"{cfg['project']}-{service}-1"


def running_healthy(cfg: dict, ref: str) -> bool:
    for service in ("app", "tutor"):
        out = docker(cfg, "inspect", container(cfg, service), "--format",
                     "{{.Config.Image}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
                     check=False)
        if out.returncode != 0 or out.stdout.split() != [ref, "running", "healthy"]:
            return False
    return True


def wait_healthy(cfg: dict, ref: str) -> bool:
    deadline = time.monotonic() + cfg["health_timeout"]
    while time.monotonic() < deadline:
        if running_healthy(cfg, ref):
            return True
        time.sleep(2)
    return False


def smoke() -> bool:
    out = subprocess.run([shutil.which("sh") or "sh", str(HERE / "mentorpro"), "smoke"], capture_output=True,
                         text=True, timeout=120)
    print(out.stdout.rstrip())
    return out.returncode == 0


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:300]


def compose_up(cfg: dict, recreate: bool) -> str:
    """Empty on success, otherwise a one-line error; a failed compose is never reported as a deployment."""
    env = {k: v for k, v in os.environ.items() if k != "MENTOR_PRO_IMAGE"}  # release.env is the only source
    cmd = [*cfg["docker"], "compose", "-p", cfg["project"], "-f", str(cfg["compose"]), "--env-file",
           str(cfg["release_env"]), "up", "-d", "--no-deps", *(["--force-recreate"] if recreate else []),
           "app", "tutor"]
    try:
        out = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return one_line(f"compose up did not run: {exc}")
    if out.returncode != 0:
        return one_line(f"compose up exited {out.returncode}: {out.stderr.strip() or out.stdout.strip()}")
    return ""


# ---------------------------------------------------------------- commands

def preflight(args, cfg: dict) -> int:
    manifest, manifest_sha = load_manifest(Path(args.manifest), cfg["repository"])
    digest = manifest["image"]["digest"]
    declared = verify_release_image(cfg, manifest)
    print(f"image {manifest['image']['repository']}@{digest}")
    print(f"release {manifest['release']} commit {manifest['commit']} schema {declared[0]}..{declared[1]}")
    live = read_live(cfg)
    print(f"live database: {live[0]} (schema {live[1] or '?'}; {live[2]})")
    require_ok_state(live)
    verdict = compatibility(declared, live[1])
    if verdict == "migration required":
        print("MIGRATION REQUIRED: the image needs a newer schema; G2 migration (I5) is not part of deploy")
        return 1
    if verdict == "incompatible":
        print("REFUSED: the image cannot run on the live schema")
        return 1
    path = write_preflight(cfg, manifest, manifest_sha, live)
    print(f"PREFLIGHT OK: DEPLOY COMPATIBLE (record {path}, valid six hours)")
    return 0


def write_preflight(cfg: dict, manifest: dict, manifest_sha: str, live: tuple) -> Path:
    """Only after the identity and compatibility checks passed."""
    path = preflight_path(cfg, manifest["image"]["digest"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"digest": manifest["image"]["digest"], "release": manifest["release"],
                                "commit": manifest["commit"], "manifest_sha256": manifest_sha, "state": live[0],
                                "schema": live[1], "checked_at": stamp(utc_now()), "result": "DEPLOY COMPATIBLE"},
                               indent=1) + "\n", encoding="utf-8")
    return path


def change(cfg: dict, args, action: str, ref: str, version: str, live: tuple, backup_sha: str,
           propose_rollback: bool = True) -> int:
    """The only code that changes containers: release.env, then app and tutor. Never PostgreSQL."""
    common = {"action": action, "version": version, "image": ref, "schema": f"{live[0]}:{live[1]}",
              "backup_sha256": backup_sha, "window": args.window, "authorization": args.authorization,
              "authorization_verified": "no"}
    if current_image(cfg) == ref and running_healthy(cfg, ref):
        if smoke():
            record_release(cfg, result="UNCHANGED", **common)
            print(f"UNCHANGED: {version} is already running and healthy; nothing changed")
            return 0
    recreate = current_image(cfg) == ref
    before = current_image(cfg)
    common["previous"] = before or "none"
    write_release_env(cfg, ref)
    error = compose_up(cfg, recreate)
    if not error:
        healthy = wait_healthy(cfg, ref)
        if healthy and smoke():
            record_release(cfg, result="OK", **common)
            print(f"{action.upper()} OK: {version} running and healthy, smoke passed")
            return 0
        error = "smoke test failed" if healthy else "app or tutor not healthy in time"
    record_release(cfg, result="FAILED", error=error, **common)
    print(f"{action.upper()} FAILED: {error}")
    print("No automatic rollback (PO decision). release.env.previous holds the earlier configuration"
          f" ({before or 'none'}).")
    if propose_rollback:
        print("PROPOSED MANUAL ROLLBACK (not executed):")
        print("  deploy/mentorpro rollback --backup <verified dump> --window <ref> --authorization <ref>")
    return 1


def deploy(args, cfg: dict) -> int:
    check_references(args.window, args.authorization)
    with deploy_lock(cfg):
        return deploy_locked(args, cfg)


def deploy_locked(args, cfg: dict, backup_live: tuple | None = None, propose_rollback: bool = True) -> int:
    """The deploy checks and change; the caller holds the lock. `migrate` (I5) passes the pre-migration schema its
    backup was taken on, and no rollback proposal (an application rollback across a migration is refused)."""
    manifest, manifest_sha = load_manifest(Path(args.manifest), cfg["repository"])
    digest = manifest["image"]["digest"]
    ref = f"{cfg['repository']}@{digest}"
    try:
        record = json.loads(preflight_path(cfg, digest).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    now = utc_now()
    live = read_live(cfg)  # inside the lock, immediately before any change
    require_ok_state(live)
    check_preflight(record, digest, manifest_sha, live, now)
    # Final identity check under the lock: a preflight record alone never authorizes a deployment when the
    # registry content, the version tag, the labels or the commit changed since.
    verdict = compatibility(verify_release_image(cfg, manifest), live[1])
    if verdict != "compatible":
        raise Refused(f"{verdict} on live schema {live[1]}")
    backup_sha = check_backup(Path(args.backup), read_backup_record(Path(args.backup)), cfg["pg_db"],
                              backup_live or live, now)
    manifests = cfg["state"] / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    (manifests / f"{manifest['release']}.json").write_bytes(Path(args.manifest).read_bytes())
    return change(cfg, args, "deploy", ref, manifest["release"], live, backup_sha, propose_rollback)


def stored_manifest(cfg: dict, version: str | None = None, digest: str | None = None) -> tuple[dict, str] | None:
    folder = cfg["state"] / "manifests"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data, sha = load_manifest(path, cfg["repository"])
        except Refused:
            continue
        if (version and data["release"] == version) or (digest and data["image"]["digest"] == digest):
            return data, sha
    return None


def releases(cfg: dict) -> list[dict]:
    """The RELEASES lines written by this script; hand-written lines are ignored."""
    try:
        text = cfg["releases"].read_text(encoding="utf-8")
    except OSError:
        return []
    return [dict(f.split("=", 1) for f in line.split("\t")[1:] if "=" in f)
            for line in text.splitlines() if line.startswith("mentorpro\t")]


def legacy_path(cfg: dict, digest: str) -> Path:
    return cfg["state"] / "legacy" / (digest.split(":", 1)[1] + ".json")


def provenance(cfg: dict, ref: str) -> tuple[str, dict]:
    """Why a rollback target can be trusted: ('manifest', manifest) for a stored, valid release manifest, or
    ('legacy', record) for the pre-script image captured by `adopt-legacy`. Either way it must have run
    successfully here before (an OK or UNCHANGED line in RELEASES). Anything else is refused."""
    match = re.fullmatch(r"(.+)@(sha256:[0-9a-f]{64})", ref)
    if not match or match.group(1) != cfg["repository"]:
        raise Refused(f"rollback target is not a {cfg['repository']} image pinned by digest: {ref}")
    if not any(r.get("image") == ref and r.get("result") in ("OK", "UNCHANGED") for r in releases(cfg)):
        raise Refused(f"{ref} never ran successfully under this script (no OK record in RELEASES); "
                      "choose a known-good release with --to <version>")
    found = stored_manifest(cfg, digest=match.group(2))
    if found:
        return "manifest", found[0]
    try:
        record = json.loads(legacy_path(cfg, match.group(2)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = None
    if record and record.get("image") == ref and record.get("verified") == "running":
        return "legacy", record
    raise Refused(f"no provenance for {ref}: neither a stored release manifest nor an adopted legacy record")


def adopt_legacy(args, cfg: dict) -> int:
    """Once, before the first scripted deployment: record the image running now as a rollback candidate.

    release.env must pin it by digest, app and tutor must both run exactly it and be healthy, and the local image
    must carry that repository digest. Changes no container."""
    check_references(args.window, args.authorization)
    with deploy_lock(cfg):
        ref = current_image(cfg) or ""
        match = re.fullmatch(r"(.+)@(sha256:[0-9a-f]{64})", ref)
        if not match or match.group(1) != cfg["repository"]:
            raise Refused(f"release.env does not pin a {cfg['repository']} image by digest: {ref or 'none'}")
        if stored_manifest(cfg, digest=match.group(2)):
            raise Refused("this image is a published release; it needs no legacy adoption")
        if not running_healthy(cfg, ref):
            raise Refused("app and tutor are not both running this image and healthy")
        declared = image_range(pull_and_inspect(cfg, ref, match.group(2)))
        path = legacy_path(cfg, match.group(2))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"image": ref, "verified": "running", "schema": list(declared),
                                    "adopted_at": stamp(utc_now()), "operator": operator(),
                                    "window": args.window, "authorization": args.authorization}, indent=1) + "\n",
                        encoding="utf-8")
        record_release(cfg, action="adopt-legacy", result="OK", version="legacy", image=ref,
                       schema=f"{declared[0]}..{declared[1]}", window=args.window,
                       authorization=args.authorization, authorization_verified="no")
        print(f"ADOPTED legacy rollback candidate {ref} (schema {declared[0]}..{declared[1]}); nothing changed")
        return 0


def rollback(args, cfg: dict) -> int:
    check_references(args.window, args.authorization)
    with deploy_lock(cfg):
        if args.to:
            found = stored_manifest(cfg, version=args.to)
            if not found:
                raise Refused(f"no stored manifest for {args.to}; only releases deployed by this script")
            ref = f"{cfg['repository']}@{found[0]['image']['digest']}"
        else:
            ref = previous_image(cfg) or ""
            if not ref:
                raise Refused("no previous configuration (release.env.previous) to roll back to")
        if ref == current_image(cfg):
            raise Refused("the rollback target is the configuration already in release.env")
        kind, source = provenance(cfg, ref)
        if kind == "manifest":
            declared = verify_release_image(cfg, source)
            version = source["release"]
        else:
            declared = image_range(pull_and_inspect(cfg, ref, ref.rsplit("@", 1)[1]))
            if list(declared) != source.get("schema"):
                raise Refused("legacy image labels differ from what was adopted")
            version = "legacy"
        live = read_live(cfg)
        require_ok_state(live)
        verdict = compatibility(declared, live[1])
        print(f"rollback target {version} {ref} schema {declared[0]}..{declared[1]}; live {live[0]} {live[1]}")
        if verdict != "compatible":
            record_release(cfg, action="rollback", result="REFUSED", version=version, image=ref,
                           schema=f"{live[0]}:{live[1]}", window=args.window, authorization=args.authorization,
                           authorization_verified="no")
            print(f"ROLLBACK REFUSED: {verdict} (image {declared[0]}..{declared[1]}, live {live[1]}). "
                  "Nothing changed. Crossing a migration is a database restore into a new database "
                  "(ADR-030 section 6, G3, PO approval), never an application rollback.")
            return 1
        backup_sha = check_backup(Path(args.backup), read_backup_record(Path(args.backup)), cfg["pg_db"], live,
                                  utc_now())
        return change(cfg, args, "rollback", ref, version, live, backup_sha)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mentorpro")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("manifest")
    p = sub.add_parser("deploy")
    p.add_argument("manifest")
    for name in ("--backup", "--window", "--authorization"):
        p.add_argument(name)
    p = sub.add_parser("rollback")
    p.add_argument("--to")
    for name in ("--backup", "--window", "--authorization"):
        p.add_argument(name)
    p = sub.add_parser("adopt-legacy")
    for name in ("--window", "--authorization"):
        p.add_argument(name)
    sub.add_parser("schema-sql")
    sub.add_parser("classify")
    args = parser.parse_args(argv)
    if args.command == "schema-sql":
        sys.stdout.write(SCHEMA_SQL)
        return 0
    if args.command == "classify":  # used by `mentorpro backup` to record the schema state
        state, schema, _ = classify(sys.stdin.read())
        print(f"{state} {schema or '-'}")
        return 0
    cfg = settings()
    try:
        if args.command in ("deploy", "rollback") and not args.backup:
            raise Refused("--backup <restore-verified dump> is required")
        return {"preflight": preflight, "deploy": deploy, "rollback": rollback,
                "adopt-legacy": adopt_legacy}[args.command](args, cfg)
    except Refused as exc:
        print(f"{args.command.upper()} REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
