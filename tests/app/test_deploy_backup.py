"""Restore-checked backups (T042, ADR-033 increment I2): `deploy/mentorpro backup` and `verify-backup`.

Synthetic data only, in a dedicated schema of the isolated test database. The local provider restores into a
throwaway initdb cluster; the Docker tests (skipped where Docker is absent) use a test-owned "live" container and
the production provider: disposable container, internal network and volume. Never a production resource.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import psycopg
import pytest

from curriculum import db

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "mentorpro"
SCHEMA = "t042_backup"
SH = shutil.which("sh")


def _pg_bin():
    """Directory of PostgreSQL 17 client and server tools, or None."""
    found = shutil.which("pg_ctl")
    candidates = [str(Path(found).parent)] if found else []
    candidates += sorted(glob.glob(r"C:\Program Files\PostgreSQL\17\bin")) + sorted(
        glob.glob("/usr/lib/postgresql/17/bin"))
    for folder in candidates:
        if all(shutil.which(tool, path=folder) for tool in ("initdb", "pg_ctl", "pg_dump", "pg_restore", "psql")):
            version = subprocess.run([shutil.which("pg_dump", path=folder), "--version"], capture_output=True, text=True)
            if " 17." in version.stdout:
                return folder
    return None


PG_BIN = _pg_bin()
local_only = pytest.mark.skipif(not (SH and PG_BIN), reason="sh and PostgreSQL 17 tools are needed")


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _posix(path):
    return Path(path).as_posix()


def run(*args, **env):
    base = {**os.environ, "PATH": os.pathsep.join(filter(None, [PG_BIN, os.environ["PATH"]])),
            "MENTORPRO_BACKUP_SCHEMAS": SCHEMA, "MENTORPRO_PYTHON": _posix(sys.executable), **env}
    return subprocess.run([SH, str(SCRIPT), *args], env=base, capture_output=True, text=True, timeout=300)


BACKUP_DB = "mentor_pro_backup_test"


@pytest.fixture(scope="module")
def live():
    """A dedicated, disposable *_test database holding only the synthetic schema, so the backup's scope check
    (every user schema must be expected) sees exactly what the test put there: accents, timestamps, JSON, NULLs."""
    admin_url = db.require_test_database(db.test_database_url())
    url = db.require_test_database(re.sub(r"/mentor_pro_test(?=$|\?)", f"/{BACKUP_DB}", admin_url))
    assert url != admin_url
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {BACKUP_DB} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {BACKUP_DB}")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        conn.execute(f"CREATE TABLE {SCHEMA}.note (id int PRIMARY KEY, body text, at timestamptz, extra jsonb)")
        conn.execute(f"CREATE TABLE {SCHEMA}.empty (id int)")
        conn.execute(f"""INSERT INTO {SCHEMA}.note SELECT g, 'Ñandú número ' || g, '2026-10-28 12:00+00'::timestamptz
                         + g * interval '1 minute', CASE WHEN g % 3 = 0 THEN NULL ELSE jsonb_build_object('k', g) END
                         FROM generate_series(1, 120) g""")
    yield url
    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {BACKUP_DB} WITH (FORCE)")


def local_env(tmp_path, url):
    return {"MENTORPRO_PROVIDER": "local", "MENTORPRO_LIVE_URL": url, "MENTORPRO_VERIFY_PORT": str(_free_port()),
            "MENTORPRO_BACKUPS": _posix(tmp_path / "backups"), "TMPDIR": _posix(tmp_path)}


@pytest.fixture(scope="module")
def made(live, tmp_path_factory):
    """One verified backup, copied by the tests that damage it."""
    folder = tmp_path_factory.mktemp("made")
    result = run("backup", **local_env(folder, live))
    return folder, result


def copy_of(made, tmp_path):
    folder, _ = made
    shutil.copytree(folder / "backups", tmp_path / "backups")
    return only_dump(tmp_path)


def scratch_left(tmp_path):
    return [p for p in tmp_path.iterdir() if p.name.startswith("mentorpro-verify-")]


def only_dump(tmp_path):
    (dump,) = (tmp_path / "backups").glob("*.dump")
    return dump


@local_only
def test_backup_is_restored_and_compared_before_backup_ok(live, made, tmp_path):
    tmp_path, result = made
    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"^BACKUP OK .*mentor_pro_\d{4}-\d\d-\d\d_\d{6}\.dump sha256:[0-9a-f]{64}$", result.stdout, re.M)
    assert "cleanup verified: disposable instance removed" in result.stdout
    assert "dump: 2 tables, 120 rows" in result.stdout
    assert not scratch_left(tmp_path)

    dump = only_dump(tmp_path)
    record = dump.with_name(dump.name + ".verify").read_text(encoding="utf-8")
    assert f"table {SCHEMA}.note 120" in record and f"table {SCHEMA}.empty 0" in record
    assert "restore pass" in record and record.rstrip().endswith("result BACKUP OK")
    assert re.search(r"^fingerprint [0-9a-f]{64}$", record, re.M)
    # Deploy evidence (T044): database, schema state (no writing tables here: fresh) and verification time.
    assert f"\ndatabase {BACKUP_DB}\n" in record and "\nschema_state fresh none\n" in record
    assert re.search(r"^verified \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", record, re.M)
    assert "Ñandú" not in record and "Ñandú" not in result.stdout and live not in result.stdout  # no data, no URL
    if os.name == "posix":
        assert dump.stat().st_mode & 0o777 == 0o600 and (tmp_path / "backups").stat().st_mode & 0o777 == 0o700

    again = run("verify-backup", _posix(dump), **local_env(tmp_path, live))
    assert again.returncode == 0 and "VERIFY OK" in again.stdout and not scratch_left(tmp_path)
    assert dump.with_name(dump.name + ".verify").read_text(encoding="utf-8").rstrip().endswith(" OK")


@local_only
def test_corrupted_or_truncated_dump_fails_its_checksum(live, made, tmp_path):
    env = local_env(tmp_path, live)
    dump = copy_of(made, tmp_path)
    data = dump.read_bytes()
    dump.write_bytes(data[: len(data) // 2])  # incomplete
    result = run("verify-backup", _posix(dump), **env)
    assert result.returncode == 1 and "VERIFY FAILED: file checksum differs" in result.stdout
    assert "VERIFY OK" not in result.stdout


@local_only
def test_unrestorable_dump_fails_and_cleans_up(live, made, tmp_path):
    """A record that matches the file, but the file is not a restorable archive."""
    env = local_env(tmp_path, live)
    dump = copy_of(made, tmp_path)
    data = bytearray(dump.read_bytes())
    data[len(data) // 2: len(data) // 2 + 4096] = os.urandom(4096)  # damaged in the middle
    dump.write_bytes(bytes(data))
    record = dump.with_name(dump.name + ".verify")
    text = re.sub(r"^sha256 \w+$", "sha256 " + hashlib.sha256(bytes(data)).hexdigest(),
                  record.read_text(encoding="utf-8"), flags=re.M)
    record.write_text(text, encoding="utf-8", newline="\n")
    result = run("verify-backup", _posix(dump), **env)
    assert result.returncode == 1, result.stdout
    assert re.search(r"VERIFY FAILED: (dump is not restorable|restored data differs)", result.stdout)
    assert "cleanup verified" in result.stdout and not scratch_left(tmp_path)
    assert "FAILED restore" in record.read_text(encoding="utf-8")


@local_only
def test_restore_that_does_not_match_the_source_is_not_ok(live, made, tmp_path):
    env = local_env(tmp_path, live)
    dump = copy_of(made, tmp_path)
    record = dump.with_name(dump.name + ".verify")
    record.write_text(re.sub(r"^fingerprint \w+$", "fingerprint " + "0" * 64, record.read_text(encoding="utf-8"),
                             flags=re.M), encoding="utf-8", newline="\n")
    result = run("verify-backup", _posix(dump), **env)
    assert result.returncode == 1 and "VERIFY FAILED: restored data differs from the source (2 tables, 120 rows)" \
        in result.stdout


@local_only
def test_failed_backup_is_recorded_and_never_ok(live, tmp_path):
    env = {**local_env(tmp_path, live), "MENTORPRO_LIVE_URL": live.replace(f"/{BACKUP_DB}", "/missing_db_test")}
    result = run("backup", **env)
    assert result.returncode == 1 and "BACKUP FAILED: schema list not readable" in result.stdout
    assert "BACKUP OK" not in result.stdout
    (record,) = (tmp_path / "backups").glob("*.verify")
    assert record.read_text(encoding="utf-8").rstrip().endswith("result BACKUP FAILED: schema list not readable")


@local_only
def test_existing_dump_is_never_overwritten(live, tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    now = datetime.now()
    for second in range(0, 4):  # the names this run can choose
        name = (now + timedelta(seconds=second)).strftime("mentor_pro_%Y-%m-%d_%H%M%S.dump")
        (folder / name).write_bytes(b"keep")
    result = run("backup", **local_env(tmp_path, live))
    assert result.returncode == 1 and "already exists" in result.stdout
    assert all(p.read_bytes() == b"keep" for p in folder.glob("*.dump"))


@local_only
def test_tables_outside_the_expected_schemas_fail_the_backup(live, tmp_path):
    """Incomplete scope is detected, never silently excluded."""
    with psycopg.connect(live, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA t042_stray")
        conn.execute("CREATE TABLE t042_stray.forgotten (id int)")
        conn.execute("CREATE TABLE public.also_forgotten (id int)")
    try:
        result = run("backup", **local_env(tmp_path, live))
        assert result.returncode == 1 and "BACKUP OK" not in result.stdout
        assert "BACKUP FAILED: unexpected schema(s) with tables: public t042_stray" in result.stdout
        listed = run("backup", **{**local_env(tmp_path / "b", live),
                                   "MENTORPRO_BACKUP_SCHEMAS": f"{SCHEMA} t042_stray public"})
        assert listed.returncode == 0 and "dump: 4 tables, 120 rows" in listed.stdout  # all of them fingerprinted
    finally:
        with psycopg.connect(live, autocommit=True) as conn:
            conn.execute("DROP SCHEMA t042_stray CASCADE")
            conn.execute("DROP TABLE public.also_forgotten")


@local_only
def test_missing_expected_schema_fails_the_backup(live, tmp_path):
    result = run("backup", **{**local_env(tmp_path, live), "MENTORPRO_BACKUP_SCHEMAS": f"{SCHEMA} writing"})
    assert result.returncode == 1 and "BACKUP FAILED: expected schema(s) missing: writing" in result.stdout


def test_local_provider_refuses_a_database_that_is_not_a_test_database(tmp_path):
    if not SH:
        pytest.skip("sh is needed")
    result = run("backup", MENTORPRO_PROVIDER="local", MENTORPRO_LIVE_URL="postgresql://x@127.0.0.1/mentor_pro",
                 MENTORPRO_BACKUPS=_posix(tmp_path / "b"))
    assert result.returncode == 1 and "BACKUP REFUSED" in result.stdout and not (tmp_path / "b").exists()


@local_only
def test_fingerprint_is_deterministic_and_detects_changed_data(live, made, tmp_path):
    """Runs last in this module: it changes the synthetic data."""
    second = run("backup", **local_env(tmp_path / "b", live))
    assert second.returncode == 0

    def fingerprint(folder):
        (record,) = (folder / "backups").glob("*.verify")
        return re.search(r"^fingerprint (\w+)$", record.read_text(encoding="utf-8"), re.M).group(1)

    assert fingerprint(made[0]) == fingerprint(tmp_path / "b")
    with psycopg.connect(live, autocommit=True) as conn:
        conn.execute(f"UPDATE {SCHEMA}.note SET body = 'cambiado' WHERE id = 7")  # same counts, other content
    third = run("backup", **local_env(tmp_path / "c", live))
    assert third.returncode == 0 and fingerprint(tmp_path / "c") != fingerprint(made[0])



# ------------------------------------------------------------------ Docker (CI runners; skipped without Docker)

def _docker_ready():
    docker = shutil.which("docker")
    return bool(docker and SH and subprocess.run([docker, "info"], capture_output=True).returncode == 0)


# CI sets MENTORPRO_REQUIRE_DOCKER=1 on Linux: there a missing Docker fails these tests instead of skipping them.
DOCKER_REQUIRED = os.environ.get("MENTORPRO_REQUIRE_DOCKER") == "1"


@pytest.fixture()
def docker():
    if not _docker_ready():
        if DOCKER_REQUIRED:
            pytest.fail("Docker is required here (MENTORPRO_REQUIRE_DOCKER=1) but not available")
        pytest.skip("Docker is not available")


def _verify_resources():
    out = []
    for kind in (["ps", "-a"], ["volume", "ls"], ["network", "ls"]):
        listed = subprocess.run(["docker", *kind, "-q", "--filter", "name=mentorpro-verify-"], capture_output=True,
                                text=True).stdout.split()
        out += listed
    return out


def test_docker_backup_uses_an_isolated_disposable_instance(docker, tmp_path):
    """Production provider end to end against a test-owned 'live' container with synthetic data."""
    name = f"mentorpro-test-live-{uuid.uuid4().hex[:8]}"
    assert not name.startswith("mentor-pro-")  # never a production container name (mentor-pro-*)
    subprocess.run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                    "-e", "POSTGRES_USER=mentor_pro_admin", "-e", "POSTGRES_DB=mentor_pro", "postgres:17.6"],
                   check=True, capture_output=True)
    try:
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "mentor_pro_admin"],
                              capture_output=True).returncode == 0:
                break
            time.sleep(1)
        seed = (f"CREATE SCHEMA {SCHEMA}; CREATE TABLE {SCHEMA}.note (id int, body text);"
                f"INSERT INTO {SCHEMA}.note SELECT g, 'texto ' || g FROM generate_series(1, 40) g;")
        subprocess.run(["docker", "exec", "-i", name, "psql", "-U", "mentor_pro_admin", "-d", "mentor_pro", "-q"],
                       input=seed, text=True, check=True, capture_output=True)
        before = set(_verify_resources())
        result = run("backup", MENTORPRO_POSTGRES_CONTAINER=name, MENTORPRO_BACKUPS=_posix(tmp_path / "backups"))
        assert result.returncode == 0, result.stdout + result.stderr
        assert "BACKUP OK" in result.stdout and "dump: 1 tables, 40 rows" in result.stdout
        assert re.search(r"cleanup verified: container, volume and network mentorpro-verify-\d+ removed", result.stdout)
        assert set(_verify_resources()) == before
        dump = only_dump(tmp_path)
        again = run("verify-backup", _posix(dump), MENTORPRO_POSTGRES_CONTAINER=name)
        assert again.returncode == 0 and "VERIFY OK" in again.stdout and set(_verify_resources()) == before
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)  # the test's own container only


def test_compose_file_is_valid_for_the_docker_compose_cli(docker, tmp_path):
    """PO correction 4 (T041): `docker compose config` on deploy/compose.yml with empty stand-in env files."""
    text = (REPO / "deploy" / "compose.yml").read_text(encoding="utf-8")
    for name in ("app.env", "tutor.env", "postgres.env"):
        (tmp_path / name).write_text("", encoding="utf-8")
        text = text.replace(f"/etc/mentor-pro/{name}", _posix(tmp_path / name))
    compose = tmp_path / "compose.yml"
    compose.write_text(text, encoding="utf-8")
    image = "ghcr.io/jonnabio/mentor-pro@sha256:" + "a" * 64
    ok = subprocess.run(["docker", "compose", "-f", str(compose), "config", "--quiet"], capture_output=True,
                        text=True, env={**os.environ, "MENTOR_PRO_IMAGE": image})
    assert ok.returncode == 0, ok.stderr
    missing = subprocess.run(["docker", "compose", "-f", str(compose), "config", "--quiet"], capture_output=True,
                             text=True, env={k: v for k, v in os.environ.items() if k != "MENTOR_PRO_IMAGE"})
    assert missing.returncode != 0 and "MENTOR_PRO_IMAGE" in missing.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
