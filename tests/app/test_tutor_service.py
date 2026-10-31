"""Tutor service isolation (T033, ADR-031): only the configured gateway with the token reaches tutor review.

Requests are sent through the ASGI interface with an explicit client address, so LAN devices, other
containers and spoofed forwarded headers are tested as the app sees them, not inferred from a port binding.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.tutor_main import EX_CONFIG, UVICORN_OPTIONS, TutorConfigurationError, create_tutor_app, parse_allowed_hosts
from app.writing.store import WritingStore
from conftest import SYNTHETIC

REPO = Path(__file__).resolve().parents[2]
L1 = json.loads((REPO / "scripts" / "dev" / "fixtures" / "writing-exercises-L1-T023.json").read_text(
    encoding="utf-8"))[0]
TOKEN = "tutor-service-token-0123456789abcdef"  # 36 characters
GATEWAY = "172.19.0.1"
GOOD = {"X-Tutor-Token": TOKEN}


def call(app, client_ip, path, headers=None, method="GET", body=None):
    transport = httpx.ASGITransport(app=app, client=(client_ip, 40000))

    async def go():
        async with httpx.AsyncClient(transport=transport, base_url="http://tutor") as c:
            return await c.request(method, path, headers=headers or {}, json=body)

    import asyncio
    return asyncio.run(go())


@pytest.fixture()
def env(synthetic_client):
    url, schema = synthetic_client.app.state.catalog_target
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")
    store = WritingStore(url)
    store.add_exercise(L1)
    store.submit_typed(L1["exercise_id"], "Los niños juegan al fútbol.", "req-tutor-svc-1")
    yield create_tutor_app(url, TOKEN, GATEWAY), url, schema
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS writing CASCADE")


# ------------------------------------------------------------------ configuration fails closed

@pytest.mark.parametrize("value", ["", "  ", None, "172.19.0.0/16", "macedonianserver", "0.0.0.0", "::",
                                   "172.19.0.1,*", "172.19.0.255", "224.0.0.1", "172.19.0.1;192.168.50.1"])
def test_invalid_allowed_hosts_refuse_to_start(value):
    with pytest.raises(TutorConfigurationError):
        parse_allowed_hosts(value)
    with pytest.raises(TutorConfigurationError):
        create_tutor_app("postgresql://unused/x_test", TOKEN, value)


@pytest.mark.parametrize("token", ["", "short", "x" * 31])
def test_missing_or_weak_token_refuses_to_start(token):
    with pytest.raises(TutorConfigurationError):
        create_tutor_app("postgresql://unused/x_test", token, GATEWAY)


def test_exact_addresses_are_normalised():
    assert parse_allowed_hosts(" 172.19.0.1 , ::1 ") == frozenset({"172.19.0.1", "::1"})


# ------------------------------------------------------------------ who may call

def test_gateway_with_token_reaches_tutor_review(env):
    app, _, _ = env
    queue = call(app, GATEWAY, "/api/tutor/queue", GOOD)
    assert queue.status_code == 200 and len(queue.json()["submissions"]) == 1
    assert call(app, GATEWAY, "/tutor").status_code == 200


def test_tutor_page_links_back_to_the_student_app_and_the_student_app_never_links_to_the_tutor(env):
    app, url, schema = env
    page = call(app, GATEWAY, "/tutor").text
    assert '<a href="http://192.168.50.229:8080/">Volver a Mentor Pro</a>' in page  # T046
    assert call(app, GATEWAY, "/").status_code == 404  # the link leaves the tutor service
    student = TestClient(create_app(url, schema, SYNTHETIC, tutor_token="")).get("/").text
    assert "/tutor" not in student and ":8081" not in student  # ADR-024


@pytest.mark.parametrize("client_ip", ["192.168.50.23", "192.168.100.5", "172.19.0.2", "172.19.0.3",
                                       "172.17.0.1", "127.0.0.1", "100.64.84.20"])
def test_lan_clients_and_other_containers_are_refused_even_with_the_token(env, client_ip):
    app, _, _ = env
    assert call(app, client_ip, "/api/tutor/queue", GOOD).status_code == 403
    assert call(app, client_ip, "/tutor").status_code == 403
    sid = call(app, GATEWAY, "/api/tutor/queue", GOOD).json()["submissions"][0]["submission_id"]
    assert call(app, client_ip, f"/api/tutor/submissions/{sid}", GOOD).status_code == 403
    assert call(app, client_ip, f"/api/tutor/submissions/{sid}/evaluation", GOOD, "PUT",
                {"scores": {}, "complete": False}).status_code == 403


@pytest.mark.parametrize("headers", [{}, {"X-Tutor-Token": ""}, {"X-Tutor-Token": TOKEN[:-1]},
                                     {"X-Tutor-Token": TOKEN + "x"}, {"Authorization": f"Bearer {TOKEN}"}])
def test_absent_or_wrong_token_is_refused_from_the_gateway(env, headers):
    app, _, _ = env
    assert call(app, GATEWAY, "/api/tutor/queue", headers).status_code == 403


def test_forwarded_headers_cannot_impersonate_the_gateway(env):
    app, _, _ = env
    spoof = {**GOOD, "X-Forwarded-For": GATEWAY, "X-Real-IP": GATEWAY, "Forwarded": f"for={GATEWAY}"}
    assert call(app, "192.168.50.23", "/api/tutor/queue", spoof).status_code == 403


def test_wrong_gateway_configuration_fails_closed(env):
    _, url, _ = env
    misconfigured = create_tutor_app(url, TOKEN, "172.18.0.1")  # e.g. the network was recreated
    assert call(misconfigured, GATEWAY, "/api/tutor/queue", GOOD).status_code == 403


def test_tutor_service_serves_no_student_or_development_routes(env):
    app, _, _ = env
    for path in ("/", "/api/subjects", "/api/writing/levels", "/api/dashboard", "/api/docs", "/api/openapi.json"):
        assert call(app, GATEWAY, path, GOOD).status_code == 404, path


def test_student_service_never_trusts_the_gateway_or_the_setting(env, monkeypatch):
    _, url, schema = env
    monkeypatch.setenv("MENTOR_PRO_TUTOR_ALLOWED_HOSTS", GATEWAY)
    student = create_app(url, schema, SYNTHETIC, tutor_token="")  # production: no token in the app service
    assert call(student, GATEWAY, "/api/tutor/queue", GOOD).status_code == 404
    assert call(student, GATEWAY, "/tutor").status_code == 404
    local = create_app(url, schema, SYNTHETIC, tutor_token=TOKEN)  # local development: loopback only
    assert call(local, GATEWAY, "/api/tutor/queue", GOOD).status_code == 403
    assert TestClient(student).get("/api/writing/levels").status_code == 200


def test_tutor_evaluation_reaches_the_student(env):
    app, url, schema = env
    sid = call(app, GATEWAY, "/api/tutor/queue", GOOD).json()["submissions"][0]["submission_id"]
    scores = {c: 3 for c in L1["target_criteria"]}
    saved = call(app, GATEWAY, f"/api/tutor/submissions/{sid}/evaluation", GOOD, "PUT",
                 {"scores": scores, "strengths": ["Muy buena ortografía."], "complete": True})
    assert saved.status_code == 200 and saved.json()["status"] == "completed"
    student = TestClient(create_app(url, schema, SYNTHETIC, tutor_token=""))
    assert "Muy buena ortografía." in student.get(f"/api/writing/exercises/{L1['exercise_id']}").text


# ------------------------------------------------------------------ the real server process

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_real_server_ignores_forwarded_headers():
    """uvicorn trusts X-Forwarded-For from 127.0.0.1 by default; the tutor service must not."""
    assert UVICORN_OPTIONS["proxy_headers"] is False
    port = _free_port()
    code = ("import uvicorn; from app.tutor_main import create_tutor_app, UVICORN_OPTIONS as o; "
            f"uvicorn.run(create_tutor_app('postgresql://unused/x_test'), **{{**o, 'host': '127.0.0.1', "
            f"'port': {port}, 'log_level': 'warning'}})")
    env = {**os.environ, "MENTOR_PRO_TUTOR_TOKEN": TOKEN, "MENTOR_PRO_TUTOR_ALLOWED_HOSTS": "10.255.255.1"}
    proc = subprocess.Popen([sys.executable, "-c", code], cwd=REPO, env=env)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/tutor/queue",
                                         headers={**GOOD, "X-Forwarded-For": "10.255.255.1"})
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(request, timeout=5)
        assert refused.value.code == 403
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_authorised_request_without_database_is_a_defined_503(monkeypatch):
    unreachable = create_tutor_app("postgresql://127.0.0.1:1/x_test?connect_timeout=2", TOKEN, GATEWAY)
    response = call(unreachable, GATEWAY, "/api/tutor/queue", GOOD)
    assert response.status_code == 503 and response.json()["error"] == "database_unavailable"
    from curriculum import db as cdb

    def missing():
        raise cdb.ConfigurationError("DATABASE_URL is not set")
    monkeypatch.setattr(cdb, "database_url", missing)
    unconfigured = create_tutor_app(None, TOKEN, GATEWAY)
    response = call(unconfigured, GATEWAY, "/api/tutor/queue", GOOD)
    assert response.status_code == 503 and response.json()["error"] == "database_unavailable"
    assert call(unconfigured, "192.168.50.23", "/api/tutor/queue", GOOD).status_code == 403  # boundary first


@pytest.mark.parametrize("env_override", [{"MENTOR_PRO_TUTOR_TOKEN": ""},
                                          {"MENTOR_PRO_TUTOR_ALLOWED_HOSTS": "172.19.0.0/16"}])
def test_refused_start_exits_with_the_configuration_code(env_override, tmp_path):
    env = {**os.environ, "MENTOR_PRO_TUTOR_TOKEN": TOKEN, "MENTOR_PRO_TUTOR_ALLOWED_HOSTS": GATEWAY, **env_override}
    proc = subprocess.run([sys.executable, "-m", "app.tutor_main"], cwd=tmp_path, env={
        **env, "PYTHONPATH": str(REPO)}, capture_output=True, text=True, timeout=60)
    assert proc.returncode == EX_CONFIG and proc.stderr.startswith("tutor configuration rejected: ")
    assert TOKEN not in proc.stderr + proc.stdout
