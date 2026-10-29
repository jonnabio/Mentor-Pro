"""Isolated migration rehearsal, maintenance window and gated migration (T045, ADR-033 increment I5).

Unit tests of the rules (evidence binding, time limits, storage, isolation and cleanup guards, data checks) need
neither Docker nor a server. The Docker tests build a real image from this repository, seed a synthetic legacy
database (pre-T036 writing schema, synthetic records only) in an isolated compose project mentorpro-i5test-<id>,
and run the whole window: maintenance, backup, rehearsal, migration and deployment, with failure injection. They
never name a production resource.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "deploy"))
sys.path.insert(0, str(REPO / "scripts" / "release"))
import mentorpro_deploy as md  # noqa: E402
import mentorpro_migrate as mm  # noqa: E402
import release  # noqa: E402
from test_deploy_rollout import (DOCKER_REQUIRED, DOCKERFILE, SERVER, SH, _docker_ready, _free_port,  # noqa: E402
                                 _posix, _production_named, sh)

SCRIPT = REPO / "deploy" / "mentorpro"
CODE = (REPO / "deploy" / "mentorpro_migrate.py").read_text(encoding="utf-8")
REPOSITORY = "ghcr.io/jonnabio/mentor-pro"
DIGEST = "sha256:" + "a" * 64
DUMP_SHA = "d" * 64
NOW = md.parse_stamp("2026-11-02T15:00:00Z")
PROJECT = "mentorpro-rehearsal-20261102t150000-42"


# ------------------------------------------------------------------ data checks

def test_fingerprint_query_is_the_backup_query():
    text = SCRIPT.read_text(encoding="utf-8")
    shell = text.split("FINGERPRINT_SQL=$(cat <<'SQL'\n", 1)[1].split("\nSQL\n)", 1)[0]
    assert mm.FINGERPRINT_SQL == shell + "\n"


def test_fingerprint_digest_matches_the_shell_digest():
    # deploy/mentorpro: before=$(psql ...) strips trailing newlines; digest() prints it with one newline.
    out = "writing.draft|2|abc\r\nwriting.exercise|3|def\n\n"
    assert mm.fingerprint_digest(out) == hashlib.sha256(b"writing.draft|2|abc\nwriting.exercise|3|def\n").hexdigest()


@pytest.mark.parametrize("sql", [mm.COUNTS_SQL, mm.ATTEMPTS_SQL])
def test_count_queries_are_read_only(sql):
    assert sql.startswith("SET default_transaction_read_only = on;")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)\b", sql, re.I)


BEFORE_FP = "curriculum.block|5|aa\npractice.answer|2|bb\nwriting.draft|2|cc\nwriting.evaluation|1|dd\n" \
            "writing.exercise|3|ee\nwriting.submission|2|ff\n"
AFTER_FP = "curriculum.block|5|aa\npractice.answer|2|bb\nwriting.draft|2|c2\nwriting.evaluation|1|dd\n" \
           "writing.exercise|3|ee\nwriting.schema_migration|1|gg\nwriting.student_attempt|3|hh\n" \
           "writing.submission|2|f2\n"


def test_scope_allows_only_the_migration():
    assert mm.scope_problems(BEFORE_FP, AFTER_FP) == []


@pytest.mark.parametrize("after, reason", [
    (AFTER_FP.replace("curriculum.block|5|aa", "curriculum.block|5|zz"), "curriculum.block changed"),
    (AFTER_FP.replace("writing.evaluation|1|dd", "writing.evaluation|0|dd"), "writing.evaluation changed"),
    (AFTER_FP.replace("practice.answer|2|bb\n", ""), "practice.answer disappeared"),
    (AFTER_FP + "writing.other|1|xx\n", "unexpected new table writing.other"),
])
def test_changes_outside_the_migration_are_found(after, reason):
    assert any(reason in p for p in mm.scope_problems(BEFORE_FP, after))


COUNTS = {"exercises_with_work": 3, "drafts": 2, "submissions": 2, "evaluations": 1, "criterion_scores": 2,
          "evaluations_of_submissions": 1, "scores_of_evaluations": 2}
ATTEMPTS = {"attempts": 3, "attempts_not_first": 0, "drafts_on_attempt_one": 2, "submissions_on_attempt_one": 2,
            "attempts_without_work": 0}


def test_migrated_data_accepted():
    assert mm.migration_problems(COUNTS, dict(COUNTS), dict(ATTEMPTS)) == []
    assert mm.report_problems({"status": "applied", "before": {"d": 1}, "after": {"d": 1}, "attempts_created": 3},
                              COUNTS) == []


@pytest.mark.parametrize("after, attempts, reason", [
    ({"evaluations": 0}, {}, "evaluations changed"),
    ({"evaluations_of_submissions": 0}, {}, "evaluations_of_submissions changed"),  # relationship lost
    ({"scores_of_evaluations": 1}, {}, "scores_of_evaluations changed"),
    ({}, {"attempts": 2}, "attempts is 2, expected 3"),  # backfill count
    ({}, {"attempts_not_first": 1}, "attempts_not_first"),
    ({}, {"drafts_on_attempt_one": 1}, "drafts_on_attempt_one"),
    ({}, {"attempts_without_work": 1}, "attempts_without_work"),
])
def test_migrated_data_problems(after, attempts, reason):
    problems = mm.migration_problems(COUNTS, {**COUNTS, **after}, {**ATTEMPTS, **attempts})
    assert any(reason in p for p in problems), problems


@pytest.mark.parametrize("report, reason", [
    ({"status": "already_applied"}, "not 'applied'"),
    ({"status": "applied", "before": {"d": 1}, "after": {"d": 2}, "attempts_created": 3}, "differ"),
    ({"status": "applied", "before": {}, "after": {}, "attempts_created": 4}, "4 attempts created"),
])
def test_migration_report_problems(report, reason):
    assert any(reason in p for p in mm.report_problems(report, COUNTS))


# ------------------------------------------------------------------ evidence binding and time limits

def rehearsal(**change):
    record = {"result": "REHEARSAL OK", "digest": DIGEST, "dump_sha256": DUMP_SHA, "cleanup": "verified",
              "schema_after": "current 0001", "finished_at": "2026-11-02T14:00:00Z"}
    record.update(change)
    return record


def test_rehearsal_evidence_accepted():
    mm.check_rehearsal(rehearsal(), DIGEST, DUMP_SHA, NOW)


@pytest.mark.parametrize("record, reason", [
    (None, "no rehearsal"),
    (rehearsal(result="REHEARSAL FAILED", step="apply"), "result was"),
    (rehearsal(digest="sha256:" + "b" * 64), "another release digest or another dump"),
    (rehearsal(dump_sha256="e" * 64), "another release digest or another dump"),
    (rehearsal(cleanup="remaining: 1 volumes"), "cleanup"),
    (rehearsal(schema_after="legacy none"), "not current"),
    (rehearsal(finished_at="2026-11-02T08:59:59Z"), "older than six hours"),
    (rehearsal(finished_at="2026-11-02T16:00:00Z"), "future"),
    (rehearsal(finished_at="soon"), "timestamp"),
])
def test_rehearsal_evidence_is_bound_and_fresh(record, reason):
    with pytest.raises(md.Refused, match=reason):
        mm.check_rehearsal(record, DIGEST, DUMP_SHA, NOW)


@pytest.mark.parametrize("state, ok", [("legacy none", True), ("current 0001", True), ("fresh none", False),
                                       ("drifted -", False), ("unreadable -", False), (None, False)])
def test_rehearsal_dump_states(state, ok):
    if ok:
        assert mm.dump_state({"schema_state": state})[:2] == tuple(state.split())
    else:
        with pytest.raises(md.Refused):
            mm.dump_state({"schema_state": state})


DURATIONS = {"restore": 50, "dry run": 30, "apply": 30, "verify": 10, "start app and tutor": 40, "smoke": 10}


@pytest.mark.parametrize("minutes, durations, reason", [
    (10, DURATIONS, None),
    (40, DURATIONS, None),  # at the checkpoint, not past it
    (40.1, DURATIONS, "40-minute checkpoint"),
    (30, {**DURATIONS, "apply": 900}, "projected downtime"),  # 30 + 2 x 15.3 min > 60
    (55, {"apply": 1}, "checkpoint"),
])
def test_downtime_window(minutes, durations, reason):
    problems = mm.window_problems(NOW - timedelta(minutes=minutes), NOW, durations)
    assert (problems == []) if reason is None else any(reason in p for p in problems), problems


def test_window_constants_are_the_po_decision():
    assert mm.DOWNTIME_LIMIT == timedelta(minutes=60) and mm.CHECKPOINT == timedelta(minutes=40)
    assert "restore" not in mm.REMAINING  # the restore is the rehearsal's, not part of the remaining window


# ------------------------------------------------------------------ storage

def probe(table):
    return lambda path: table[path.as_posix()]


def test_space_needs_add_up_per_filesystem():
    needs = [("dump copy", Path("/r"), 600), ("restored database", Path("/d"), 500), ("migration", Path("/d"), 500)]
    assert mm.space_problems(needs, probe({"/r": (1, 600), "/d": (2, 1000)})) == []
    problems = mm.space_problems(needs, probe({"/r": (1, 1500), "/d": (1, 1500)}))  # one filesystem: 1600 > 1500
    assert len(problems) == 1 and "needs 1600 bytes" in problems[0]
    problems = mm.space_problems(needs, probe({"/r": (1, 599), "/d": (2, 1000)}))
    assert len(problems) == 1 and "dump copy 600" in problems[0]


def test_missing_filesystem_fails_closed(tmp_path):
    with pytest.raises(md.Refused, match="does not exist"):
        mm.free_space(tmp_path / "missing")
    assert mm.free_space(tmp_path)[1] > 0


def test_space_reserve_can_only_add(monkeypatch):
    monkeypatch.setenv("MENTORPRO_REHEARSAL_RESERVE_BYTES", "-99999999999")
    assert mm.settings()["reserve"] == 0
    assert mm.restore_estimate(10) == mm.CLUSTER_BYTES + 100


@pytest.mark.skipif(os.name != "posix", reason="ownership and modes are POSIX")
def test_rehearsal_directory_must_be_private(tmp_path):
    base = tmp_path / "rehearsal"
    mm.private_dir(base)
    assert oct(base.stat().st_mode & 0o777) == "0o700"
    base.chmod(0o750)
    with pytest.raises(md.Refused, match="0700"):
        mm.private_dir(base)


# ------------------------------------------------------------------ isolation guards

def config(**change):
    workdir = Path("/var/lib/mentor-pro/rehearsal") / PROJECT
    image = f"{REPOSITORY}@{DIGEST}"
    services = {
        "postgres": {"image": "postgres:17.6", "networks": {"rehearsal": None}, "env_file": [str(workdir / "pg.env")],
                     "volumes": [{"type": "volume", "source": "pgdata", "target": "/var/lib/postgresql/data"}]},
        "app": {"image": image, "networks": {"rehearsal": None},
                "env_file": [{"path": str(workdir / "app.env"), "required": True}]},
        "tutor": {"image": image, "networks": {"rehearsal": None}, "env_file": [str(workdir / "app.env")]},
    }
    data = {"name": PROJECT, "services": services,
            "networks": {"rehearsal": {"name": f"{PROJECT}_rehearsal", "internal": True}},
            "volumes": {"pgdata": {"name": f"{PROJECT}_pgdata"}}}
    for path, value in change.items():
        *keys, last = path.split("__")
        target = data
        for key in keys:
            target = target[key]
        target[last] = value
    return mm.check_config(data, PROJECT, workdir, image)


def test_rehearsal_configuration_accepted():
    assert config() == []


@pytest.mark.parametrize("change, reason", [
    ({"services__app__ports": [{"published": "8080", "target": 8000}]}, "app sets ports"),
    ({"services__tutor__network_mode": "host"}, "tutor sets network_mode"),
    ({"networks__rehearsal": {"name": "mentor-pro_default", "external": True}}, "not this project's own"),
    ({"networks__rehearsal": {"name": f"{PROJECT}_rehearsal"}}, "not internal"),
    ({"volumes__pgdata": {"name": "mentor-pro_postgres_data", "external": True}}, "not this project's own"),
    ({"services__postgres__volumes": [{"type": "bind", "source": "/var/backups", "target": "/b"}]},
     "not a rehearsal volume"),
    ({"services__app__env_file": ["/etc/mentor-pro/app.env"]}, "outside the rehearsal directory"),
    ({"services__app__networks": {"rehearsal": None, "mentor-pro_default": None}}, "joins networks"),
    ({"services__app__image": f"{REPOSITORY}:testing"}, "not the release digest"),
    ({"services__app__container_name": "mentor-pro-app-1"}, "container_name"),
    ({"services__extra": {"image": "x"}}, "services"),
    ({"name": "mentor-pro"}, "project name"),
])
def test_rehearsal_configuration_refusals(change, reason):
    problems = config(**change)
    assert any(reason in p for p in problems), problems


def container(name, networks=(f"{PROJECT}_rehearsal",), ports=None, mounts=()):
    return {"Name": "/" + name, "NetworkSettings": {"Networks": {n: {} for n in networks},
                                                    "Ports": {"8000/tcp": ports}},
            "HostConfig": {"PortBindings": {"8000/tcp": ports} if ports else {}}, "Mounts": list(mounts)}


def test_running_rehearsal_accepted():
    infos = [container(f"{PROJECT}-postgres-1", mounts=[{"Type": "volume", "Name": f"{PROJECT}_pgdata"}]),
             container(f"{PROJECT}-app-1"), container(f"{PROJECT}-tutor-1")]
    assert mm.check_containers(infos, PROJECT, f"{PROJECT}_rehearsal") == []


@pytest.mark.parametrize("info, reason", [
    (container("mentor-pro-app-1"), "not named"),
    (container(f"{PROJECT}-app-1", networks=(f"{PROJECT}_rehearsal", "mentor-pro_default")), "joins networks"),
    (container(f"{PROJECT}-app-1", ports=[{"HostIp": "127.0.0.1", "HostPort": "8080"}]), "publishes a port"),
    (container(f"{PROJECT}-postgres-1", mounts=[{"Type": "volume", "Name": "mentor-pro_postgres_data"}]), "mounts"),
    (container(f"{PROJECT}-app-1", mounts=[{"Type": "bind", "Source": "/etc/mentor-pro"}]), "mounts bind"),
])
def test_running_rehearsal_refusals(info, reason):
    problems = mm.check_containers([info], PROJECT, f"{PROJECT}_rehearsal")
    assert any(reason in p for p in problems), problems


@pytest.mark.parametrize("name", ["mentor-pro", "mentor-pro-postgres-1", "mentorpro-rehearsal-", "mentorpro-verify-1",
                                  "mentorpro-i4test-abc", "mentorpro-rehearsal-x y", "MENTORPRO-REHEARSAL-1"])
def test_cleanup_and_commands_refuse_non_rehearsal_projects(tmp_path, name):
    cfg = {"docker": ["no-docker-here"], "rehearsal": tmp_path}
    with pytest.raises(md.Refused, match="not a rehearsal project"):
        mm.cleanup(cfg, name, tmp_path / "x")
    with pytest.raises(md.Refused):
        mm.Rehearsal(cfg, name, tmp_path / "x")


def test_cleanup_removes_only_a_marked_rehearsal_directory(tmp_path):
    base = tmp_path / "rehearsal"
    unmarked = base / PROJECT
    unmarked.mkdir(parents=True)
    with pytest.raises(md.Refused, match="marker"):
        mm.remove_workdir(base, unmarked)
    with pytest.raises(md.Refused, match="not a rehearsal directory"):
        mm.remove_workdir(base, tmp_path / "backups")
    with pytest.raises(md.Refused, match="not a rehearsal directory"):
        mm.remove_workdir(base, base / PROJECT / "nested")
    (unmarked / mm.MARKER).write_text("x", encoding="utf-8")
    (unmarked / "backup.dump").write_bytes(b"copy")
    mm.remove_workdir(base, unmarked)
    assert not unmarked.exists() and base.exists()


def test_dump_copy_is_private_and_checked(tmp_path):
    source = tmp_path / "a.dump"
    source.write_bytes(b"x" * 3_000_000)
    target = tmp_path / "copy.dump"
    assert mm.copy_private(source, target) == hashlib.sha256(source.read_bytes()).hexdigest()
    if os.name == "posix":
        assert oct(target.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        mm.copy_private(source, target)  # never overwrites


def test_the_rehearsal_never_touches_production():
    code = re.sub(r'"""[\s\S]*?"""', "", CODE)
    code = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ('"down"', "--volumes", '"restart"', '"repair"', '"rollback"', "/etc/mentor-pro",
                      ":testing", "latest", "--service-ports", '"-p", "', "--publish"):
        assert forbidden not in code, forbidden
    # pg_restore only into the rehearsal's own PostgreSQL; production is only read (psql) and migrated (apply).
    assert code.count('"pg_restore"') == 1 and 'self.postgres, "pg_restore"' in code
    assert "docker compose down -v" not in (REPO / "deploy" / "compose.rehearsal.yml").read_text(encoding="utf-8")


def test_rehearsal_compose_has_no_ports_and_an_internal_network():
    text = (REPO / "deploy" / "compose.rehearsal.yml").read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "ports:" not in body and "internal: true" in body and "/etc/mentor-pro" not in body
    assert "external" not in body and "container_name" not in body


# ------------------------------------------------------------------ command line, lock and window state

def cli(tmp_path, *args):
    env = {**os.environ, "MENTORPRO_STATE": str(tmp_path / "state"), "MENTORPRO_RELEASES": str(tmp_path / "R"),
           "MENTORPRO_RELEASE_ENV": str(tmp_path / "release.env"), "MENTORPRO_DOCKER": "no-docker-here",
           "MENTORPRO_REHEARSAL_DIR": str(tmp_path / "rehearsal")}
    return subprocess.run([sys.executable, str(REPO / "deploy" / "mentorpro_migrate.py"), *args], env=env,
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("args", [
    ["rehearse", "m.json", "d.dump", "--window", "W-1"],
    ["migrate", "m.json", "--backup", "d", "--authorization", "PO-1"],
    ["migrate", "m.json", "--window", "W-1", "--authorization", "PO-1"],
    ["maintenance", "start", "--window", "W-1"],
    ["maintenance", "end", "--authorization", "PO-1"],
])
def test_missing_references_refuse_before_anything(tmp_path, args):
    out = cli(tmp_path, *args)
    assert out.returncode == 1 and "REFUSED" in out.stdout, out.stdout + out.stderr
    assert not (tmp_path / "R").exists() and not (tmp_path / "rehearsal").exists()
    assert not (tmp_path / "state" / "maintenance.json").exists()


def test_migrate_needs_an_open_window(tmp_path):
    out = cli(tmp_path, "migrate", "m.json", "--backup", "d", "--window", "W-1", "--authorization", "PO-1")
    assert out.returncode == 1 and "no maintenance window is open" in out.stdout


def test_window_with_a_started_migration_needs_a_recovery_decision(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "maintenance.json").write_text(json.dumps({"started_at": "2026-11-02T14:00:00Z", "window": "W-1",
                                                        "state": "legacy", "schema": "none", "image": "x"}))
    (state / "migration.json").write_text("{}")
    for args in (["maintenance", "end"], ["migrate", "m.json", "--backup", "d"]):
        out = cli(tmp_path, *args, "--window", "W-1", "--authorization", "PO-1")
        assert out.returncode == 1 and "DATABASE RECOVERY DECISION REQUIRED" in out.stdout, out.stdout
    out = cli(tmp_path, "migrate", "m.json", "--backup", "d", "--window", "W-2", "--authorization", "PO-1")
    assert "not the open maintenance window" in out.stdout


def test_deploy_lock_is_reentrant_in_one_process_only(tmp_path):
    cfg = {"state": tmp_path / "state"}
    with md.deploy_lock(cfg):
        with md.deploy_lock(cfg):  # migrate -> deploy_locked: no self-deadlock
            pass
        holder = subprocess.run([sys.executable, "-c", (
            "import sys; sys.path.insert(0, sys.argv[1]); import mentorpro_deploy as md\n"
            "from pathlib import Path\n"
            "try:\n    with md.deploy_lock({'state': Path(sys.argv[2])}): print('acquired')\n"
            "except md.Refused: print('refused')"), str(REPO / "deploy"), str(cfg["state"])],
            capture_output=True, text=True, timeout=60)
        assert holder.stdout.strip() == "refused"  # still held by the outer lock
    assert md._LOCK_DEPTH[0] == 0


def test_after_apply_failure_stops_services_and_never_restores(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(mm, "stop_services", lambda cfg: calls.append("stop") or "")
    monkeypatch.setattr(md, "read_live", lambda cfg: ("current", "0001", "migrations 0001_student_attempts"))
    cfg = {"releases": tmp_path / "RELEASES"}
    refs = {"window": "W-1", "authorization": "PO-1", "authorization_verified": "no"}
    code = mm.after_apply_failure(cfg, None, refs, mm.Failed("deploy", "tutor not healthy"), Path("x.dump"))
    out = capsys.readouterr().out
    assert code == 1 and calls == ["stop"]
    assert "MIGRATE FAILED at deploy" in out and "DATABASE RECOVERY DECISION REQUIRED" in out
    assert "stay stopped" in out and "No automatic database restore" in out
    (line,) = md.releases(cfg)
    assert line["result"] == "FAILED" and line["step"] == "deploy" and line["schema"] == "current:0001"


def test_wrapper_dispatches_the_i5_commands():
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'rehearse|maintenance|migrate) exec "$PYTHON" "$(dirname "$0")/mentorpro_migrate.py" "$@"' in text


# ------------------------------------------------------------------ Docker: synthetic window, real image

SEED = r'''import json, os
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
from curriculum import importer
from app.generation.store import SCHEMA_SQL as GENERATION
from app.llm.usage import SCHEMA_SQL as LLM
from app.practice.store import SCHEMA_SQL as PRACTICE
from app.writing.store import SCHEMA_SQL as WRITING, WritingStore
url = os.environ["DATABASE_URL"]
importer.import_workbook(Path("/seed/wb.xlsx"), url, "PNE2026-SUM-v1.0", Path("/seed/MANIFEST.sha256"), "curriculum")
with psycopg.connect(url, autocommit=True) as conn:
    for ddl in (PRACTICE, GENERATION, LLM, WRITING):
        conn.execute(ddl)
    conn.execute("CREATE UNIQUE INDEX uq_submission_exercise ON writing.submission (exercise_id)")  # pre-T036
store = WritingStore.__new__(WritingStore)  # the pre-T036 way: no startup check
store.url = url
records = json.loads(Path("/seed/exercises.json").read_text(encoding="utf-8"))
for record in records:
    store.add_exercise(record)
l1, l2, l3 = (r["exercise_id"] for r in records)
with psycopg.connect(url) as conn:
    conn.execute("INSERT INTO writing.draft (exercise_id, text_es, word_count, updated_at) "
                 "VALUES (%s, 'Mi borrador sintetico.', 3, '2026-10-01T08:00:00Z')", (l2,))
    conn.execute("INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count, "
                 "paragraph_count, submitted_at, client_request_id) VALUES ('SUB-SYN-3', %s, 'typed', "
                 "'Parrafo sintetico.', 2, 1, '2026-10-02T09:00:00Z', 'req-syn-3')", (l3,))
    conn.execute("INSERT INTO writing.submission (submission_id, exercise_id, evidence_mode, text_es, word_count, "
                 "paragraph_count, submitted_at, client_request_id, exercise_revision) VALUES ('SUB-SYN-1', %s, "
                 "'typed', 'Texto sintetico corregido.', 3, 1, '2026-10-03T10:00:00Z', 'req-syn-1', 1)", (l1,))
    conn.execute("INSERT INTO writing.draft (exercise_id, text_es, word_count, client_seq, exercise_revision, "
                 "updated_at) VALUES (%s, 'Texto sintetico corregido.', 3, 7, 1, '2026-10-03T10:00:00Z')", (l1,))
    feedback = {"strengths": ["Bien."], "improvements": ["Tildes."]}
    conn.execute("INSERT INTO writing.evaluation (evaluation_id, submission_id, status, evaluator_role, rubric_id, "
                 "rubric_sha256, evaluated_at, feedback, record, exercise_revision) VALUES ('EVAL-SYN-1', 'SUB-SYN-1', "
                 "'completed', 'parent', 'MEP-PE-2026', 'abc123', '2026-10-20T10:00:00Z', %s, %s, 1)",
                 (Jsonb(feedback), Jsonb({"evaluation_id": "EVAL-SYN-1", "feedback_es": feedback})))
    for code, points in (("EE07", 3), ("EE08", 2)):
        conn.execute("INSERT INTO writing.criterion_score (evaluation_id, criterion_code, status, points, "
                     "descriptor_ref) VALUES ('EVAL-SYN-1', %s, 'scored', %s, %s)",
                     (code, points, f"MEP-PE-2026#{code}@{points}"))
print("SEEDED")
'''
EXPECTED_COUNTS = {"exercises_with_work": 3, "drafts": 2, "submissions": 2, "evaluations": 1, "criterion_scores": 2,
                   "evaluations_of_submissions": 1, "scores_of_evaluations": 2}
CREATED = "2026-11-02T15:04:05Z"
VERSION = "v2026.11.02-1"
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    """A local registry with the pre-T036 stand-in (no labels) and a real image of this repository."""
    if not _docker_ready():
        if DOCKER_REQUIRED:
            pytest.fail("Docker is required here (MENTORPRO_REQUIRE_DOCKER=1) but not available")
        pytest.skip("Docker is not available")
    ident = uuid.uuid4().hex[:8]
    registry = f"mentorpro-i5test-{ident}-registry"
    port = _free_port()
    repo = f"127.0.0.1:{port}/mentor-pro"
    build = tmp_path_factory.mktemp("legacy-image")
    (build / "app").mkdir()
    (build / "server.py").write_text(SERVER, encoding="utf-8")
    (build / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (build / "app" / "__init__.py").write_text("", encoding="utf-8")
    (build / "app" / "tutor_main.py").write_text(
        'import runpy, sys\nsys.argv = ["server.py", "tutor"]\nrunpy.run_path("/srv/server.py", run_name="__main__")\n',
        encoding="utf-8")

    def push(tag):
        out = sh("docker", "push", tag)
        assert out.returncode == 0, out.stderr
        return re.search(r"digest: (sha256:[0-9a-f]{64})", out.stdout).group(1)

    try:
        assert sh("docker", "run", "-d", "--name", registry, "-p", f"127.0.0.1:{port}:5000",
                  "registry:2").returncode == 0
        for _ in range(30):
            if sh("docker", "exec", registry, "wget", "-qO-", "http://127.0.0.1:5000/v2/").returncode == 0:
                break
            time.sleep(1)
        out = sh("docker", "build", "-q", "-t", f"{repo}:legacy", str(build))
        assert out.returncode == 0, out.stderr
        legacy = push(f"{repo}:legacy")
        labels = sum((["--label", f"{k}={v}"] for k, v in release.labels(VERSION, SHA, CREATED).items()), [])
        out = sh("docker", "build", "-q", *labels, "-t", f"{repo}:{VERSION}", str(REPO))
        assert out.returncode == 0, out.stderr
        real = push(f"{repo}:{VERSION}")
        yield {"repo": repo, "legacy": legacy, "real": real}
    finally:
        sh("docker", "rm", "-f", "-v", registry)


class Production:
    """A synthetic stand-in for production: compose project mentorpro-i5test-<id> from deploy/compose.yml, a legacy
    writing schema with synthetic records, and the label-less pre-T036 stand-in running app and tutor."""

    def __init__(self, tmp_path, stack, tutor_token=None):
        self.tmp, self.stack = tmp_path, stack
        self.project = f"mentorpro-i5test-{uuid.uuid4().hex[:8]}"
        assert not self.project.startswith(("mentor-pro", mm.PREFIX))
        repo = stack["repo"]
        self.legacy_ref, self.real_ref = f"{repo}@{stack['legacy']}", f"{repo}@{stack['real']}"
        app_port, tutor_port = _free_port(), _free_port()
        compose = (REPO / "deploy" / "compose.yml").read_text(encoding="utf-8")
        for name in ("app.env", "tutor.env", "postgres.env"):
            compose = compose.replace(f"/etc/mentor-pro/{name}", _posix(tmp_path / name))
        compose = re.sub(r'\n\s+- "192\.168\.50\.229:8080:8000".*', "", compose)
        compose = compose.replace('"127.0.0.1:8080:8000"', f'"127.0.0.1:{app_port}:8000"')
        compose = compose.replace('"127.0.0.1:8081:8000"', f'"127.0.0.1:{tutor_port}:8000"')
        compose = compose.replace("interval: 30s", "interval: 2s").replace("start_period: 30s", "start_period: 1s")
        (tmp_path / "compose.yml").write_text(compose, encoding="utf-8")
        (tmp_path / "postgres.env").write_text("POSTGRES_HOST_AUTH_METHOD=trust\nPOSTGRES_USER=mentor_pro_admin\n"
                                               "POSTGRES_DB=mentor_pro\n", encoding="utf-8")
        self.database_url = "postgresql://mentor_pro_admin@postgres:5432/mentor_pro"
        (tmp_path / "app.env").write_text(f"DATABASE_URL={self.database_url}\n", encoding="utf-8")
        (tmp_path / "tutor.env").write_text("", encoding="utf-8")
        self.release_env = tmp_path / "release.env"
        self.release_env.write_text(f"MENTOR_PRO_IMAGE={self.legacy_ref}\n", encoding="utf-8")
        self.state = tmp_path / "state"
        self.rehearsal = tmp_path / "rehearsal"
        self.env = {**os.environ, "MENTORPRO_REPOSITORY": repo, "MENTORPRO_RELEASE_ENV": _posix(self.release_env),
                    "MENTORPRO_RELEASES": _posix(tmp_path / "RELEASES"), "MENTORPRO_STATE": _posix(self.state),
                    "MENTORPRO_COMPOSE": _posix(tmp_path / "compose.yml"), "MENTORPRO_PROJECT": self.project,
                    "MENTORPRO_POSTGRES_CONTAINER": f"{self.project}-postgres-1",
                    "MENTORPRO_BACKUPS": _posix(tmp_path / "backups"),
                    "MENTORPRO_BACKUP_SCHEMAS": "curriculum practice generation llm writing",
                    "MENTORPRO_PYTHON": sys.executable, "MENTORPRO_REHEARSAL_DIR": _posix(self.rehearsal),
                    "MENTORPRO_APP_URL": f"http://127.0.0.1:{app_port}",
                    "MENTORPRO_TUTOR_URL": f"http://127.0.0.1:{tutor_port}", "MENTORPRO_WIFI_ADDR": "",
                    "MENTORPRO_HEALTH_TIMEOUT": "90"}
        self.compose("up", "-d", "--wait", "postgres")
        gateway = sh("docker", "network", "inspect", f"{self.project}_default", "--format",
                     "{{range .IPAM.Config}}{{.Gateway}}{{end}}").stdout.strip()
        token = tutor_token if tutor_token is not None else "i5-synthetic-token-" + uuid.uuid4().hex
        (tmp_path / "tutor.env").write_text(f"MENTOR_PRO_TUTOR_TOKEN={token}\n"
                                            f"MENTOR_PRO_TUTOR_ALLOWED_HOSTS={gateway}\n", encoding="utf-8")
        self.seed()
        self.compose("up", "-d", "--wait")
        self.postgres_id = self.inspect("postgres")[0]

    def compose(self, *args):
        out = sh("docker", "compose", "-p", self.project, "-f", str(self.tmp / "compose.yml"), "--env-file",
                 str(self.release_env), *args)
        assert out.returncode == 0, out.stderr
        return out.stdout

    def seed(self):
        from test_writing_tutor import L1, L23  # synthetic exercise records (scripts/dev/fixtures)
        from workbook_fixtures import catalog_rows, evidence_rows, register, write_workbook
        seed = self.tmp / "seed"
        seed.mkdir()
        write_workbook(seed / "wb.xlsx", catalog_rows(), evidence_rows())
        register(seed / "MANIFEST.sha256", seed / "wb.xlsx")
        others = [r for k, r in L23.items() if k != "introduction_paragraph"]
        records = [L1, L23["introduction_paragraph"], others[0]]
        (seed / "exercises.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        (seed / "seed.py").write_text(SEED, encoding="utf-8")
        seed.chmod(0o755)
        for path in seed.iterdir():
            path.chmod(0o644)
        out = sh("docker", "run", "--rm", "--network", f"{self.project}_default", "-v", f"{_posix(seed)}:/seed:ro",
                 "-e", f"DATABASE_URL={self.database_url}", "-e", "PYTHONPATH=/app", self.real_ref, "python", "/seed/seed.py")
        assert out.returncode == 0 and "SEEDED" in out.stdout, out.stdout + out.stderr

    def run(self, *args, **extra):
        out = subprocess.run([SH, str(SCRIPT), *args], env={**self.env, **extra}, capture_output=True, text=True,
                             timeout=1800)
        return out.returncode, out.stdout + out.stderr

    def psql(self, sql):
        out = sh("docker", "exec", "-i", f"{self.project}-postgres-1", "psql", "-U", "mentor_pro_admin", "-d",
                 "mentor_pro", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", input=sql)
        assert out.returncode == 0, out.stderr
        return out.stdout

    def schema(self):
        return md.classify(self.psql(md.SCHEMA_SQL))[:2]

    def counts(self, sql=mm.COUNTS_SQL):
        return json.loads(self.psql(sql).strip())

    def inspect(self, service):
        return sh("docker", "inspect", f"{self.project}-{service}-1", "--format",
                  "{{.Id}} {{.Config.Image}} {{.State.Running}}").stdout.split()

    def manifest(self, name="m.json", **change):
        data = release.manifest(VERSION, SHA, "7", CREATED, digest=self.stack["real"])
        data["image"]["repository"] = self.stack["repo"]
        data.update(change)
        path = self.tmp / name
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return str(path)

    def results(self):
        return [(line["action"], line["result"]) for line in md.releases({"releases": self.tmp / "RELEASES"})]

    def remove(self):
        for ls, rm in ((("ps", "-aq"), ("rm", "-f", "-v")), (("volume", "ls", "-q"), ("volume", "rm")),
                       (("network", "ls", "-q"), ("network", "rm"))):
            ids = sh("docker", *ls, "--filter", f"label=com.docker.compose.project={self.project}").stdout.split()
            if ids:
                sh("docker", *rm, *ids)
        left = []
        for kind in (["ps", "-a"], ["volume", "ls"], ["network", "ls"]):
            left += sh("docker", *kind, "-q", "--filter", f"name={self.project}").stdout.split()
        return left


def rehearsal_resources():
    out = []
    for kind in (["ps", "-a"], ["volume", "ls"], ["network", "ls"]):
        out += sh("docker", *kind, "-q", "--filter", f"name={mm.PREFIX}").stdout.split()
    return out


REFS = ["--window", "W-2026-11-02-i5", "--authorization", "PO-T045-test"]


def test_docker_rehearsal_and_migration_window(stack, tmp_path):
    production_before = _production_named()
    assert rehearsal_resources() == []
    prod = None
    try:
        prod = Production(tmp_path, stack)
        assert prod.schema() == ("legacy", "none") and prod.counts() == EXPECTED_COUNTS
        manifest = prod.manifest()
        code, out = prod.run("adopt-legacy", *REFS)
        assert code == 0 and "ADOPTED" in out, out

        # Outside a window, and a refusal inside one followed by a controlled exit on the unchanged schema.
        code, out = prod.run("migrate", manifest, "--backup", str(tmp_path / "none.dump"), *REFS)
        assert code == 1 and "no maintenance window is open" in out, out
        code, out = prod.run("maintenance", "start", *REFS)
        assert code == 0 and "MAINTENANCE STARTED" in out and "40-minute checkpoint" in out, out
        assert prod.inspect("app")[2] == prod.inspect("tutor")[2] == "false"
        assert prod.inspect("postgres")[0] == prod.postgres_id and prod.inspect("postgres")[2] == "true"
        code, out = prod.run("migrate", manifest, "--backup", str(tmp_path / "none.dump"), *REFS)
        assert code == 1 and "backup record" in out and prod.schema() == ("legacy", "none"), out
        code, out = prod.run("maintenance", "end", *REFS)
        assert code == 0 and "MAINTENANCE ENDED" in out and "schema unchanged" in out, out
        assert prod.inspect("app")[1:] == [prod.legacy_ref, "true"]

        # The real window: stop, back up with the services stopped.
        code, out = prod.run("maintenance", "start", *REFS)
        assert code == 0, out
        code, out = prod.run("backup")
        assert code == 0 and "BACKUP OK" in out, out
        dump = Path(re.search(r"BACKUP OK (\S+)", out).group(1))
        dump_sha = hashlib.sha256(dump.read_bytes()).hexdigest()
        assert "schema_state legacy none" in Path(str(dump) + ".verify").read_text(encoding="utf-8")
        code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
        assert code == 1 and "no rehearsal of this release on this dump" in out, out

        # Rehearsal guards, each before anything starts.
        bad = tmp_path / "compose.bad.yml"
        bad.write_text((REPO / "deploy" / "compose.rehearsal.yml").read_text(encoding="utf-8").replace(
            "    internal: true", f"    external: true\n    name: {prod.project}_default"), encoding="utf-8")
        code, out = prod.run("rehearse", manifest, str(dump), *REFS, MENTORPRO_REHEARSAL_COMPOSE=_posix(bad))
        assert code == 1 and "REHEARSAL FAILED at isolation check" in out and "not this project's own" in out, out
        assert "cleanup verified" in out and rehearsal_resources() == []
        code, out = prod.run("rehearse", manifest, str(dump), *REFS, MENTORPRO_REHEARSAL_RESERVE_BYTES=str(10**18))
        assert code == 1 and "REHEARSE REFUSED: insufficient space" in out, out
        tampered = tmp_path / "tampered.dump"
        tampered.write_bytes(dump.read_bytes() + b"x")
        shutil.copy(str(dump) + ".verify", str(tampered) + ".verify")
        code, out = prod.run("rehearse", manifest, str(tampered), *REFS)
        assert code == 1 and "checksum differs" in out, out
        code, out = prod.run("rehearse", prod.manifest("other.json", commit="f" * 40), str(dump), *REFS)
        assert code == 1 and "labels differ" in out, out
        assert rehearsal_resources() == [] and list(prod.rehearsal.iterdir()) == []

        # REHEARSAL OK: isolated, migrated, checked, smoke-tested inside, removed.
        code, out = prod.run("rehearse", manifest, str(dump), *REFS)
        assert code == 0 and "REHEARSAL OK" in out, out
        assert "isolation verified" in out and "SMOKE PASS (9/9)" in out and "cleanup verified" in out, out
        assert "PASS production database not reachable" in out and "PASS no route out of the rehearsal network" in out
        assert rehearsal_resources() == [] and list(prod.rehearsal.iterdir()) == []
        assert dump.exists() and hashlib.sha256(dump.read_bytes()).hexdigest() == dump_sha  # backup kept
        assert prod.schema() == ("legacy", "none") and prod.inspect("postgres")[0] == prod.postgres_id
        record_path = mm.rehearsal_path({"state": prod.state}, stack["real"], dump_sha)
        record = json.loads(record_path.read_text(encoding="utf-8"))
        assert record["counts_before"] == record["counts_after"] == EXPECTED_COUNTS
        assert record["attempts"]["attempts"] == 3 and record["attempts_created"] == 3
        for key in ("restore", "dry run", "apply", "verify", "start app and tutor", "smoke", "cleanup", "total"):
            assert key in record["durations"], record["durations"]
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                summary.write(f"T045 synthetic rehearsal durations (s): {json.dumps(record['durations'])}\n")

        # Binding: another dump, stale evidence, the checkpoint, the projection, changed data, writers, references.
        code, out = prod.run("backup")
        other = re.search(r"BACKUP OK (\S+)", out).group(1)
        code, out = prod.run("migrate", manifest, "--backup", other, *REFS)
        assert code == 1 and "no rehearsal of this release on this dump" in out, out
        good = record_path.read_text(encoding="utf-8")
        for key, value, reason in (("finished_at", md.stamp(md.utc_now() - timedelta(hours=7)), "older than six hours"),
                                   ("durations", {**record["durations"], "apply": 1800}, "projected downtime")):
            record_path.write_text(json.dumps({**record, key: value}), encoding="utf-8")
            code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
            assert code == 1 and reason in out, out
        record_path.write_text(good, encoding="utf-8")
        window_path = prod.state / "maintenance.json"
        window = window_path.read_text(encoding="utf-8")
        window_path.write_text(json.dumps({**json.loads(window), "started_at": md.stamp(
            md.utc_now() - timedelta(minutes=41))}), encoding="utf-8")
        code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
        assert code == 1 and "40-minute checkpoint passed" in out, out
        window_path.write_text(window, encoding="utf-8")
        prod.psql("UPDATE writing.exercise SET created_at = created_at + interval '1 second';")
        code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
        assert code == 1 and "live data changed since the backup" in out, out
        prod.psql("UPDATE writing.exercise SET created_at = created_at - interval '1 second';")
        sh("docker", "start", f"{prod.project}-tutor-1")
        code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
        assert code == 1 and "application writers active: tutor is running" in out, out
        sh("docker", "stop", f"{prod.project}-tutor-1")
        code, out = prod.run("migrate", manifest, "--backup", str(dump), "--window", "W-other",
                             "--authorization", "PO-T045-test")
        assert code == 1 and "not the open maintenance window" in out, out
        code, out = prod.run("migrate", manifest, "--backup", str(dump), "--window", "W-2026-11-02-i5")
        assert code == 1 and "--authorization reference is required" in out, out
        assert prod.schema() == ("legacy", "none")

        # Gate G2: explicit migration, verification, deployment.
        code, out = prod.run("migrate", manifest, "--backup", str(dump), *REFS)
        assert code == 0 and "MIGRATE OK" in out and "DEPLOY OK" in out, out
        assert prod.schema() == ("current", "0001")
        assert prod.counts() == EXPECTED_COUNTS
        attempts = prod.counts(mm.ATTEMPTS_SQL)
        assert attempts == {"attempts": 3, "attempts_not_first": 0, "drafts_on_attempt_one": 2,
                            "submissions_on_attempt_one": 2, "attempts_without_work": 0}
        assert prod.inspect("app")[1:] == prod.inspect("tutor")[1:] == [prod.real_ref, "true"]
        assert prod.inspect("postgres")[0] == prod.postgres_id
        assert not (prod.state / "maintenance.json").exists() and not (prod.state / "migration.json").exists()

        # A pre-T036 image never runs on the migrated database.
        code, out = prod.run("rollback", "--backup", str(dump), *REFS)
        assert code == 1 and "ROLLBACK REFUSED: incompatible" in out, out
        code, out = prod.run("maintenance", "end", *REFS)
        assert code == 1 and "no maintenance window is open" in out, out
        assert prod.inspect("app")[1:] == [prod.real_ref, "true"]

        results = prod.results()
        assert results[-3:] == [("deploy", "OK"), ("migrate", "OK"), ("rollback", "REFUSED")], results
        assert ("rehearse", "OK") in results and ("rehearse", "FAILED") in results
        assert results.count(("maintenance-start", "OK")) == 2 and ("maintenance-end", "OK") in results
        lines = (tmp_path / "RELEASES").read_text(encoding="utf-8").splitlines()
        assert all("authorization_verified=no" in line for line in lines)
        assert not re.search(r"sintetico|DATABASE_URL|TUTOR_TOKEN", "\n".join(lines) + out)
        assert len(list((tmp_path / "backups").glob("*.dump"))) == 2  # never deleted
    finally:
        left = prod.remove() if prod else []
    assert left == [] and rehearsal_resources() == []
    assert _production_named() == production_before


def test_docker_migration_failures_never_restore_or_roll_back(stack, tmp_path):
    production_before = _production_named()
    prod = None
    try:
        # Injected: the production tutor token is too short, so the tutor service cannot start after the migration.
        prod = Production(tmp_path, stack, tutor_token="short")
        manifest = prod.manifest()
        assert prod.run("maintenance", "start", *REFS)[0] == 0
        code, out = prod.run("backup")
        assert code == 0, out
        dump = re.search(r"BACKUP OK (\S+)", out).group(1)
        code, out = prod.run("rehearse", manifest, dump, *REFS)  # generated rehearsal env: unaffected
        assert code == 0 and "REHEARSAL OK" in out, out

        # Failure before apply (injected: the migration cannot reach the database): old schema kept.
        good = (tmp_path / "app.env").read_text(encoding="utf-8")
        (tmp_path / "app.env").write_text(good.replace("@postgres:", "@nowhere:"), encoding="utf-8")
        code, out = prod.run("migrate", manifest, "--backup", dump, *REFS)
        assert code == 1 and "MIGRATE REFUSED before apply at dry run" in out and "old schema unchanged" in out, out
        assert prod.schema() == ("legacy", "none") and not (prod.state / "migration.json").exists()
        (tmp_path / "app.env").write_text(good, encoding="utf-8")

        # Failure after apply: services stopped and kept stopped; no restore, no rollback.
        code, out = prod.run("migrate", manifest, "--backup", dump, *REFS)
        assert code == 1 and "MIGRATE FAILED at deploy" in out and "DATABASE RECOVERY DECISION REQUIRED" in out, out
        assert "PROPOSED MANUAL ROLLBACK" not in out
        assert prod.schema() == ("current", "0001") and prod.counts() == EXPECTED_COUNTS
        assert prod.inspect("app")[2] == prod.inspect("tutor")[2] == "false"
        assert prod.inspect("postgres")[0] == prod.postgres_id
        assert (prod.state / "migration.json").exists() and (prod.state / "maintenance.json").exists()
        for args in (["maintenance", "end", *REFS], ["migrate", manifest, "--backup", dump, *REFS]):
            code, out = prod.run(*args)
            assert code == 1 and "DATABASE RECOVERY DECISION REQUIRED" in out, out
        code, out = prod.run("rollback", "--backup", dump, *REFS)
        assert code == 1 and "REFUSED" in out, out
        assert prod.inspect("app")[2] == "false" and prod.schema() == ("current", "0001")
        assert len(list((tmp_path / "backups").glob("*.dump"))) == 1  # no restore attempted, nothing deleted
        results = prod.results()
        assert results[-3:] == [("migrate", "REFUSED"), ("deploy", "FAILED"), ("migrate", "FAILED")], results
    finally:
        left = prod.remove() if prod else []
    assert left == [] and rehearsal_resources() == []
    assert _production_named() == production_before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
