"""verify.sh records every gate and never reports a pass it cannot show (T018)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is required to run .ace/scripts/verify.sh")


def run_gate(tmp_path: Path, test_cmd: str, lint_cmd: str = "") -> tuple[subprocess.CompletedProcess, str]:
    config = tmp_path / "aceconfig"
    config.write_text(f'verify:\n  test_cmd: "{test_cmd}"\n  lint_cmd: "{lint_cmd}"\n  typecheck_cmd: ""\n',
                      encoding="utf-8")
    logs = tmp_path / "logs"
    env = {**os.environ, "VERIFY_LOG_DIR": logs.as_posix()}
    result = subprocess.run([BASH, (REPO / ".ace" / "scripts" / "verify.sh").as_posix(), config.as_posix()],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    summaries = list(logs.glob("*/summary.txt"))
    assert len(summaries) == 1, result.stdout
    return result, summaries[0].read_text(encoding="utf-8")


def last_line(result: subprocess.CompletedProcess) -> str:
    return result.stdout.strip().splitlines()[-1]


def test_pass_records_exit_and_duration(tmp_path):
    result, summary = run_gate(tmp_path, "echo ok", "echo linted")
    assert result.returncode == 0 and last_line(result) == "VERIFY_RESULT=pass gate=all"
    assert "gate=test exit=0 duration_ms=" in summary and "gate=lint exit=0" in summary


def test_failure_keeps_stdout_and_stderr_separately(tmp_path):
    result, summary = run_gate(tmp_path, "echo some-output; echo the-error >&2; exit 3")
    assert result.returncode == 1 and last_line(result) == "VERIFY_RESULT=fail gate=test"
    assert "gate=test exit=3" in summary and "gate=lint" not in summary
    assert "the-error" in result.stdout and "some-output" in result.stdout
    log_dir = next((tmp_path / "logs").iterdir())
    assert (log_dir / "test.stderr.log").read_text().strip() == "the-error"
    assert (log_dir / "test.stdout.log").read_text().strip() == "some-output"


def test_silent_success_is_not_a_pass(tmp_path):
    result, summary = run_gate(tmp_path, "true")
    assert result.returncode == 1 and last_line(result) == "VERIFY_RESULT=fail gate=test"
    assert "exit=125" in summary and "no_output=1" in summary


def test_termination_by_signal_is_reported(tmp_path):
    result, summary = run_gate(tmp_path, "echo started; kill -9 $$")
    assert result.returncode == 1 and last_line(result) == "VERIFY_RESULT=fail gate=test"
    assert "exit=137" in summary and "terminated_by_signal=9" in summary
