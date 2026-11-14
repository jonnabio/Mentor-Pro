"""Scheduled replenishment ticks (T066). mentor_pro_test, fake runs or a mocked LLM only."""

from __future__ import annotations

import functools

import psycopg
import pytest

from app.practice import replenish_schedule as rs
from app.practice import replenishment, seeding
from app.practice.replenish_schedule import ScheduleError, ScheduleSettings
from conftest import SYNTHETIC
from test_bank_seeding import TARGET, factory, item, url  # noqa: F401  (fixture)
from test_generation import FakeLlm, catalog_conn  # noqa: F401  (fixture)
from test_replenishment import clean_requests

SUBJECTS = ("espanol", "matematicas", "ciencias", "estudios_sociales")
ON = ScheduleSettings(enabled=True, tick_calls=10)
POLICY = replenishment.Policy()


def clean_schedule(url):
    rs.ensure_schema(url)
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DELETE FROM generation.replenish_tick")
        conn.execute("UPDATE generation.replenish_schedule SET paused = false, reason = NULL, next_index = 0")


@pytest.fixture()
def db(url):
    clean_schedule(url)
    clean_requests(url)
    yield url
    clean_schedule(url)
    clean_requests(url)


class FakeRun:
    """Stands in for replenishment.run: spends `calls` per subject, optional per-subject outcomes."""

    def __init__(self, calls=3, outcomes=None):
        self.calls, self.outcomes, self.seen = calls, outcomes or {}, []

    def __call__(self, url, catalog, baseline, subject, llm_factory, policy, max_calls):
        self.seen.append((subject, max_calls))
        outcome = self.outcomes.get(subject)
        if isinstance(outcome, Exception):
            raise outcome
        spent = min(self.calls, max_calls)
        return {"subject": subject, "opened": 1, "generated": 1, "calls": spent,
                "stop_reason": outcome or ("run_call_limit" if spent >= max_calls else None), "pending": [{}]}


def tick(url, settings=ON, run=None, subjects=SUBJECTS):
    return rs.tick(url, None, SYNTHETIC, lambda: None, POLICY, settings, subjects, run=run or FakeRun())


# ---------------------------------------------------------------- settings


def test_settings_default_off_and_bounded():
    assert ScheduleSettings.from_env({}) == ScheduleSettings(enabled=False, tick_calls=10)
    assert ScheduleSettings.from_env({"MENTOR_PRO_REPLENISH_SCHEDULE": "on",
                                      "MENTOR_PRO_REPLENISH_TICK_CALLS": "20"}) == ScheduleSettings(True, 20)
    for env in ({"MENTOR_PRO_REPLENISH_SCHEDULE": "yes"}, {"MENTOR_PRO_REPLENISH_TICK_CALLS": "0"},
                {"MENTOR_PRO_REPLENISH_TICK_CALLS": "51"}, {"MENTOR_PRO_REPLENISH_TICK_CALLS": "x"}):
        with pytest.raises(ScheduleError):
            ScheduleSettings.from_env(env)


# ---------------------------------------------------------------- switches and concurrency


def test_disabled_tick_runs_nothing_and_is_recorded(db):
    run = FakeRun()
    out = tick(db, ScheduleSettings(enabled=False), run)
    assert (out["status"], out["reason"], run.seen) == ("skipped", "disabled", [])


def test_pause_and_resume_without_restart(db):
    rs.set_paused(db, True, "tutor backlog")
    run = FakeRun()
    out = tick(db, run=run)
    assert (out["status"], out["reason"], run.seen) == ("skipped", "paused", [])
    assert rs.status(db, ON)["pause_reason"] == "tutor backlog"
    rs.set_paused(db, False)
    assert tick(db, run=run)["status"] == "ok" and run.seen


def test_concurrent_tick_is_skipped_as_busy(db):
    holder = psycopg.connect(db, autocommit=True)
    try:
        holder.execute("SELECT pg_advisory_lock(%s, %s)", rs.SCHEDULE_LOCK)
        run = FakeRun()
        out = tick(db, run=run)
        assert (out["status"], out["reason"], run.seen) == ("skipped", "busy", [])
    finally:
        holder.close()
    assert tick(db)["status"] == "ok"  # the lock is released with its connection


