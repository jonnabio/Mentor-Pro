"""T055 review fixes: explicit `llm` migration (no start-up DDL), daily exposure for unknown paid costs, and
operator-only access to the paid CLI."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.llm import costs, migrations, paid
from app.llm.router import route
from app.llm.usage import MemoryUsageStore, UsageStore, paid_exposure
from test_openrouter import MSG, completion, failing_free
from test_paid_approval import PAID, Billing, grant_for, history, make

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def fresh_db():
    """A throwaway database, so migrations never touch the shared test database's `llm` schema."""
    from curriculum import db
    from workbook_fixtures import TEST_DATABASE_URL

    base = db.require_test_database(TEST_DATABASE_URL)
    name = f"mp_llm_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(base, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {name}")
    try:
        yield make_conninfo(base, dbname=name)
    finally:
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE {name} WITH (FORCE)")


def state(url):
    with migrations._connect(url) as conn:
        return migrations.state(conn)["state"]


def row(**over):
    base = {"schema_version": "1.0", "call_id": f"c-{uuid.uuid4().hex}", "request_id": "r", "practice_set_id": None,
            "purpose": "generation", "attempt": 1, "is_fallback": False, "model_requested": "m:free",
            "model_used": "m:free", "provider": "p", "tier": "free", "tokens_in": 10, "tokens_out": 5,
            "cost_usd": 0.0, "cost_source": "provider_reported", "latency_ms": 1, "status": "ok",
            "started_at": "2026-11-05T10:00:00Z", "generation_id": None, "error_kind": None, "subject": "matematicas",
            "objective_code": "M09", "reasoning_tokens": None, "failure_category": None, "authorization_id": None,
            "liability_usd": None}
    return {**base, **over}


# ---------------------------------------------------------------- blocker 1: controlled schema evolution

def test_startup_never_adds_t055_schema(fresh_db):
    store = UsageStore(fresh_db)                         # what the application does at start
    assert state(fresh_db) == "base" and not store.migrated
    store.add(row())                                     # T055 fields are dropped, as an older image writes
    with psycopg.connect(fresh_db) as conn:
        assert conn.execute("SELECT count(*) FROM llm.usage_record").fetchone()[0] == 1
        assert conn.execute("SELECT to_regclass('llm.paid_authorization')").fetchone()[0] is None
    with pytest.raises(paid.PaidRefused, match="L001_paid_cost_tracking is not applied"):
        paid.AuthorizationStore(fresh_db)                # paid generation stays unavailable: free-only


def test_apply_is_explicit_checked_and_idempotent(fresh_db):
    UsageStore(fresh_db).add(row())
    dry = migrations.apply(fresh_db, dry_run=True)
    assert dry["result"] == "dry_run_ok" and state(fresh_db) == "base"
    done = migrations.apply(fresh_db)
    assert done["result"] == "applied" and done["usage_rows"] == 1 and state(fresh_db) == "current"
    assert migrations.apply(fresh_db) == {"result": "already_applied", "migration": migrations.L001}
    store = UsageStore(fresh_db)
    assert store.migrated
    store.add(row(tier="paid", cost_usd=None, liability_usd=0.05, cost_source="missing"))
    paid.AuthorizationStore(fresh_db)                    # now available


def test_older_image_inserts_still_work_on_a_migrated_database(fresh_db):
    migrations.apply(fresh_db)
    old = {k: v for k, v in row().items() if k in migrations.ORIGINAL_COLUMNS}
    with psycopg.connect(fresh_db) as conn:              # the column list an earlier image sends
        conn.execute(f"INSERT INTO llm.usage_record ({', '.join(old)}) VALUES ({', '.join(['%s'] * len(old))})",
                     list(old.values()))


def test_apply_on_an_empty_database_creates_the_base_table_first(fresh_db):
    assert state(fresh_db) == "none"
    assert migrations.apply(fresh_db)["result"] == "applied" and state(fresh_db) == "current"


