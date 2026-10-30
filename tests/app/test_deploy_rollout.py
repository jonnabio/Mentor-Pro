"""Preflight, deploy and rollback by digest (T044, ADR-033 increment I4).

Unit tests of the rules (schema states, compatibility, manifests, evidence, references, lock, release.env) need
neither Docker nor a server. The Docker test runs the whole cycle on synthetic images in a temporary local
registry and an isolated compose project named mentorpro-i4test-<id>; it never names a production resource.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.writing import migrations

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "deploy"))
sys.path.insert(0, str(REPO / "scripts" / "release"))
import mentorpro_deploy as md  # noqa: E402
import release  # noqa: E402

SCRIPT = REPO / "deploy" / "mentorpro"
HELPER = (REPO / "deploy" / "mentorpro_deploy.py").read_text(encoding="utf-8")
SH = shutil.which("sh")
REPOSITORY = "ghcr.io/jonnabio/mentor-pro"
SHA = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "sha256:" + "a" * 64
NOW = datetime(2026, 11, 2, 15, 0, 0, tzinfo=timezone.utc)
CURRENT = ("current", "0001", "")
LEGACY = ("legacy", "none", "")


def _posix(path):
    return Path(path).as_posix()


# ------------------------------------------------------------------ live schema states

def test_known_migrations_follow_the_application():
    assert md.KNOWN_MIGRATIONS == migrations.MIGRATIONS


@pytest.mark.parametrize("answer, state, schema", [
    ("f|f|f|\n", "fresh", "none"),
    ("t|f|f|\n", "legacy", "none"),
    ("t|f|t|\n", "legacy", "none"),  # pre-T036 database: the old unique index is expected
    ("t|t|f|0001_student_attempts\r\n", "current", "0001"),
    ("t|t|t|0001_student_attempts\n", "drifted", ""),
    ("t|t|f|\n", "corrupt", ""),  # empty ledger
    ("t|t|f|0002_future\n", "corrupt", ""),  # unknown migration
    ("t|t|f|0001_student_attempts,0002_future\n", "corrupt", ""),
    ("f|t|f|0001_student_attempts\n", "corrupt", ""),  # ledger without tables
    ("f|f|t|\n", "corrupt", ""),
    ("", "unreadable", ""),
    ("ERROR: permission denied\n", "unreadable", ""),
    ("t|f|f|\nt|f|f|\n", "unreadable", ""),
])
def test_schema_states(answer, state, schema):
    assert md.classify(answer)[:2] == (state, schema)


@pytest.mark.parametrize("state", ["drifted", "corrupt", "unreadable"])
def test_only_fresh_legacy_and_current_can_pass(state):
    with pytest.raises(md.Refused):
        md.require_ok_state((state, "", "detail"))
    for ok in md.OK_STATES:
        md.require_ok_state((ok, "none", ""))


def test_schema_query_is_read_only():
    assert md.SCHEMA_SQL.startswith("SET default_transaction_read_only = on;")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)\b", md.SCHEMA_SQL, re.I)


# ------------------------------------------------------------------ compatibility

@pytest.mark.parametrize("declared, live, verdict", [
    (("none", "none"), "none", "compatible"),  # pre-T036 image on a legacy database
    (("none", "none"), "0001", "incompatible"),  # rollback across migration 0001
    (("0001", "0001"), "none", "migration required"),
    (("0001", "0001"), "0001", "compatible"),
    (("0001", "0002"), "0001", "compatible"),
])
def test_compatibility(declared, live, verdict):
    assert md.compatibility(declared, live) == verdict


def test_image_range_from_labels():
    assert md.image_range(None) == ("none", "none") == md.image_range({"other": "x"})
    assert md.image_range({md.LABEL_MIN: "0001", md.LABEL_MAX: "0001"}) == ("0001", "0001")
    for broken in ({md.LABEL_MIN: "0001"}, {md.LABEL_MIN: "0002", md.LABEL_MAX: "0001"},
                   {md.LABEL_MIN: "x", md.LABEL_MAX: "0001"}):
        with pytest.raises(md.Refused):
            md.image_range(broken)


# ------------------------------------------------------------------ manifests

def manifest(**change):
    data = release.manifest("v2026.11.02-1", SHA, "7", "2026-11-02T15:04:05Z", digest=DIGEST)
    data.update(change)
    return data


def test_published_manifest_is_accepted():
    assert md.validate_manifest(manifest(), REPOSITORY) == []


@pytest.mark.parametrize("data, expected", [
    (release.manifest("dev-0123456", SHA, "7", "2026-11-02T15:04:05Z", image_id=DIGEST, dry_run=True), "dry-run"),
    (manifest(status="Published"), "status"),
    (manifest(commit="abc"), "commit"),
    (manifest(extra=1), "fields"),
    (manifest(schema={"min": "0002", "max": "0001"}), "schema range"),
    (manifest(smoke={"student": "pass", "tutor": "fail"}), "smoke"),
    (manifest(image={"repository": REPOSITORY, "digest": "sha256:abc", "image_id": None}), "digest"),
    (manifest(image={"repository": "ghcr.io/other/mentor-pro", "digest": DIGEST, "image_id": None}), "repository"),
    ([], "not a JSON object"),
])
def test_invalid_manifests_are_refused(data, expected):
    problems = md.validate_manifest(data, REPOSITORY)
    assert problems and any(expected in p for p in problems), problems


def test_unreadable_manifest_file_is_refused(tmp_path):
    bad = tmp_path / "m.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(md.Refused, match="JSON"):
        md.load_manifest(bad, REPOSITORY)
    good = tmp_path / "ok.json"
    good.write_text(json.dumps(manifest()), encoding="utf-8")
    assert md.load_manifest(good, REPOSITORY)[1] == hashlib.sha256(good.read_bytes()).hexdigest()


# ------------------------------------------------------------------ evidence

def preflight_record(**change):
    record = {"digest": DIGEST, "manifest_sha256": "m" * 64, "state": "current", "schema": "0001",
              "checked_at": "2026-11-02T12:00:00Z", "result": "DEPLOY COMPATIBLE"}
    record.update(change)
    return record


@pytest.mark.parametrize("record, reason", [
    (None, "no preflight record"),
    (preflight_record(result="REFUSED"), "result"),
    (preflight_record(digest="sha256:" + "b" * 64), "another digest"),
    (preflight_record(manifest_sha256="x" * 64), "another digest or manifest"),
    (preflight_record(state="legacy", schema="none"), "changed since preflight"),
    (preflight_record(checked_at="2026-11-02T08:59:59Z"), "older than six hours"),
    (preflight_record(checked_at="2026-11-02T16:00:00Z"), "future"),
    (preflight_record(checked_at="yesterday"), "timestamp"),
])
def test_preflight_evidence_is_bound_and_fresh(record, reason):
    with pytest.raises(md.Refused, match=reason):
        md.check_preflight(record, DIGEST, "m" * 64, CURRENT, NOW)


def test_preflight_evidence_accepted():
    md.check_preflight(preflight_record(), DIGEST, "m" * 64, CURRENT, NOW)
    md.check_preflight(preflight_record(checked_at="2026-11-02T09:00:00Z"), DIGEST, "m" * 64, CURRENT, NOW)


def backup(tmp_path, lines=None, **change):
    dump = tmp_path / "mentor_pro_2026-11-02_120000.dump"
    dump.write_bytes(b"synthetic archive")
    fields = {"database": "mentor_pro", "schema_state": "current 0001",
              "sha256": hashlib.sha256(b"synthetic archive").hexdigest(), "verified": "2026-11-02T12:00:00Z",
              "result": "BACKUP OK"}
    fields.update(change)
    text = "dump x\n" + "".join(f"{k} {v}\n" for k, v in fields.items() if v is not None) + "".join(lines or [])
    Path(str(dump) + ".verify").write_text(text, encoding="utf-8")
    return dump


def check(dump, live=CURRENT):
    return md.check_backup(dump, md.read_backup_record(dump), "mentor_pro", live, NOW)


def test_backup_evidence_accepted(tmp_path):
    assert check(backup(tmp_path)) == hashlib.sha256(b"synthetic archive").hexdigest()
    old = backup(tmp_path, verified="2026-11-01T12:00:00Z", lines=["reverified 2026-11-02T14:00:00Z OK\n"])
    check(old)  # a later successful re-verification refreshes it


@pytest.mark.parametrize("change, lines, reason", [
    ({"result": "BACKUP FAILED: dump is empty"}, None, "not BACKUP OK"),
    ({"database": "mentor_pro_test"}, None, "database"),
    ({"schema_state": "legacy none"}, None, "schema state"),
    ({"verified": "2026-11-02T08:00:00Z"}, None, "older than six hours"),
    ({"verified": None}, None, "timestamp"),
    ({"sha256": "0" * 64}, None, "checksum"),
    ({}, ["reverified 2026-11-02T14:00:00Z FAILED checksum\n"], "later verification"),
])
def test_backup_evidence_refusals(tmp_path, change, lines, reason):
    with pytest.raises(md.Refused, match=reason):
        check(backup(tmp_path, lines=lines, **change))


def test_missing_backup_record(tmp_path):
    with pytest.raises(md.Refused, match="missing"):
        md.read_backup_record(tmp_path / "none.dump")


@pytest.mark.parametrize("window, authorization", [(None, "PO-1"), ("W-1", None), ("", "x"), ("W 1", "PO-1"),
                                                   ("W-1", "a" * 201), ("W-1", "PO\n1")])
def test_window_and_authorization_references_are_required(window, authorization):
    with pytest.raises(md.Refused):
        md.check_references(window, authorization)
    md.check_references("2026-11-02/window-1", "PO#T036-2026-11-01")


# ------------------------------------------------------------------ command line, lock, release.env

def cli(tmp_path, *args):
    env = {**os.environ, "MENTORPRO_STATE": str(tmp_path / "state"), "MENTORPRO_RELEASES": str(tmp_path / "R"),
           "MENTORPRO_RELEASE_ENV": str(tmp_path / "release.env"), "MENTORPRO_DOCKER": "no-docker-here"}
    return subprocess.run([sys.executable, str(REPO / "deploy" / "mentorpro_deploy.py"), *args], env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("args", [
    ["deploy", "m.json", "--backup", "d", "--window", "W-1"],
    ["deploy", "m.json", "--backup", "d", "--authorization", "PO-1"],
    ["deploy", "m.json", "--window", "W-1", "--authorization", "PO-1"],
    ["rollback", "--backup", "d", "--window", "W-1"],
])
def test_missing_references_refuse_before_anything(tmp_path, args):
    out = cli(tmp_path, *args)
    assert out.returncode == 1 and "REFUSED" in out.stdout
    assert not (tmp_path / "release.env").exists() and not (tmp_path / "R").exists()


def test_parallel_deploy_is_locked(tmp_path):
    state = tmp_path / "state"
    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys, time; sys.path.insert(0, sys.argv[1]); import mentorpro_deploy as md\n"
        "from pathlib import Path\n"
        "with md.deploy_lock({'state': Path(sys.argv[2])}):\n    print('held', flush=True); time.sleep(30)"),
        str(REPO / "deploy"), str(state)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        out = cli(tmp_path, "deploy", "m.json", "--backup", "d", "--window", "W-1", "--authorization", "PO-1")
        assert out.returncode == 1 and "holds the lock" in out.stdout
        assert not (tmp_path / "release.env").exists()
    finally:
        holder.kill()
        holder.wait()


def test_release_env_keeps_the_previous_configuration(tmp_path):
    cfg = {"release_env": tmp_path / "release.env", "state": tmp_path / "state"}
    md.write_release_env(cfg, f"{REPOSITORY}@{DIGEST}")
    assert md.current_image(cfg) == f"{REPOSITORY}@{DIGEST}" and md.previous_image(cfg) is None
    second = f"{REPOSITORY}@sha256:" + "b" * 64
    md.write_release_env(cfg, second)
    md.write_release_env(cfg, second)  # same content: nothing rewritten, previous kept
    assert md.current_image(cfg) == second and md.previous_image(cfg) == f"{REPOSITORY}@{DIGEST}"
    assert len(list((tmp_path / "state" / "history").iterdir())) == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_the_helper_never_touches_postgres_or_migrations():
    code = "\n".join(line for line in HELPER.splitlines() if not line.lstrip().startswith("#"))
    assert '"up", "-d", "--no-deps"' in code and '"app", "tutor"]' in code
    for forbidden in ("down", '"rm"', "migrate apply", "migrate rollback", "volume", "network rm", "restart",
                      ":testing", "latest"):
        assert forbidden not in re.sub(r'"""[\s\S]*?"""', "", code), forbidden
    assert "docker compose down -v" not in SCRIPT.read_text(encoding="utf-8")


def test_backup_record_carries_the_deploy_evidence():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "printf 'database %s\\nschema_state %s\\n'" in text
    assert "verified %s\\nresult BACKUP OK" in text


# ------------------------------------------------------------------ compose failure (PO correction 1)

FAKE_DOCKER = '''import sys
if sys.argv[1] == "compose":
    sys.stderr.write("service app: no such image\\n")
    sys.exit(17)
sys.exit(1)  # inspect: no container
'''


def state_cfg(tmp_path, docker=None):
    return {"repository": REPOSITORY, "release_env": tmp_path / "release.env", "releases": tmp_path / "RELEASES",
            "state": tmp_path / "state", "compose": tmp_path / "compose.yml", "project": "mentorpro-unit",
            "docker": docker or ["no-docker-here"], "health_timeout": 1}


def test_compose_failure_is_reported_and_recorded(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "fake_docker.py"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    cfg = state_cfg(tmp_path, [sys.executable, str(fake)])
    old, new = f"{REPOSITORY}@{DIGEST}", f"{REPOSITORY}@sha256:" + "b" * 64
    cfg["release_env"].write_text(f"MENTOR_PRO_IMAGE={old}\n", encoding="utf-8")
    assert md.compose_up(cfg, False).startswith("compose up exited 17: service app: no such image")

    def never(*a, **k):
        raise AssertionError("no health wait or smoke after a failed compose")

    monkeypatch.setattr(md, "wait_healthy", never)
    monkeypatch.setattr(md, "smoke", never)
    args = type("A", (), {"window": "W-1", "authorization": "PO-1"})
    assert md.change(cfg, args, "deploy", new, "v2026.11.02-2", CURRENT, "c" * 64) == 1
    out = capsys.readouterr().out
    assert "DEPLOY FAILED: compose up exited 17" in out and "PROPOSED MANUAL ROLLBACK (not executed)" in out
    assert "DEPLOY OK" not in out
    (line,) = md.releases(cfg)
    assert line["result"] == "FAILED" and line["image"] == new and line["previous"] == old
    assert line["error"].startswith("compose up exited 17")
    assert md.previous_image(cfg) == old  # kept for manual recovery


# ------------------------------------------------------------------ rollback provenance (PO correction 3)

def provenance_cfg(tmp_path, results=(), manifest_for=None, legacy_for=None):
    cfg = state_cfg(tmp_path)
    lines = [f"mentorpro\ttime=2026-11-02T12:00:00Z\taction=deploy\tresult={result}\timage={image}"
             for image, result in results]
    cfg["releases"].write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    if manifest_for:
        (cfg["state"] / "manifests").mkdir(parents=True)
        data = manifest(image={"repository": REPOSITORY, "digest": manifest_for, "image_id": None})
        (cfg["state"] / "manifests" / "v2026.11.02-1.json").write_text(json.dumps(data), encoding="utf-8")
    if legacy_for:
        path = md.legacy_path(cfg, legacy_for)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"image": f"{REPOSITORY}@{legacy_for}", "verified": "running",
                                    "schema": ["none", "none"]}), encoding="utf-8")
    return cfg


REF = f"{REPOSITORY}@{DIGEST}"


def test_ordinary_rollback_needs_a_stored_manifest(tmp_path):
    kind, source = md.provenance(provenance_cfg(tmp_path, [(REF, "OK")], manifest_for=DIGEST), REF)
    assert kind == "manifest" and source["release"] == "v2026.11.02-1"


def test_approved_legacy_candidate(tmp_path):
    kind, source = md.provenance(provenance_cfg(tmp_path, [(REF, "OK")], legacy_for=DIGEST), REF)
    assert kind == "legacy" and source["schema"] == ["none", "none"]


@pytest.mark.parametrize("results, manifest_for, legacy_for, ref, reason", [
    ([(REF, "OK")], None, None, REF, "no provenance"),  # unknown image, even if it once ran
    ([], None, None, REF, "never ran successfully"),
    ([(REF, "FAILED")], DIGEST, None, REF, "never ran successfully"),  # previous config was a failed deploy
    ([(REF, "REFUSED")], None, DIGEST, REF, "never ran successfully"),
    ([], None, None, "ghcr.io/someone/else@" + DIGEST, "pinned by digest"),  # arbitrary image
    ([], None, None, f"{REPOSITORY}:v2026.11.02-1", "pinned by digest"),  # a tag, not a digest
])
def test_rollback_without_provenance_is_refused(tmp_path, results, manifest_for, legacy_for, ref, reason):
    with pytest.raises(md.Refused, match=reason):
        md.provenance(provenance_cfg(tmp_path, results, manifest_for, legacy_for), ref)


def test_adopt_legacy_needs_references(tmp_path):
    out = cli(tmp_path, "adopt-legacy", "--window", "W-1")
    assert out.returncode == 1 and "--authorization reference is required" in out.stdout
    assert not (tmp_path / "state" / "legacy").exists()


# ------------------------------------------------------------------ Docker: the whole cycle, isolated

DOCKER_REQUIRED = os.environ.get("MENTORPRO_REQUIRE_DOCKER") == "1"


def _docker_ready():
    docker = shutil.which("docker")
    return bool(docker and SH and subprocess.run([docker, "info"], capture_output=True).returncode == 0)


@pytest.fixture()
def docker():
    if not _docker_ready():
        if DOCKER_REQUIRED:
            pytest.fail("Docker is required here (MENTORPRO_REQUIRE_DOCKER=1) but not available")
        pytest.skip("Docker is not available")


SERVER = '''import os, sys, http.server
ROLE, FAIL = sys.argv[1], os.environ.get("FAIL_PATH", "")
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if ROLE == "tutor":
            code = (403 if self.client_address[0] == "127.0.0.1" else 200) if self.path == "/tutor" else \\
                403 if self.path.startswith("/api/tutor") else 404
        else:
            code = 500 if self.path == FAIL else 404 if self.path.startswith("/api/tutor") else 200
        self.send_response(code)
        self.end_headers()
    def log_message(self, *a):
        pass
http.server.ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
'''
DOCKERFILE = '''FROM python:3.12-alpine
ARG MARK=x
ARG FAIL_PATH=
ENV FAIL_PATH=$FAIL_PATH
WORKDIR /srv
COPY . /srv
RUN echo "$MARK" > /srv/mark
CMD ["python", "/srv/server.py", "app"]
'''


def sh(*args, **kw):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=600, **kw)


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _production_named():
    return sorted(sh("docker", "ps", "-a", "--filter", "name=mentor-pro-", "--format", "{{.ID}} {{.Image}}").stdout
                  .split("\n") + sh("docker", "volume", "ls", "-q", "--filter", "name=mentor-pro").stdout.split())


def _test_resources(prefix):
    out = []
    for kind in (["ps", "-a"], ["volume", "ls"], ["network", "ls"]):
        out += sh("docker", *kind, "-q", "--filter", f"name={prefix}").stdout.split()
    return out


def test_docker_deploy_and_rollback_cycle(docker, tmp_path):
    ident = uuid.uuid4().hex[:8]
    project = f"mentorpro-i4test-{ident}"
    assert not project.startswith("mentor-pro")
    production_before = _production_named()
    reg_port, app_port, tutor_port = _free_port(), _free_port(), _free_port()
    repo = f"127.0.0.1:{reg_port}/mentor-pro"
    build = tmp_path / "image"
    (build / "app").mkdir(parents=True)
    (build / "server.py").write_text(SERVER, encoding="utf-8")
    (build / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (build / "app" / "__init__.py").write_text("", encoding="utf-8")
    (build / "app" / "tutor_main.py").write_text(
        'import runpy, sys\nsys.argv = ["server.py", "tutor"]\nrunpy.run_path("/srv/server.py", run_name="__main__")\n',
        encoding="utf-8")
    created = "2026-11-02T15:04:05Z"

    def image(name, version=None, fail=""):
        labels = [] if version is None else sum((["--label", f"{k}={v}"] for k, v in
                                                 release.labels(version, SHA, created).items()), [])
        tag = f"{repo}:{version or name}"
        out = sh("docker", "build", "-q", "--build-arg", f"MARK={name}", "--build-arg", f"FAIL_PATH={fail}",
                 *labels, "-t", tag, str(build))
        assert out.returncode == 0, out.stderr
        return push(tag)

    def push(tag):
        out = sh("docker", "push", tag)
        assert out.returncode == 0, out.stderr
        return re.search(r"digest: (sha256:[0-9a-f]{64})", out.stdout).group(1)

    def write_manifest(version, digest, **change):
        data = release.manifest(version, SHA, "7", created, digest=digest)
        data["image"]["repository"] = repo
        data.update(change)
        path = tmp_path / f"{version}{'-x' if change else ''}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    compose = (REPO / "deploy" / "compose.yml").read_text(encoding="utf-8")
    for name, content in (("app.env", ""), ("tutor.env", ""), ("postgres.env", (
            "POSTGRES_HOST_AUTH_METHOD=trust\nPOSTGRES_USER=mentor_pro_admin\nPOSTGRES_DB=mentor_pro\n"))):
        (tmp_path / name).write_text(content, encoding="utf-8")
        compose = compose.replace(f"/etc/mentor-pro/{name}", _posix(tmp_path / name))
    compose = re.sub(r'\n\s+- "192\.168\.50\.229:8080:8000".*', "", compose)
    compose = compose.replace('"127.0.0.1:8080:8000"', f'"127.0.0.1:{app_port}:8000"')
    compose = compose.replace('"127.0.0.1:8081:8000"', f'"127.0.0.1:{tutor_port}:8000"')
    compose = compose.replace("interval: 30s", "interval: 2s").replace("start_period: 30s", "start_period: 1s")
    (tmp_path / "compose.yml").write_text(compose, encoding="utf-8")
    release_env = tmp_path / "release.env"
    env = {**os.environ, "MENTORPRO_REPOSITORY": repo, "MENTORPRO_RELEASE_ENV": _posix(release_env),
           "MENTORPRO_RELEASES": _posix(tmp_path / "RELEASES"), "MENTORPRO_STATE": _posix(tmp_path / "state"),
           "MENTORPRO_COMPOSE": _posix(tmp_path / "compose.yml"), "MENTORPRO_PROJECT": project,
           "MENTORPRO_POSTGRES_CONTAINER": f"{project}-postgres-1", "MENTORPRO_BACKUPS": _posix(tmp_path / "b"),
           "MENTORPRO_BACKUP_SCHEMAS": "writing", "MENTORPRO_PYTHON": sys.executable,
           "MENTORPRO_APP_URL": f"http://127.0.0.1:{app_port}", "MENTORPRO_TUTOR_URL": f"http://127.0.0.1:{tutor_port}",
           "MENTORPRO_WIFI_ADDR": "", "MENTORPRO_HEALTH_TIMEOUT": "90"}

    def run(*args, **extra):
        out = subprocess.run([SH, str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True,
                             timeout=900)
        return out.returncode, out.stdout + out.stderr

    def psql(sql):
        out = sh("docker", "exec", "-i", f"{project}-postgres-1", "psql", "-U", "mentor_pro_admin", "-d",
                 "mentor_pro", "-q", "-v", "ON_ERROR_STOP=1", input=sql)
        assert out.returncode == 0, out.stderr

    def running(service="app"):
        return sh("docker", "inspect", f"{project}-{service}-1", "--format", "{{.Id}} {{.Config.Image}}").stdout.split()

    def wait_registry():
        for _ in range(30):
            if sh("docker", "exec", f"{project}-registry", "wget", "-qO-", "http://127.0.0.1:5000/v2/").returncode == 0:
                return
            time.sleep(1)

    refs = ["--window", "W-2026-11-02", "--authorization", "PO-T044-test"]
    try:
        assert sh("docker", "run", "-d", "--name", f"{project}-registry", "-p", f"127.0.0.1:{reg_port}:5000",
                  "registry:2").returncode == 0
        wait_registry()
        legacy = image("legacy")  # pre-T036 stand-in: no labels
        r1 = image("r1", "v2026.11.02-1")
        r2 = image("r2", "v2026.11.02-2")
        rfail = image("rfail", "v2026.11.02-3", fail="/api/dashboard")
        m1, m2, mfail = (write_manifest(v, d) for v, d in
                         (("v2026.11.02-1", r1), ("v2026.11.02-2", r2), ("v2026.11.02-3", rfail)))

        # "Production" before scripted deployments: the label-less image on a legacy schema.
        release_env.write_text(f"MENTOR_PRO_IMAGE={repo}@{legacy}\n", encoding="utf-8")
        up = sh("docker", "compose", "-p", project, "-f", str(tmp_path / "compose.yml"), "--env-file",
                str(release_env), "up", "-d", "--wait")
        assert up.returncode == 0, up.stderr
        postgres_id = running("postgres")[0]
        code, out = run("adopt-legacy", *refs)  # once: the pre-script image becomes a known rollback candidate
        assert code == 0 and "ADOPTED legacy rollback candidate" in out, out
        psql("CREATE SCHEMA writing; CREATE TABLE writing.draft (id int); CREATE TABLE writing.submission "
             "(exercise_id int); CREATE UNIQUE INDEX uq_submission_exercise ON writing.submission (exercise_id);")

        code, out = run("preflight", m1)
        assert code == 1 and "MIGRATION REQUIRED" in out and "live database: legacy" in out, out

        # Synthetic stand-in for migration 0001 (the real one is I5), then drift and repair by hand.
        psql("CREATE TABLE writing.schema_migration (migration_id text PRIMARY KEY);"
             "INSERT INTO writing.schema_migration VALUES ('0001_student_attempts');")
        code, out = run("preflight", m1)
        assert code == 1 and "schema drifted" in out, out
        psql("DROP INDEX writing.uq_submission_exercise;")

        code, out = run("backup")
        assert code == 0 and "BACKUP OK" in out, out
        dump = re.search(r"BACKUP OK (\S+)", out).group(1)
        assert "schema_state current 0001" in Path(dump + ".verify").read_text(encoding="utf-8")

        code, out = run("deploy", m1, "--backup", dump, *refs)
        assert code == 1 and "no preflight record" in out, out
        code, out = run("preflight", m1)
        assert code == 0 and "PREFLIGHT OK: DEPLOY COMPATIBLE" in out, out
        code, out = run("deploy", m1, "--backup", dump, "--window", "W-1")
        assert code == 1 and "--authorization reference is required" in out
        code, out = run("deploy", m1, "--backup", dump, *refs)
        assert code == 0 and "DEPLOY OK" in out, out
        assert running()[1] == running("tutor")[1] == f"{repo}@{r1}"
        app_id = running()[0]
        code, out = run("deploy", m1, "--backup", dump, *refs)
        assert code == 0 and "UNCHANGED" in out and running()[0] == app_id, out

        # Rollback to the label-less image would cross migration 0001: refused, nothing changed.
        code, out = run("rollback", "--backup", dump, *refs)
        assert code == 1 and "ROLLBACK REFUSED: incompatible" in out and "database restore" in out, out
        assert running()[0] == app_id and running("postgres")[0] == postgres_id
        assert release_env.read_text(encoding="utf-8") == f"MENTOR_PRO_IMAGE={repo}@{r1}\n"

        # Evidence bound to the deployment: r1's preflight is not r2's.
        state = tmp_path / "state" / "preflight"
        shutil.copy(state / (r1.split(":")[1] + ".json"), state / (r2.split(":")[1] + ".json"))
        code, out = run("deploy", m2, "--backup", dump, *refs)
        assert code == 1 and "another digest" in out, out
        code, out = run("preflight", m2)
        assert code == 0, out
        record = state / (r2.split(":")[1] + ".json")
        fresh = record.read_text(encoding="utf-8")
        stale = json.loads(fresh)
        stale["checked_at"] = md.stamp(md.utc_now() - timedelta(hours=7))
        record.write_text(json.dumps(stale), encoding="utf-8")
        code, out = run("deploy", m2, "--backup", dump, *refs)
        assert code == 1 and "older than six hours" in out, out
        record.write_text(fresh, encoding="utf-8")
        verify = Path(dump + ".verify")
        good = verify.read_text(encoding="utf-8")
        for bad, reason in ((re.sub(r"(?m)^verified .*", "verified " + md.stamp(md.utc_now() - timedelta(hours=7)),
                                    good), "older than six hours"),
                            (good.replace("database mentor_pro", "database other_db"), "database"),
                            (good.replace("schema_state current 0001", "schema_state legacy none"), "schema state")):
            verify.write_text(bad, encoding="utf-8")
            code, out = run("deploy", m2, "--backup", dump, *refs)
            assert code == 1 and reason in out, out
        verify.write_text(good, encoding="utf-8")

        # Registry identity changes between preflight and deploy: the final check under the lock refuses.
        sh("docker", "tag", f"{repo}:legacy", f"{repo}:v2026.11.02-2")
        push(f"{repo}:v2026.11.02-2")
        code, out = run("deploy", m2, "--backup", dump, *refs)
        assert code == 1 and "retagged" in out and running()[1] == f"{repo}@{r1}", out
        sh("docker", "tag", f"{repo}@{r2}", f"{repo}:v2026.11.02-2")
        assert push(f"{repo}:v2026.11.02-2") == r2
        sh("docker", "stop", f"{project}-registry")
        code, out = run("deploy", m2, "--backup", dump, *refs)
        assert code == 1 and "registry not reachable" in out and running()[1] == f"{repo}@{r1}", out
        sh("docker", "start", f"{project}-registry")
        wait_registry()

        code, out = run("deploy", m2, "--backup", dump, *refs)
        assert code == 0 and "DEPLOY OK" in out and running()[1] == f"{repo}@{r2}", out

        code, out = run("rollback", "--to", "v2026.11.02-1", "--backup", dump, *refs)
        assert code == 0 and "ROLLBACK OK" in out and running()[1] == f"{repo}@{r1}", out

        # Compose failure: FAILED, never OK; previous configuration kept; no automatic rollback.
        app_id = running()[0]
        code, out = run("deploy", m2, "--backup", dump, *refs, MENTORPRO_COMPOSE=_posix(tmp_path / "missing.yml"))
        assert code == 1 and "DEPLOY FAILED: compose up exited" in out and "DEPLOY OK" not in out, out
        assert running()[0] == app_id and Path(str(release_env) + ".previous").read_text(
            encoding="utf-8") == f"MENTOR_PRO_IMAGE={repo}@{r1}\n"
        code, out = run("rollback", "--backup", dump, *refs)
        assert code == 0 and "ROLLBACK OK" in out and running()[1] == f"{repo}@{r1}", out

        # Registry identity: retagged version, unknown digest, mismatched and dry-run manifests.
        sh("docker", "tag", f"{repo}:legacy", f"{repo}:v2026.11.02-2")
        push(f"{repo}:v2026.11.02-2")
        code, out = run("preflight", m2)
        assert code == 1 and "retagged" in out, out
        sh("docker", "tag", f"{repo}@{r2}", f"{repo}:v2026.11.02-2")
        assert push(f"{repo}:v2026.11.02-2") == r2
        code, out = run("preflight", write_manifest("v2026.11.02-9", "sha256:" + "0" * 64))
        assert code == 1 and "REFUSED" in out, out
        code, out = run("preflight", write_manifest("v2026.11.02-1", r1, commit="f" * 40))
        assert code == 1 and "labels differ" in out, out
        dry = tmp_path / "dry.json"
        dry.write_text(json.dumps(release.manifest("dev-0123456", SHA, "7", created, image_id=r1, dry_run=True)))
        code, out = run("preflight", str(dry))
        assert code == 1 and "dry-run" in out, out

        # Failed smoke: reported, no automatic rollback, manual rollback works.
        assert run("preflight", mfail)[0] == 0
        code, out = run("deploy", mfail, "--backup", dump, *refs)
        assert code == 1 and "DEPLOY FAILED: smoke test failed" in out and "PROPOSED MANUAL ROLLBACK" in out, out
        assert running()[1] == f"{repo}@{rfail}"  # nothing rolled back by itself
        code, out = run("rollback", "--backup", dump, *refs)
        assert code == 0 and "ROLLBACK OK" in out and running()[1] == f"{repo}@{r1}", out
        # release.env.previous now names the failed release: never a rollback target.
        code, out = run("rollback", "--backup", dump, *refs)
        assert code == 1 and "never ran successfully" in out and running()[1] == f"{repo}@{r1}", out

        lines = [line for line in (tmp_path / "RELEASES").read_text(encoding="utf-8").splitlines()]
        results = [re.search(r"result=(\w+)", line).group(1) for line in lines]
        assert results == ["OK", "OK", "UNCHANGED", "REFUSED", "OK", "OK", "FAILED", "OK", "FAILED", "OK"], results
        assert all("authorization=PO-T044-test" in line and "authorization_verified=no" in line for line in lines)
        assert running("postgres")[0] == postgres_id
    finally:
        for container in sh("docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").stdout.split():
            sh("docker", "rm", "-f", "-v", container)
        sh("docker", "rm", "-f", "-v", f"{project}-registry")
        for volume in sh("docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}").stdout.split():
            sh("docker", "volume", "rm", volume)
        for network in sh("docker", "network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}").stdout.split():
            sh("docker", "network", "rm", network)
    assert _test_resources(project) == []
    assert _production_named() == production_before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
