"""Question bank inventory and performance-based replenishment (T061, T062; ADR-036).

Inventory is measured per objective and difficulty (a "cell" here):

- eligible: what practices can serve now (`QuestionBank.candidates`, the composer's own rule);
- pending_review: seeder-generated candidates never reviewed by the tutor (held from practices);
- quarantined: questions whose latest tutor verdict is `quarantined`;
- rejected: generation attempts rejected by automated validation (never stored as questions);
- served, answered, correct and accuracy from real practices (T060 analytics; test sessions excluded).

A policy turns that into replenishment requests, one per cell and trigger, each with the evidence that
triggered it:

- coverage: the cell has no eligible question and no candidate awaiting review;
- low_inventory: eligible plus awaiting-review questions below `low_inventory`;
- performance: at least `min_answered` answers and accuracy at or above `mastery_threshold`, so the student
  has mostly mastered the cell's questions. Coverage and inventory triggers never depend on accuracy.

A cell has at most one pending request (open, or candidates awaiting review); a pending request is never
generated twice. `run` generates candidates for pending requests with the existing seeder
(`seeding.run --objective`: planned gap cells only, the advisory lock, the shared daily budget, free models
only, D01) and stops at `max_batch` candidates or `max_calls` per subject. Every generated candidate is held
from practices until a human tutor approves it (ADR-034); nothing here records a verdict.
"""

from __future__ import annotations

import os
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.practice import seeding
from app.practice.bank import QuestionBank
from app.practice.tutor_results import PracticeResults
from curriculum.catalog import PracticeScope, select_objectives

LEVELS = ("easy", "medium", "hard")
TRIGGERS = ("coverage", "low_inventory", "performance")
PENDING = ("open", "candidates_generated")

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS generation;
CREATE TABLE IF NOT EXISTS generation.replenishment_request (
    replenishment_id  TEXT PRIMARY KEY,
    baseline_version  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    objective_code    TEXT NOT NULL,
    difficulty        TEXT NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    trigger           TEXT NOT NULL CHECK (trigger IN ('coverage', 'low_inventory', 'performance')),
    evidence          JSONB NOT NULL,
    policy            JSONB NOT NULL,
    status            TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'candidates_generated', 'closed')),
    close_reason      TEXT,
    candidates        INTEGER NOT NULL DEFAULT 0 CHECK (candidates >= 0),
    calls             INTEGER NOT NULL DEFAULT 0 CHECK (calls >= 0),
    last_stop         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_replenishment_pending ON generation.replenishment_request
    (baseline_version, subject, objective_code, difficulty) WHERE status IN ('open', 'candidates_generated');