def test_drifted_schema_is_refused(fresh_db):
    UsageStore(fresh_db)
    with psycopg.connect(fresh_db) as conn:
        conn.execute("ALTER TABLE llm.usage_record ADD COLUMN subject TEXT")
    assert state(fresh_db) == "drifted"
    with pytest.raises(migrations.MigrationError, match="drifted"):
        migrations.apply(fresh_db)


def test_rollback_refuses_while_l001_data_exists(fresh_db):
    migrations.apply(fresh_db)
    UsageStore(fresh_db).add(row())                      # subject is set
    with pytest.raises(migrations.MigrationError, match="usage rows use L001 data"):
        migrations.rollback(fresh_db)
    with psycopg.connect(fresh_db) as conn:
        conn.execute("UPDATE llm.usage_record SET subject = NULL, objective_code = NULL")
    assert migrations.rollback(fresh_db)["result"] == "rolled_back" and state(fresh_db) == "base"


def test_writing_schema_range_and_deploy_tool_are_unchanged():
    from app.writing import migrations as writing

    assert (writing.SCHEMA_MIN, writing.SCHEMA_MAX) == ("0001", "0001")
    assert "llm" not in (REPO / "deploy/mentorpro_deploy.py").read_text(encoding="utf-8").split("KNOWN_MIGRATIONS")[1][:80]


# ---------------------------------------------------------------- blocker 2: daily exposure of unknown costs

def unknown_cost_fake():
    # A paid call answered without a reported cost or a resolvable generation id: cost unknown.
    return Billing({**failing_free(), PAID: [(200, completion(PAID, cost=None, gen_id="gen-u"), {})]})


def test_unknown_paid_cost_is_held_on_the_record_as_liability():
    client, usage = make(unknown_cost_fake()), history()
    grant, _ = grant_for(client, usage, ceiling=0.5)
    route(client, usage, MSG, "generation", paid=grant, max_tokens=4000)
    record = usage.records[-1]
    assert record["cost_usd"] is None and record["liability_usd"] == pytest.approx(0.06375)
    assert usage.today()["paid_exposure_usd"] == pytest.approx(0.06375) and usage.today()["paid_usd"] == 0


def test_successive_authorization_sees_the_previous_unknown_liability():
    fake = unknown_cost_fake()
    client, usage = make(fake, max_usd_per_day=0.1, paid_max_usd_per_operation=0.1), history()
    first, store = grant_for(client, usage, ceiling=0.1)
    route(client, usage, MSG, "generation", paid=first, max_tokens=4000)
    first.finish()
    second, _ = grant_for(client, usage, ceiling=0.1, store=store)
    # 0.1 daily - 0.06375 held = 0.03625 left; one worst-case call (0.06375) no longer fits.
    assert second.reserve("generation", 4000) is None
    assert route(client, usage, MSG, "generation", paid=second, max_tokens=4000).status != "ok"
    assert fake.chat_models().count(PAID) == 1


def test_reconciliation_releases_the_liability_without_double_counting():
    fake = unknown_cost_fake()
    client, usage = make(fake, max_usd_per_day=0.1, paid_max_usd_per_operation=0.1), history()
    first, store = grant_for(client, usage, ceiling=0.1)
    route(client, usage, MSG, "generation", paid=first, max_tokens=4000)
    first.finish()
    fake.generation = {"total_cost": 0.004}
    assert costs.reconcile(usage, client)["filled_missing"] == 1
    assert usage.today()["paid_exposure_usd"] == pytest.approx(0.004)   # the actual cost replaces the liability
    second, _ = grant_for(client, usage, ceiling=0.1, store=store)
    assert second.reserve("generation", 4000) == pytest.approx(0.06375)


