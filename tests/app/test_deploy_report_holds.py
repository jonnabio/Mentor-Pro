"""T072 rollback safeguard (ADR-038 section 7): never run an image that ignores open student-report holds.

Deploy, rollback and preflight run an image without the report-hold capability label only when PostgreSQL proves
that no student report is open. An unrecognised label or an unreadable count refuses (fail closed). The capability
is read only from the labels of an image whose digest was verified, never from a manifest file.

Unit tests need neither Docker nor a server; the psql test runs the real query against mentor_pro_test when psql
is installed (CI).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest

from test_deploy_rollout import (CURRENT, DIGEST, REPOSITORY, SHA, manifest, md, provenance_cfg, release,
                                 state_cfg)

CAP = md.LABEL_REPORT_HOLDS
OLD = {md.LABEL_MIN: "0001", md.LABEL_MAX: "0001"}  # a release built before T072
NEW = {**OLD, CAP: "1"}
BLOCKED = "report holds BLOCKED"


# ---------------------------------------------------------------- the rules

@pytest.mark.parametrize("labels, capability", [
    (NEW, "yes"), (OLD, "no"), (None, "no"), ({}, "no"),
    ({**OLD, CAP: "0"}, "unknown"), ({**OLD, CAP: ""}, "unknown"), ({**OLD, CAP: "true"}, "unknown"),
    ({**OLD, CAP: " 1"}, "unknown"),
])
def test_capability_from_verified_labels(labels, capability):
    assert md.report_capability(labels) == capability


# The compatibility matrix the PO asked for (requirement 4).
@pytest.mark.parametrize("capability, open_reports, allowed", [
    ("yes", 0, True), ("yes", 5, True), ("yes", None, True),   # compatible: the existing gates decide
    ("no", 0, True),                                           # incompatible, nothing to hold
    ("no", 1, False), ("no", 40, False),                       # incompatible with open reports
    ("no", None, False),                                       # database unreadable: fail closed
    ("unknown", 0, False), ("unknown", None, False),           # unknown capability: fail closed
])
def test_report_hold_matrix(capability, open_reports, allowed):
    verdict = md.report_hold_verdict(capability, open_reports)
    assert verdict.startswith("BLOCKED") is not allowed


@pytest.mark.parametrize("answer, count", [
    ("open|0\n", 0), ("open|3\n", 3), ("open|none\n", 0), ("\r\nopen|12\r\n", 12),
    ("", None), ("open|\n", None), ("open|-1\n", None), ("open|3\nopen|4\n", None), ("ERROR\n", None),
    ("3\n", None),
])
def test_open_report_answer(answer, count):
    assert md.parse_open_reports(answer) == count


def test_report_query_is_read_only_and_counts_open_reports():
    sql = md.OPEN_REPORTS_SQL
    assert sql.startswith("SET default_transaction_read_only = on;")
    body = sql.upper()
    for verb in ("INSERT", "UPDATE", "DELETE", "ALTER", "DROP", "TRUNCATE", "CREATE"):
        assert verb not in body
    assert "status = 'open'" in sql and "generation.question_report" in sql


def test_release_images_declare_the_capability():
    """CI builds every image with release.labels(), and check-labels proves the image carries them."""
    assert release.labels("v2026.11.19-2", SHA, "2026-11-19T12:00:00Z")[CAP] == "1"


def test_capability_cannot_come_from_the_manifest_file():
    data = manifest()
    data["capabilities"] = {"report-holds": True}
    assert any("fields differ" in p for p in md.validate_manifest(data, REPOSITORY))


def test_capability_is_read_from_the_verified_image_only():
    """No code path takes the capability from the manifest, the arguments or the environment."""
    source = (Path(md.__file__)).read_text(encoding="utf-8")
    assert source.count("check_report_holds(cfg, labels)") == 1  # preflight (advisory)
    assert source.count("report_hold_barrier(cfg, labels)") == 2  # deploy and rollback, around the switch
    assert not re.search(r"add_argument\([^)]*(report|force|override)", source)  # no operator bypass


# ---------------------------------------------------------------- the count, through docker exec psql

FAKE_PSQL = '''import sys
sys.stdin.read()
mode = {mode!r}
if mode == "fail":
    sys.stderr.write("psql: connection refused\\n")
    sys.exit(2)
sys.stdout.write(mode)
'''


def counting_cfg(tmp_path, mode):
    fake = tmp_path / "fake_docker.py"
    fake.write_text(FAKE_PSQL.format(mode=mode), encoding="utf-8")
    cfg = state_cfg(tmp_path, [sys.executable, str(fake)])
    cfg.update(pg_container="pg", pg_user="u", pg_db="d")
    return cfg


@pytest.mark.parametrize("mode, count", [("open|2\n", 2), ("open|none\n", 0), ("garbage\n", None), ("fail", None)])
def test_read_open_reports(tmp_path, mode, count):
    assert md.read_open_reports(counting_cfg(tmp_path, mode)) == count


def test_unreachable_postgres_is_unreadable(tmp_path):
    cfg = state_cfg(tmp_path, ["no-such-docker-binary-here"])
    cfg.update(pg_container="pg", pg_user="u", pg_db="d")
    assert md.read_open_reports(cfg) is None


@pytest.mark.parametrize("labels, mode, blocked", [
    (NEW, "fail", False), (OLD, "open|0\n", False), (OLD, "open|none\n", False),
    (OLD, "open|1\n", True), (OLD, "fail", True), (OLD, "garbage\n", True), ({**OLD, CAP: "2"}, "open|0\n", True),
])
def test_check_report_holds(tmp_path, labels, mode, blocked):
    cfg = counting_cfg(tmp_path, mode)
    if blocked:
        with pytest.raises(md.Refused, match=BLOCKED):
            md.check_report_holds(cfg, labels)
    else:
        md.check_report_holds(cfg, labels)


def test_compatible_image_needs_no_database_read(tmp_path, monkeypatch):
    def never(cfg):
        raise AssertionError("the count is read only for an image without the capability")

    monkeypatch.setattr(md, "read_open_reports", never)
    assert md.check_report_holds(state_cfg(tmp_path), NEW) == "enforced"


# ---------------------------------------------------------------- deploy, rollback and preflight

class Changed(Exception):
    """Raised by the fake `change`: the containers would have been changed."""


@pytest.fixture()
def gates(monkeypatch):
    """Every existing gate passes; only the image labels and the report count vary."""
    state = {"labels": NEW, "open": 0, "changed": []}
    monkeypatch.setattr(md, "read_live", lambda cfg: CURRENT)
    monkeypatch.setattr(md, "check_preflight", lambda *a: None)
    monkeypatch.setattr(md, "check_backup", lambda *a: "c" * 64)
    monkeypatch.setattr(md, "read_backup_record", lambda dump: {})
    monkeypatch.setattr(md, "verified_labels", lambda cfg, m: state["labels"])
    monkeypatch.setattr(md, "pull_and_inspect", lambda cfg, ref, digest: state["labels"])
    monkeypatch.setattr(md, "read_open_reports", lambda cfg: state["open"])
    state["events"] = []

    class FakeBarrier:
        def __init__(self, cfg):
            pass

        def start(self):
            state["events"].append("barrier on")
            return state["open"]

        def close(self):
            state["events"].append("barrier off")

        terminated = 0

    monkeypatch.setattr(md, "ReportBarrier", FakeBarrier)

    def change(cfg, args, action, ref, version, live, backup_sha, propose_rollback=True):
        state["changed"].append((action, ref))
        state["events"].append(action)
        return 0

    monkeypatch.setattr(md, "change", change)
    return state


def full_cfg(cfg):
    cfg.update(pg_container="pg", pg_user="u", pg_db="d")
    return cfg


def deploy_args(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    return type("A", (), {"manifest": str(path), "backup": str(tmp_path / "x.dump"), "window": "W-1",
                          "authorization": "PO-1", "to": None})


@pytest.mark.parametrize("labels, open_reports, allowed", [
    (NEW, 3, True), (NEW, None, True), (OLD, 0, True), (OLD, 3, False), (OLD, None, False),
    ({**OLD, CAP: "yes"}, 0, False),
])
def test_deploy(tmp_path, gates, labels, open_reports, allowed):
    gates.update(labels=labels, open=open_reports)
    cfg = full_cfg(state_cfg(tmp_path))
    args = deploy_args(tmp_path)
    if allowed:
        assert md.deploy(args, cfg) == 0 and gates["changed"] == [("deploy", f"{REPOSITORY}@{DIGEST}")]
        # without the capability, the barrier spans the count and the switch
        assert gates["events"] == (["deploy"] if labels is NEW else ["barrier on", "deploy", "barrier off"])
    else:
        with pytest.raises(md.Refused, match=BLOCKED):
            md.deploy(args, cfg)
        assert gates["changed"] == []
        assert not (cfg["state"] / "manifests").exists()  # refused before anything was stored or changed


def test_deploy_refusal_through_the_cli(tmp_path, gates, monkeypatch, capsys):
    gates.update(labels=OLD, open=2)
    cfg = full_cfg(state_cfg(tmp_path))
    monkeypatch.setattr(md, "settings", lambda: cfg)
    args = deploy_args(tmp_path)
    code = md.main(["deploy", args.manifest, "--backup", args.backup, "--window", "W-1", "--authorization", "PO-1"])
    out = capsys.readouterr().out
    assert code == 1 and "DEPLOY REFUSED: report holds BLOCKED: 2 open student report(s)" in out
    assert "Recovery: docs/runbooks/production-deployment.md" in out and gates["changed"] == []


def rollback_cfg(tmp_path, legacy=False):
    current = f"{REPOSITORY}@sha256:" + "f" * 64
    target = f"{REPOSITORY}@{DIGEST}"
    cfg = provenance_cfg(tmp_path, results=[(target, "OK")], manifest_for=None if legacy else DIGEST,
                         legacy_for=DIGEST if legacy else None)
    if legacy:  # an adopted pre-script image, with the schema range of the fake labels
        md.legacy_path(cfg, DIGEST).write_text(json.dumps({"image": target, "verified": "running",
                                                           "schema": ["0001", "0001"]}), encoding="utf-8")
    full_cfg(cfg)
    cfg["release_env"].write_text(f"MENTOR_PRO_IMAGE={current}\n", encoding="utf-8")
    cfg["release_env"].with_name("release.env.previous").write_text(f"MENTOR_PRO_IMAGE={target}\n",
                                                                     encoding="utf-8")
    return cfg, target


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("labels, open_reports, allowed", [
    (NEW, 4, True), (OLD, 0, True), (OLD, 4, False), (OLD, None, False), ({**OLD, CAP: "0"}, 0, False),
])
def test_rollback(tmp_path, gates, legacy, labels, open_reports, allowed):
    gates.update(labels=labels, open=open_reports)
    cfg, target = rollback_cfg(tmp_path, legacy)
    assert md.previous_image(cfg) == target
    args = deploy_args(tmp_path)
    if allowed:
        assert md.rollback(args, cfg) == 0 and gates["changed"] == [("rollback", target)]
        assert gates["events"] == (["rollback"] if labels is NEW else ["barrier on", "rollback", "barrier off"])
    else:
        with pytest.raises(md.Refused, match=BLOCKED):
            md.rollback(args, cfg)
        assert gates["changed"] == [] and gates["events"] in ([], ["barrier on", "barrier off"])
        refused = [r for r in md.releases(cfg) if r.get("action") == "rollback"]
        assert len(refused) == 1 and refused[0]["result"] == "REFUSED" and refused[0]["image"] == target
        assert md.current_image(cfg) != target  # release.env untouched


def test_preflight_reports_the_block(tmp_path, gates, monkeypatch, capsys):
    gates.update(labels=OLD, open=1)
    cfg = state_cfg(tmp_path)
    args = deploy_args(tmp_path)
    with pytest.raises(md.Refused, match=BLOCKED):
        md.preflight(args, cfg)
    assert not md.preflight_path(cfg, DIGEST).exists()  # no preflight evidence for a blocked image
    gates.update(labels=NEW)
    assert md.preflight(args, cfg) == 0 and md.preflight_path(cfg, DIGEST).exists()


# ---------------------------------------------------------------- the barrier against PostgreSQL (CI requires psql)

PSQL = shutil.which("psql")


def test_report_lock_is_the_application_lock():
    from app.practice import question_reports
    assert md.REPORT_LOCK == question_reports.REPORT_LOCK


@pytest.fixture()
def psql_url(bank, url, monkeypatch):  # noqa: F811
    """The real barrier and count against mentor_pro_test. CI sets MENTORPRO_REQUIRE_PSQL=1: a missing psql fails."""
    if not PSQL:
        if os.environ.get("MENTORPRO_REQUIRE_PSQL") == "1":
            pytest.fail("psql is required in CI (MENTORPRO_REQUIRE_PSQL=1)")
        pytest.skip("psql not installed (required in CI)")
    monkeypatch.setattr(md, "psql_cmd", lambda cfg: [PSQL, url, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"])
    return url


def two_questions(url, bank):  # noqa: F811
    from test_question_reports import by_cell, practice
    _, batch_id = bank
    return practice(url, list(by_cell(url, batch_id).values())[:2])


def open_now(url):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT count(*) FROM generation.question_report WHERE status = 'open'").fetchone()[0]


def waiting_for_report_lock(url):  # noqa: F811
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = %s "
                            "AND objid = %s AND objsubid = 2 AND NOT granted", md.REPORT_LOCK).fetchone()[0]


def test_query_on_postgres(psql_url, bank):
    from app.practice import question_reports
    url = psql_url
    assert md.read_open_reports({}) == 0
    session = two_questions(url, bank)
    question_reports.create(url, session, 1, "wrong_answer", None)
    question_reports.create(url, session, 2, "confusing", None)
    assert md.read_open_reports({}) == 2


def test_report_committed_before_the_barrier_is_counted(psql_url, bank):
    from app.practice import question_reports
    url = psql_url
    question_reports.create(url, two_questions(url, bank), 1, "wrong_answer", None)
    with pytest.raises(md.Refused, match="BLOCKED: 1 open student report"):
        with md.report_hold_barrier({}, OLD):
            raise AssertionError("no switch with an open report")
    assert waiting_for_report_lock(url) == 0


def test_in_flight_report_cannot_commit_across_the_switch(psql_url, bank):
    """The race the review named: a report arrives after the count but before the older image runs.

    Deterministic: the report request is started only after the barrier counted zero, and the switch happens only
    once PostgreSQL shows that request waiting for the report lock. It must never commit."""
    from app.practice import question_reports
    url = psql_url
    session = two_questions(url, bank)
    outcome = {}

    def student_reports():
        try:
            outcome["result"] = question_reports.create(url, session, 1, "wrong_answer", None)
        except psycopg.Error as exc:
            outcome["error"] = type(exc).__name__

    with md.report_hold_barrier({}, OLD) as _:
        thread = threading.Thread(target=student_reports)
        thread.start()
        deadline = time.monotonic() + 30
        while waiting_for_report_lock(url) == 0:
            assert thread.is_alive() and time.monotonic() < deadline, outcome
            time.sleep(0.05)
        assert open_now(url) == 0  # the switch to the older image happens here
    thread.join(30)
    assert not thread.is_alive()
    assert "result" not in outcome and "error" in outcome  # terminated, rolled back
    assert open_now(url) == 0
    assert waiting_for_report_lock(url) == 0
    # the lock is released: reports work again (e.g. a failed deploy left T072 running)
    assert question_reports.create(url, session, 2, "confusing", None)["already_reported"] is False


def test_barrier_session_holds_no_lock_after_failure(psql_url, bank):
    url = psql_url
    with pytest.raises(RuntimeError):
        with md.report_hold_barrier({}, OLD):
            raise RuntimeError("compose failed")
    with psycopg.connect(url) as conn:
        assert conn.execute("SELECT pg_try_advisory_lock(%s, %s)", md.REPORT_LOCK).fetchone()[0]
        conn.execute("SELECT pg_advisory_unlock(%s, %s)", md.REPORT_LOCK)


def test_unreachable_barrier_refuses(tmp_path):
    cfg = full_cfg(state_cfg(tmp_path, ["no-such-docker-binary-here"]))
    with pytest.raises(md.Refused, match="BLOCKED: open student reports could not be counted"):
        with md.report_hold_barrier(cfg, OLD):
            raise AssertionError("no switch without a barrier")


from test_question_reports import bank  # noqa: E402,F401  (fixture)
from test_bank_seeding import url  # noqa: E402,F401  (fixture)
from test_generation import catalog_conn  # noqa: E402,F401  (fixture)
