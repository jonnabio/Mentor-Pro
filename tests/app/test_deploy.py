"""Versioned deployment files and read-only commands (T041, ADR-033 increment I1).

The compose file is checked as text (no YAML dependency); `deploy/mentorpro smoke` and `status` run against real
student and tutor processes on the isolated test database. Nothing here touches Docker or a server.
"""

from __future__ import annotations

import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest

from app.writing.store import WritingStore
from conftest import SYNTHETIC

REPO = Path(__file__).resolve().parents[2]
COMPOSE = (REPO / "deploy" / "compose.yml").read_text(encoding="utf-8")
SCRIPT = REPO / "deploy" / "mentorpro"
TOKEN = "deploy-smoke-token-0123456789abcdef"  # test only, 35 characters
SH, CURL = shutil.which("sh"), shutil.which("curl")


def _posix(path):
    return Path(path).as_posix()


def service(name):
    """The text block of one top-level service."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  \w+:\n|^\S)", COMPOSE, re.M | re.S)
    assert match, name
    return match.group(1)


def test_compose_holds_no_secret_and_interpolates_only_the_image():
    body = "\n".join(line.split("#")[0] for line in COMPOSE.splitlines())  # code, not comments
    assert not re.search(r"password|postgres(ql)?://|api_key|token", body, re.I)
    assert set(re.findall(r"\$\{(\w+)", body)) == {"MENTOR_PRO_IMAGE"}


def test_compose_bindings_match_adr_030_and_031():
    app, tutor, postgres = service("app"), service("tutor"), service("postgres")
    assert re.findall(r'- "([\d.]+:\d+:\d+)"', app) == ["127.0.0.1:8080:8000", "192.168.50.229:8080:8000"]
    assert re.findall(r'- "([\d.]+:\d+:\d+)"', tutor) == ["127.0.0.1:8081:8000"]  # loopback only
    assert "ports:" not in postgres and "0.0.0.0" not in COMPOSE
    assert "/etc/mentor-pro/tutor.env" in tutor and "tutor.env" not in app  # student service never holds the token
    assert 'command: ["python", "-m", "app.tutor_main"]' in tutor
    assert 'MENTOR_PRO_DEV_ENDPOINTS: "false"' in app and 'MENTOR_PRO_DEV_ENDPOINTS: "false"' in tutor
    assert "postgres_data:/var/lib/postgresql/data" in postgres and "image: postgres:17.6" in postgres
    for block in (app, tutor, postgres):
        assert "healthcheck:" in block and "restart: unless-stopped" in block


def _answering(status):
    """A local HTTP server that answers every GET with `status`; returns (server, port)."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def _tutor_healthcheck(port):
    test = re.search(r'test: \["CMD", "python", "-c", "(.*)"\]', service("tutor")).group(1)
    code = test.encode().decode("unicode_escape").replace("127.0.0.1:8000", f"127.0.0.1:{port}")
    return subprocess.run([sys.executable, "-c", code], timeout=30).returncode


@pytest.mark.parametrize("status, healthy", [(403, True), (200, False), (500, False), (503, False)])
def test_tutor_healthcheck_passes_only_on_the_expected_403(status, healthy):
    server, port = _answering(status)
    try:
        assert (_tutor_healthcheck(port) == 0) is healthy
    finally:
        server.shutdown()


def test_tutor_healthcheck_fails_without_a_connection():
    assert _tutor_healthcheck(_free_port()) != 0


# ------------------------------------------------------------------ the script against real processes

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(code, port, env):
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=REPO, env={**os.environ, **env},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError(f"port {port} did not open")