# ---------------------------------------------------------------- bounds and rotation


def test_tick_spends_at_most_its_call_budget_and_rotates(db):
    run = FakeRun(calls=4)
    out = tick(db, run=run)
    # T067: each subject gets at most max(objective_calls, ceil(10 / 4)) = 5 calls of the tick.
    assert run.seen == [("espanol", 5), ("matematicas", 5), ("ciencias", 2)]
    assert (out["status"], out["calls"], out["reason"]) == ("ok", 10, "tick_call_limit")
    run2 = FakeRun(calls=4)
    tick(db, run=run2)
    assert run2.seen[0][0] == "estudios_sociales"  # resumes after the last subject served


def test_one_subject_cannot_take_the_whole_tick(db):
    run = FakeRun(calls=50)  # each subject would spend everything it is given
    out = tick(db, run=run)
    assert [s for s, _ in run.seen] == ["espanol", "matematicas"] and all(m == 5 for _, m in run.seen)
    assert out["calls"] == 10


def test_budget_stop_ends_the_tick(db):
    run = FakeRun(calls=1, outcomes={"matematicas": "daily_budget"})
    out = tick(db, run=run)
    assert [s for s, _ in run.seen] == ["espanol", "matematicas"]
    assert (out["status"], out["reason"]) == ("ok", "daily_budget")


def test_busy_subject_is_skipped_and_the_tick_continues(db):
    run = FakeRun(calls=1, outcomes={"espanol": seeding.SeedBusy("SEED BUSY")})
    out = tick(db, run=run)
    assert out["status"] == "ok"
    assert out["detail"][0] == {"subject": "espanol", "skipped": "subject_busy"}
    assert [s for s, _ in run.seen] == list(SUBJECTS)


# ---------------------------------------------------------------- failure reporting


def test_failure_is_recorded_and_counted(db):
    run = FakeRun(outcomes={"espanol": RuntimeError("provider down")})
    out = tick(db, run=run)
    assert out["status"] == "failed" and "provider down" in out["error"]
    tick(db, ScheduleSettings(enabled=False))  # skips do not reset or add to the failure count
    tick(db, run=FakeRun(outcomes={"matematicas": RuntimeError("again")}))
    assert rs.status(db, ON)["consecutive_failures"] == 2
    tick(db)
    assert rs.status(db, ON)["consecutive_failures"] == 0


def test_a_tick_left_running_is_marked_abandoned(db):
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("INSERT INTO generation.replenish_tick (tick_id, status, started_at) "
                     "VALUES ('tick-stale', 'running', now() - interval '3 hours')")
    tick(db)
    recent = {t["tick_id"]: t for t in rs.status(db, ON)["recent"]}
    assert recent["tick-stale"]["status"] == "abandoned"


# ---------------------------------------------------------------- end to end with the real replenishment run


def test_scheduled_ticks_generate_held_candidates_once(db, catalog_conn):
    real = functools.partial(
        lambda url, catalog, baseline, subject, llm_factory, policy, max_calls: replenishment.run(
            url, catalog, baseline, subject, factory(url, FakeLlm([item(i) for i in range(10)])), policy,
            max_calls, seed_run=functools.partial(seeding.run, target=TARGET)))
    first = rs.tick(db, catalog_conn, SYNTHETIC, lambda: None, POLICY, ScheduleSettings(True, 50),
                    ("matematicas",), run=real)
    assert first["status"] == "ok" and first["generated"] > 0
    rows = replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas")
    assert replenishment.totals(rows)["pending_review"] == first["generated"]  # held, never approved
    second = rs.tick(db, catalog_conn, SYNTHETIC, lambda: None, POLICY, ScheduleSettings(True, 50),
                     ("matematicas",), run=real)
    # While its candidates await the tutor, the plan holds no gap: the next tick generates nothing again.
    assert (second["status"], second["generated"]) == ("ok", 0)
    rows = replenishment.inventory(db, catalog_conn, SYNTHETIC, "matematicas")
    assert replenishment.totals(rows)["pending_review"] == first["generated"]