CREATE TABLE IF NOT EXISTS generation.inventory_snapshot (
    snapshot_id       TEXT PRIMARY KEY,
    baseline_version  TEXT NOT NULL,
    subject           TEXT NOT NULL,
    taken_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    policy            JSONB NOT NULL,
    inventory         JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_snapshot ON generation.inventory_snapshot (subject, taken_at DESC);
"""


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    """Configurable starting values (PO-QUESTION-BANK-PHASE-B), not validated mastery measures."""
    min_answered: int = 10
    mastery_threshold: float = 0.80
    low_inventory: int = 3
    max_batch: int = 100

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Policy:
        try:
            policy = cls(
                min_answered=int(env.get("MENTOR_PRO_REPLENISH_MIN_ANSWERED", cls.min_answered)),
                mastery_threshold=float(env.get("MENTOR_PRO_REPLENISH_MASTERY", cls.mastery_threshold)),
                low_inventory=int(env.get("MENTOR_PRO_REPLENISH_LOW_INVENTORY", cls.low_inventory)),
                max_batch=int(env.get("MENTOR_PRO_REPLENISH_MAX_BATCH", cls.max_batch)),
            )
        except ValueError as exc:
            raise PolicyError(f"invalid replenishment setting: {exc}") from None
        policy.validate()
        return policy

    def validate(self) -> None:
        if self.min_answered < 1:
            raise PolicyError("MENTOR_PRO_REPLENISH_MIN_ANSWERED must be at least 1")
        if not 0 < self.mastery_threshold <= 1:
            raise PolicyError("MENTOR_PRO_REPLENISH_MASTERY must be in (0, 1]")
        if self.low_inventory < 0:
            raise PolicyError("MENTOR_PRO_REPLENISH_LOW_INVENTORY must be zero or positive")
        if not 1 <= self.max_batch <= 100:
            raise PolicyError("MENTOR_PRO_REPLENISH_MAX_BATCH must be 1..100")


def ensure_schema(url: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL)


def _connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


# ---------------------------------------------------------------- inventory


def inventory(url: str, catalog: psycopg.Connection, baseline: str, subject: str) -> list[dict[str, Any]]:
    """One row per objective and difficulty of the subject's multiple-choice objectives (counts only)."""
    objectives = select_objectives(catalog, baseline, PracticeScope.SUBJECT_SIMULATION, subject).objectives
    codes = [o["workbook_code"] for o in objectives]
    bank = QuestionBank(url)
    eligible: Counter[tuple[str, str]] = Counter()
    with bank.connect() as db:
        for o in objectives:
            evidences = {e["id"]: e["ordinal"] for e in o["evidences"]}
            for row in bank.candidates(catalog, baseline, subject, o["workbook_code"], evidences, LEVELS, db=db):
                eligible[(o["workbook_code"], row["difficulty"])] += 1
    pending: Counter[tuple[str, str]] = Counter()
    batch = seeding.current_batch(url, baseline, subject)
    if batch is not None:
        plan = {c["cell"]: c for c in batch["plan"]}
        for link in seeding._awaiting_item_review(url, batch["batch_id"]).values():
            cell = plan[link["cell"]]
            pending[(cell["objective_code"], cell["difficulty"])] += 1
    with _connect(url) as conn:
        quarantined = Counter((r["objective_code"], r["difficulty"]) for r in conn.execute(
            """SELECT q.objective_code, q.difficulty FROM generation.question_attempt q
               WHERE q.baseline_version = %s AND q.objective_code = ANY(%s) AND q.item->>'subject' = %s
                 AND (SELECT v.verdict FROM generation.bank_item_review v WHERE v.request_id = q.request_id
                      ORDER BY v.review_id DESC LIMIT 1) = 'quarantined'""", (baseline, codes, subject)))
        rejected = Counter((r["objective_code"], r["difficulty"]) for r in conn.execute(
            """SELECT objective_code, difficulty FROM generation.question_attempt
               WHERE baseline_version = %s AND objective_code = ANY(%s) AND status = 'rejected'""",
            (baseline, codes)))
    performance = {(g["objective_code"], g["difficulty"]): g
                   for g in PracticeResults(lambda: url).questions(subject=subject)["groups"]}
    rows = []
    for code in codes:
        for level in LEVELS:
            p = performance.get((code, level), {})
            answered, correct = p.get("answered", 0), p.get("correct", 0)
            rows.append({"objective_code": code, "difficulty": level, "eligible": eligible[(code, level)],
                         "pending_review": pending[(code, level)], "quarantined": quarantined[(code, level)],
                         "rejected": rejected[(code, level)], "served": p.get("served", 0), "answered": answered,
                         "correct": correct,
                         "accuracy": round(correct / answered, 4) if answered else None})
    return rows


def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
    keys = ("eligible", "pending_review", "quarantined", "rejected", "served", "answered", "correct")
    out = {k: sum(r[k] for r in rows) for k in keys}
    out["cells"] = len(rows)
    out["covered_cells"] = sum(1 for r in rows if r["eligible"])
    return out


# ---------------------------------------------------------------- policy


def triggers(row: dict[str, Any], policy: Policy) -> list[tuple[str, dict[str, Any]]]:
    """The triggers a cell meets now, each with its evidence (why)."""
    found = []
    # Candidates awaiting review count towards stock here, so stock already generated is not generated again.
    projected = row["eligible"] + row["pending_review"]
    if projected == 0:
        found.append(("coverage", {"eligible": 0}))
    elif projected < policy.low_inventory:
        found.append(("low_inventory", {"eligible": row["eligible"], "pending_review": row["pending_review"],
                                        "threshold": policy.low_inventory}))
    if row["answered"] >= policy.min_answered and row["accuracy"] is not None \
            and row["accuracy"] >= policy.mastery_threshold:
        found.append(("performance", {"answered": row["answered"], "accuracy": row["accuracy"],
                                      "min_answered": policy.min_answered,
                                      "threshold": policy.mastery_threshold}))
    return found


def assess(url: str, catalog: psycopg.Connection, baseline: str, subject: str, policy: Policy) -> dict[str, Any]:
    """Measure, store a snapshot, close pending requests whose cell no longer triggers (after review) and open
    one request per newly triggered cell. Never generates. Idempotent: running it twice opens nothing twice."""
    ensure_schema(url)
    rows = inventory(url, catalog, baseline, subject)
    opened, closed = [], []
    with _connect(url) as conn, conn.transaction():
        conn.execute("INSERT INTO generation.inventory_snapshot (snapshot_id, baseline_version, subject, policy, "
                     "inventory) VALUES (%s, %s, %s, %s, %s)",
                     (f"inv-{uuid.uuid4().hex[:12]}", baseline, subject, Jsonb(asdict(policy)), Jsonb(rows)))
        pending = {(r["objective_code"], r["difficulty"]): r for r in conn.execute(
            "SELECT * FROM generation.replenishment_request WHERE baseline_version = %s AND subject = %s "
            "AND status IN ('open', 'candidates_generated')", (baseline, subject))}
        for row in rows:
            key = (row["objective_code"], row["difficulty"])
            found = triggers(row, policy)
            request = pending.get(key)
            if request is not None:
                awaiting = request["status"] == "candidates_generated" and row["pending_review"] > 0
                if not found:
                    reason = "satisfied"
                elif request["status"] == "candidates_generated" and not awaiting:
                    reason = "reviewed"          # its candidates were reviewed; a new request may follow later
                else:
                    continue                      # still pending: never generated twice
                conn.execute("UPDATE generation.replenishment_request SET status = 'closed', close_reason = %s, "
                             "updated_at = now() WHERE replenishment_id = %s", (reason, request["replenishment_id"]))
                closed.append({**{k: request[k] for k in ("replenishment_id", "objective_code", "difficulty")},
                               "close_reason": reason})
                continue
            if not found:
                continue
            trigger, evidence = found[0]
            evidence = {**evidence, "also": [t for t, _ in found[1:]], "pending_review": row["pending_review"]}
            created = conn.execute(
                """INSERT INTO generation.replenishment_request (replenishment_id, baseline_version, subject,
                       objective_code, difficulty, trigger, evidence, policy)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING replenishment_id""",
                (f"rp-{uuid.uuid4().hex[:12]}", baseline, subject, *key, trigger, Jsonb(evidence),
                 Jsonb(asdict(policy)))).fetchone()
            if created:
                opened.append({"replenishment_id": created["replenishment_id"], "objective_code": key[0],
                               "difficulty": key[1], "trigger": trigger, "evidence": evidence})
    return {"subject": subject, "totals": totals(rows), "opened": opened, "closed": closed,
            "pending": requests(url, baseline, subject, pending_only=True)}


def requests(url: str, baseline: str, subject: str | None = None, pending_only: bool = False,
             read_only: bool = False) -> list[dict[str, Any]]:
    where = ["baseline_version = %s"]
    params: list[Any] = [baseline]
    if subject:
        where.append("subject = %s")
        params.append(subject)
    if pending_only:
        where.append("status IN ('open', 'candidates_generated')")
    with _connect(url) as conn:
        conn.read_only = read_only
        try:
            return conn.execute(
                f"""SELECT replenishment_id, subject, objective_code, difficulty, trigger, evidence, status,
                           close_reason, candidates, calls, last_stop, created_at, updated_at
                    FROM generation.replenishment_request WHERE {' AND '.join(where)}
                    ORDER BY created_at DESC LIMIT 500""", params).fetchall()
        except psycopg.errors.UndefinedTable:
            return []


# ---------------------------------------------------------------- generation


def run(url: str, catalog: psycopg.Connection, baseline: str, subject: str, llm_factory: Callable[[], tuple],
        policy: Policy, max_calls: int, seed_run: Callable[..., dict[str, Any]] = seeding.run) -> dict[str, Any]:
    """Assess, then generate candidates for open requests, objective by objective, until `policy.max_batch`
    candidates or `max_calls` calls. Free models only (no paid opener is ever passed). Each objective is
    generated once per run even when several of its difficulties are open."""
    if max_calls < 0:
        raise seeding.SeedError("max_calls must be zero or positive")
    assessed = assess(url, catalog, baseline, subject, policy)
    open_rows = [r for r in requests(url, baseline, subject, pending_only=True) if r["status"] == "open"]
    by_objective: dict[str, list[dict[str, Any]]] = {}
    for r in sorted(open_rows, key=lambda r: (TRIGGERS.index(r["trigger"]), r["objective_code"], r["difficulty"])):
        by_objective.setdefault(r["objective_code"], []).append(r)
    generated = calls = 0
    stop = None
    runs = []
    for objective, rows in by_objective.items():
        remaining = max_calls - calls
        if remaining <= 0 or generated >= policy.max_batch:
            stop = "run_call_limit" if remaining <= 0 else "max_batch"
            break
        try:
            out = seed_run(url, catalog, baseline, subject, llm_factory, max_calls=remaining, objective=objective)
        except seeding.SeedError as exc:
            if "has no planned cell" not in str(exc):
                raise
            out = {"run": {"generated": 0, "calls": 0, "stop_reason": "no_planned_cell"}}
        result = out["run"]
        generated += result["generated"]
        calls += result["calls"]
        runs.append({"objective_code": objective, **{k: result.get(k) for k in ("generated", "calls", "stop_reason")}})
        with _connect(url) as conn:
            for r in rows:
                if result["generated"]:
                    conn.execute("UPDATE generation.replenishment_request SET status = 'candidates_generated', "
                                 "candidates = candidates + %s, calls = calls + %s, last_stop = %s, updated_at = now() "
                                 "WHERE replenishment_id = %s",
                                 (result["generated"], result["calls"], result.get("stop_reason"),
                                  r["replenishment_id"]))
                elif result.get("stop_reason") in (None, "no_planned_cell"):
                    # Nothing left to generate in the fixed plan for this objective: needs a PO decision (ADR-036).
                    conn.execute("UPDATE generation.replenishment_request SET status = 'closed', "
                                 "close_reason = 'no_planned_gap', calls = calls + %s, updated_at = now() "
                                 "WHERE replenishment_id = %s", (result["calls"], r["replenishment_id"]))
                else:
                    conn.execute("UPDATE generation.replenishment_request SET calls = calls + %s, last_stop = %s, "
                                 "updated_at = now() WHERE replenishment_id = %s",
                                 (result["calls"], result.get("stop_reason"), r["replenishment_id"]))
        if result.get("stop_reason") in ("daily_budget", "provider_rate_limited", "run_call_limit"):
            stop = result["stop_reason"]
            break
    return {"subject": subject, "assessed": assessed["totals"], "opened": len(assessed["opened"]),
            "generated": generated, "calls": calls, "stop_reason": stop, "runs": runs,
            "pending": requests(url, baseline, subject, pending_only=True)}


# ---------------------------------------------------------------- tutor view (read-only)


def latest_snapshots(url: str, baseline: str) -> list[dict[str, Any]]:
    with _connect(url) as conn:
        conn.read_only = True
        try:
            return conn.execute(
                """SELECT DISTINCT ON (subject) subject, taken_at, policy, inventory
                   FROM generation.inventory_snapshot WHERE baseline_version = %s
                   ORDER BY subject, taken_at DESC""", (baseline,)).fetchall()
        except psycopg.errors.UndefinedTable:
            return []
