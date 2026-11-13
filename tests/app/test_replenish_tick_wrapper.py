"""T066: the cron wrapper keeps the real exit status, classifies failures and redacts output.

Runs deploy/mentorpro-replenish-tick.sh with a fake `docker` first on PATH; no container,
database or network is touched.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy" / "mentorpro-replenish-tick.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")

FAKE_DOCKER = """#!/usr/bin/env bash
if [ "$1" = "inspect" ]; then
  [ -n "${FAKE_INSPECT_OUT:-}" ] && printf '%s\\n' "$FAKE_INSPECT_OUT"
  exit "${FAKE_INSPECT_RC:-0}"
fi
if [ "$1" = "exec" ]; then
  printf '%b' "${FAKE_EXEC_OUT:-}"
  exit "${FAKE_EXEC_RC:-0}"
fi
exit 99
"""


def _posix(p: Path) -> str:
    out = subprocess.run([BASH, "-c", 'cygpath -u "$1" 2>/dev/null || printf %s "$1"', "_", str(p)],
                         capture_output=True, text=True)
    return out.stdout.strip() or str(p)


@pytest.fixture()
def run(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER, newline="\n")
    docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
    logdir = tmp_path / "runs" / "nested"

    def _run(*args, **fake):
        env = dict(os.environ)
        env.update({k.upper(): str(v) for k, v in fake.items()})
        env.setdefault("FAKE_INSPECT_OUT", "true")
        env["MENTOR_PRO_REPLENISH_LOG_DIR"] = _posix(logdir)
        cmd = f'PATH="{_posix(bindir)}:$PATH" exec "{_posix(SCRIPT)}" "$@"'
        proc = subprocess.run([BASH, "-c", cmd, "_", *args], capture_output=True, text=True, env=env)
        log = logdir / "replenish-tick.log"
        return proc.returncode, (log.read_text() if log.exists() else ""), proc

    return _run


def test_ok_tick_logged_and_exit_zero(run):
    rc, log, _ = run(fake_exec_out="TICK OK 7 reason=None calls=10 generated=2\\n{}\\n")
    assert rc == 0
    assert "RESULT=OK rc=0 TICK OK 7" in log
    assert log.count("\n") == 1


def test_skipped_tick_is_distinct_from_ok(run):
    rc, log, _ = run(fake_exec_out="TICK SKIPPED 8 reason=disabled calls=0\\n")
    assert rc == 0
    assert "RESULT=SKIPPED rc=0 TICK SKIPPED 8 reason=disabled" in log


def test_failed_tick_keeps_exit_5_and_diagnostics(run):
    rc, log, _ = run(fake_exec_rc=5, fake_exec_out="TICK FAILED 9 reason=None\\nTraceback x\\nValueError: boom\\n")
    assert rc == 5
    assert "RESULT=TICK_FAILED rc=5 TICK FAILED 9" in log
    assert "    ValueError: boom" in log


def test_other_nonzero_exit_preserved(run):
    rc, log, _ = run(fake_exec_rc=1, fake_exec_out="REFUSED (nothing changed): bad setting\\n")
    assert rc == 1
    assert "RESULT=ERROR rc=1 REFUSED" in log


def test_missing_container(run):
    rc, log, _ = run(fake_inspect_rc=1, fake_inspect_out="Error: No such object: mentor-pro-app-1")
    assert rc == 20
    assert "RESULT=CONTAINER_MISSING rc=20" in log


def test_stopped_container(run):
    rc, log, _ = run(fake_inspect_out="false")
    assert rc == 20
    assert "RESULT=CONTAINER_MISSING rc=20" in log and "running=false" in log


def test_docker_daemon_failure(run):
    rc, log, _ = run(fake_inspect_rc=1, fake_inspect_out="Cannot connect to the Docker daemon")
    assert rc == 21
    assert "RESULT=DOCKER_ERROR rc=21 step=inspect" in log


def test_docker_exec_failure(run):
    rc, log, _ = run(fake_exec_rc=126, fake_exec_out="OCI runtime exec failed\\n")
    assert rc == 21
    assert "RESULT=DOCKER_ERROR rc=21 step=exec docker_rc=126" in log


def test_secrets_redacted(run):
    secret_out = (
        "TICK FAILED 10 reason=None\\n"
        "OPENROUTER_API_KEY=sk-or-v1-abcdef123456789\\n"
        "TUTOR_TOKEN: 'tok-zzz999'\\n"
        "Authorization: Bearer abc.def.ghi\\n"
        "postgresql://mentor:hunter2pass@db:5432/mentor_pro\\n"
    )
    rc, log, _ = run(fake_exec_rc=5, fake_exec_out=secret_out)
    assert rc == 5
    for leaked in ("sk-or-v1-abcdef123456789", "tok-zzz999", "abc.def.ghi", "hunter2pass"):
        assert leaked not in log
    assert "[REDACTED]" in log


def test_diagnostics_bounded(run):
    many = "".join(f"line{i}\\n" for i in range(100))
    rc, log, _ = run(fake_exec_rc=5, fake_exec_out="TICK FAILED 11\\n" + many)
    assert rc == 5
    assert len(log.splitlines()) == 1 + 20


def test_check_creates_log_dir(run, tmp_path):
    rc, log, proc = run("--check")
    assert rc == 0
    assert "CHECK_OK" in proc.stdout
    assert (tmp_path / "runs" / "nested").is_dir()
    assert "RESULT=CHECK_OK" in log


def test_unwritable_log_dir(run, tmp_path):
    blocker = tmp_path / "runs"
    blocker.write_text("not a directory")
    rc, _, proc = run()
    assert rc == 22
    assert "RESULT=LOG_ERROR" in proc.stderr