def run(command, app_port, tutor_port, tmp_path, docker="mentorpro-test-no-docker", **extra):
    env = {**os.environ, "MENTORPRO_TAILNET_URL": "", **extra, "MENTORPRO_DOCKER": docker, "MENTORPRO_APP_URL": f"http://127.0.0.1:{app_port}",
           "MENTORPRO_TUTOR_URL": f"http://127.0.0.1:{tutor_port}", "MENTORPRO_WIFI_ADDR": "",
           "MENTORPRO_RELEASE_ENV": str(tmp_path / "release.env"), "MENTORPRO_RELEASES": str(tmp_path / "RELEASES"),
           "MENTORPRO_BACKUPS": str(tmp_path / "backups")}
    return subprocess.run([SH, str(SCRIPT), command], env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture()
def services(synthetic_client):
    if not (SH and CURL):
        pytest.skip("sh and curl are needed to run deploy/mentorpro")
    url, schema = synthetic_client.app.state.catalog_target
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    WritingStore(url)  # a current writing schema, as after deployment
    app_port, tutor_port = _free_port(), _free_port()
    student = _serve("import uvicorn; from app.main import create_app; "
                     f"uvicorn.run(create_app({url!r}, {schema!r}, {SYNTHETIC!r}, tutor_token=''), "
                     f"host='127.0.0.1', port={app_port}, log_level='warning')", app_port, {})
    tutor = _serve("import uvicorn; from app.tutor_main import create_tutor_app, UVICORN_OPTIONS as o; "
                   f"uvicorn.run(create_tutor_app({url!r}), **{{**o, 'host': '127.0.0.1', 'port': {tutor_port}, "
                   "'log_level': 'warning'})", tutor_port,
                   {"MENTOR_PRO_TUTOR_TOKEN": TOKEN, "MENTOR_PRO_TUTOR_ALLOWED_HOSTS": "127.0.0.1"})
    yield app_port, tutor_port, tutor
    for proc in (student, tutor):
        proc.terminate()
        proc.wait(timeout=10)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")


def test_smoke_passes_on_healthy_services_and_fails_when_the_tutor_is_down(services, tmp_path):
    app_port, tutor_port, tutor = services
    ok = run("smoke", app_port, tutor_port, tmp_path)
    assert ok.returncode == 0, ok.stdout
    assert "SMOKE PASS (7/7)" in ok.stdout and "FAIL" not in ok.stdout and TOKEN not in ok.stdout
    assert "PASS student service has no tutor routes (404)" in ok.stdout
    assert "PASS tutor API refuses without the token (403)" in ok.stdout

    again = run("smoke", app_port, tutor_port, tmp_path)  # read-only: same answer on a rerun
    assert again.returncode == 0 and again.stdout == ok.stdout

    tutor.terminate()
    tutor.wait(timeout=10)
    down = run("smoke", app_port, tutor_port, tmp_path)
    assert down.returncode == 1
    assert "FAIL tutor page (expected 200, got 000)" in down.stdout and "SMOKE FAIL (2 of 7 failed)" in down.stdout


# ------------------------------------------------------------------ T058: tutor over Tailscale Serve (HTTPS)

KUMA = {"Proxy": "http://127.0.0.1:3001"}


def serve_json(port, tutor_port, funnel=False, target=None, extra_tutor_port=None):
    web = {"macedonianserver.tailb0ac04.ts.net:443": {"Handlers": {"/": KUMA}},
           f"macedonianserver.tailb0ac04.ts.net:{port}": {
               "Handlers": {"/": {"Proxy": target or f"http://127.0.0.1:{tutor_port}"}}}}
    tcp = {"443": {"HTTPS": True}, str(port): {"HTTPS": True}}
    if extra_tutor_port:
        web[f"macedonianserver.tailb0ac04.ts.net:{extra_tutor_port}"] = {
            "Handlers": {"/": {"Proxy": f"http://127.0.0.1:{tutor_port}"}}}
        tcp[str(extra_tutor_port)] = {"HTTPS": True}
    cfg = {"TCP": tcp, "Web": web}
    if funnel:
        cfg["AllowFunnel"] = {f"macedonianserver.tailb0ac04.ts.net:{port}": True}
    return json.dumps(cfg)


def fake_tailscale(tmp_path, body):
    """A stand-in `tailscale` that answers only `serve status --json` and records every call."""
    (tmp_path / "serve.json").write_text(body, encoding="utf-8")
    script = tmp_path / "tailscale"
    script.write_text(f'''#!/bin/sh
echo "$*" >> "{_posix(tmp_path / 'calls.log')}"
[ "$*" = "serve status --json" ] && cat "{_posix(tmp_path / 'serve.json')}"
''', encoding="utf-8", newline="\n")
    script.chmod(0o755)
    return _posix(script)


def run_tailnet(app_port, tutor_port, tmp_path, body):
    # The tutor port stands in for the Serve HTTPS port: same tutor, same token check.
    return run("smoke", app_port, tutor_port, tmp_path, MENTORPRO_TAILNET_URL=f"http://127.0.0.1:{tutor_port}",
               MENTORPRO_TAILSCALE=fake_tailscale(tmp_path, body), MENTORPRO_PYTHON=_posix(sys.executable))


def test_smoke_checks_tutor_over_tailscale_serve(services, tmp_path):
    app_port, tutor_port, _ = services
    ok = run_tailnet(app_port, tutor_port, tmp_path, serve_json(tutor_port, tutor_port))
    assert ok.returncode == 0, ok.stdout
    assert f"PASS Tailscale Serve: port {tutor_port} only to the loopback tutor, Funnel off" in ok.stdout
    assert "PASS tutor page over Tailscale HTTPS (200)" in ok.stdout
    assert "PASS tutor API over HTTPS refuses without the token (403)" in ok.stdout
    assert "PASS practice results over HTTPS refuse without the token (403)" in ok.stdout
    assert "SMOKE PASS (11/11)" in ok.stdout and TOKEN not in ok.stdout
    # Read only: the tool asked Serve for its status and nothing else (never set, reset, off or funnel).
    assert (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines() == ["serve status --json"]


@pytest.mark.parametrize("case,expected", [
    ("funnel", "funnel on"),
    ("wrong target", "does not serve only"),
    ("other port", "tutor also served on another port"),
    ("missing", "does not serve only"),
    ("unreadable", "unreadable"),
])
def test_smoke_fails_on_unsafe_or_missing_serve_configuration(services, tmp_path, case, expected):
    app_port, tutor_port, _ = services
    body = {"funnel": serve_json(tutor_port, tutor_port, funnel=True),
            "wrong target": serve_json(tutor_port, tutor_port, target="http://127.0.0.1:3001"),
            "other port": serve_json(tutor_port, tutor_port, extra_tutor_port=10000),
            "missing": json.dumps({"TCP": {"443": {"HTTPS": True}},
                                   "Web": {"macedonianserver.tailb0ac04.ts.net:443": {"Handlers": {"/": KUMA}}}}),
            "unreadable": "not json"}[case]
    result = run_tailnet(app_port, tutor_port, tmp_path, body)
    assert result.returncode == 1 and "FAIL Tailscale Serve (" in result.stdout and expected in result.stdout


def test_smoke_fails_without_tailscale(services, tmp_path):
    app_port, tutor_port, _ = services
    result = run("smoke", app_port, tutor_port, tmp_path, MENTORPRO_TAILNET_URL=f"http://127.0.0.1:{tutor_port}",
                 MENTORPRO_TAILSCALE=_posix(tmp_path / "no-tailscale"), MENTORPRO_PYTHON=_posix(sys.executable))
    assert result.returncode == 1 and "FAIL Tailscale Serve" in result.stdout


def test_deploy_tool_never_changes_tailscale():
    script = SCRIPT.read_text(encoding="utf-8")
    # The only tailscale call reads the Serve status; nothing sets, resets or turns off Serve or Funnel.
    assert re.findall(r'"\$TAILSCALE"[^|\n]*', script) == ['"$TAILSCALE" serve status --json 2>/dev/null ']
    assert not re.search(r"tailscale\s+(funnel|serve\s+(--|reset|https|off))", script)
    assert re.search(r"TAILNET_URL=\$\{MENTORPRO_TAILNET_URL-https://macedonianserver\.tailb0ac04\.ts\.net:8443\}",
                     script)


def test_status_is_read_only_and_reports_without_secrets(services, tmp_path):
    app_port, tutor_port, _ = services
    (tmp_path / "release.env").write_text("MENTOR_PRO_IMAGE=ghcr.io/jonnabio/mentor-pro@sha256:" + "a" * 64 + "\n")
    (tmp_path / "RELEASES").write_text("2026-10-28T12:00:00 sha256:aaa abc123 operator ok\n")
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "mentor_pro_2026-10-28.dump").write_bytes(b"x")
    before = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*"))
    result = run("status", app_port, tutor_port, tmp_path)
    assert result.returncode == 3, result.stdout  # Docker unknown: never reported as healthy
    out = result.stdout
    assert "UNKNOWN docker: not available on this host" in out and "STATUS INCOMPLETE (1 item(s) unknown)" in out
    assert "HEALTHY" not in out
    assert "MENTOR_PRO_IMAGE=ghcr.io/jonnabio/mentor-pro@sha256:" in out
    assert "OK      student / 200" in out and "OK      tutor /tutor 200" in out
    assert "operator ok" in out and "dumps 1," in out and "no automatic deletion" in out
    assert TOKEN not in out and "postgresql://" not in out
    assert sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.rglob("*")) == before