def test_report_shows_unreconciled_liability_in_the_budget():
    client, usage = make(unknown_cost_fake()), history()
    grant, _ = grant_for(client, usage, ceiling=0.5)
    route(client, usage, MSG, "generation", paid=grant, max_tokens=4000)
    out = costs.report(usage, client.settings)
    assert out["today"]["unreconciled_liability_usd"] == pytest.approx(0.06375)
    assert out["budget"]["paid_exposure_usd_today"] == pytest.approx(0.06375)
    assert out["budget"]["paid_usd_remaining"] == pytest.approx(2.0 - 0.06375)


def test_exposure_counts_each_attempt_once():
    assert paid_exposure({"tier": "paid", "status": "ok", "cost_usd": 0.01, "liability_usd": 0.06}) == 0.01
    assert paid_exposure({"tier": "paid", "status": "timeout", "cost_usd": None, "liability_usd": 0.06}) == 0.06
    assert paid_exposure({"tier": "paid", "status": "budget_blocked", "cost_usd": None, "liability_usd": 9}) == 0
    assert paid_exposure({"tier": "free", "status": "ok", "cost_usd": None, "liability_usd": None}) == 0


def test_402_after_a_retry_records_every_sent_attempt():
    fake = Billing({"acme/big:free": [(503, {}, {}), (402, {"error": {"code": 402}}, {})],
                    "acme/small:free": [(503, {}, {})]})
    usage = MemoryUsageStore()
    route(make(fake, max_retries=1, allow_paid=False), usage, MSG, "generation")
    big = [r["failure_category"] for r in usage.records if r["model_requested"] == "acme/big:free"]
    assert big == ["provider_failure", "insufficient_credits"]   # the retry before the 402 is not lost


def test_paid_402_holds_no_liability():
    fake = Billing({**failing_free(), PAID: [(402, {"error": {"code": 402}}, {})]})
    client, usage = make(fake), history()
    grant, _ = grant_for(client, usage, ceiling=0.5)
    assert route(client, usage, MSG, "generation", paid=grant, max_tokens=4000).status == "payment_required"
    assert usage.records[-1]["liability_usd"] == 0.0 and usage.today()["paid_exposure_usd"] == 0


def test_postgres_daily_exposure_and_concurrent_reservations(fresh_db):
    migrations.apply(fresh_db)
    usage = UsageStore(fresh_db)
    usage.add(row(tier="paid", cost_usd=None, cost_source="missing", liability_usd=0.04,
                  started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                  .strftime("%Y-%m-%dT%H:%M:%SZ")))
    assert usage.today()["paid_exposure_usd"] == pytest.approx(0.04) and usage.today()["paid_usd"] == 0
    store = paid.AuthorizationStore(fresh_db)
    store.create({"authorization_id": "PA-x", "subject": "matematicas", "objective_code": "M09", "questions": 1,
                  "model": PAID, "estimate": {"status": "ok"}})
    assert store.decide("PA-x", True, 1.0, "parent") and store.claim("PA-x")
    headroom = 0.1 - usage.today()["paid_exposure_usd"]  # daily 0.1 minus the held liability
    won = []

    def worker():
        if store.reserve("PA-x", 0.02, headroom):
            won.append(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(won) == 3                                 # 3 x 0.02 <= 0.06 < 4 x 0.02


# ---------------------------------------------------------------- operator access

def test_no_web_route_reaches_paid_approval_or_cost_commands(synthetic_client):
    paths = [getattr(r, "path", "") for r in synthetic_client.app.routes]
    assert not [p for p in paths if re.search(r"paid|credit|cost|authoriz|billing", p, re.I)]
    # Only operator CLIs import the paid, cost and migration commands; no route module does.
    pattern = re.compile(r"^\s*(from app\.llm\.(paid|costs|migrate)\b|from app\.llm import .*\b(paid|costs|migrate)\b)",
                         re.M)
    importers = [p.relative_to(REPO).as_posix() for p in (REPO / "app").rglob("*.py")
                 if pattern.search(p.read_text(encoding="utf-8"))]
    assert sorted(importers) == ["app/llm/costs.py", "app/practice/seed_bank.py"]