FAKE_DOCKER = """#!/bin/sh
# Test double: answers `inspect` and `exec` like Docker for the three services.
case "$1" in
  inspect) [ "$2" = mentor-pro-tutor-1 ] && echo "img@sha256:t running $TUTOR_HEALTH" || echo "img@sha256:a running healthy" ;;
  exec) [ -n "$SCHEMA" ] || exit 1; printf '{\n "state": "%s"\n}\n' "$SCHEMA" ;;
esac
"""


@pytest.mark.parametrize("tutor_health, schema, code, verdict", [
    ("healthy", "current", 0, "STATUS HEALTHY"),
    ("unhealthy", "current", 1, "STATUS UNHEALTHY (1 problem(s), 0 unknown)"),
    ("healthy", "drifted", 1, "STATUS UNHEALTHY (1 problem(s), 0 unknown)"),
    ("healthy", "", 3, "STATUS INCOMPLETE (1 item(s) unknown)"),
    ("none", "current", 3, "STATUS INCOMPLETE (1 item(s) unknown)"),
])
def test_status_separates_healthy_unhealthy_and_unknown(services, tmp_path, tutor_health, schema, code, verdict):
    app_port, tutor_port, _ = services
    fake = tmp_path / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    (tmp_path / "backups").mkdir()
    result = run("status", app_port, tutor_port, tmp_path, docker=fake.as_posix(),
                 TUTOR_HEALTH=tutor_health, SCHEMA=schema)
    assert result.returncode == code, result.stdout
    assert result.stdout.rstrip().endswith(verdict)
    if code == 3:
        assert "UNKNOWN" in result.stdout and "HEALTHY" not in result.stdout


def test_unknown_command_is_refused():
    if not SH:
        pytest.skip("sh is needed")
    result = subprocess.run([SH, str(SCRIPT), "restore"], capture_output=True, text=True)  # G3: never a script command
    assert result.returncode == 2 and "usage: mentorpro status|smoke" in result.stderr
