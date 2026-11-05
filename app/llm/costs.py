"""Operator cost report and reconciliation over `llm.usage_record` (T055, llm-cost-observability).

    python -m app.llm.costs report [--credits]
    python -m app.llm.costs reconcile [--days 7] [--limit 50]

Actual cost is what OpenRouter reported (`provider_reported`) or settled later (`generation_endpoint`).
Estimates are never stored as charges. A sent call with no reported cost is `unknown`, never zero. A
`budget_blocked` row was never sent (no possible charge); every other row was sent and may have been
charged. `--credits` adds the key allowance and, with OPENROUTER_MANAGEMENT_KEY, the account balance.
Output is IDs and metrics only: no prompts, keys or student data.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


def _when(row: dict[str, Any]) -> datetime:
    value = row["started_at"]
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def batch_of(row: dict[str, Any]) -> str:
    """Seeding runs use practice_set_id `seed-<batch_id>-<run>`; student practices are grouped as `practice`."""
    set_id = row.get("practice_set_id") or ""
    if set_id.startswith("seed-"):
        return set_id[len("seed-"):].rsplit("-", 1)[0]
    return "practice" if set_id else "none"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sent = [r for r in rows if r["status"] != "budget_blocked"]
    known = [r for r in sent if r["cost_usd"] is not None]
    return {"calls_sent": len(sent), "calls_never_sent": len(rows) - len(sent),
            "paid_calls": sum(r["tier"] == "paid" for r in sent),
            "actual_usd": round(sum(r["cost_usd"] for r in known), 8),
            "unknown_cost_calls": len(sent) - len(known),
            "unknown_cost_paid_calls": sum(r["tier"] == "paid" and r["cost_usd"] is None for r in sent),
            "tokens_in": sum(r.get("tokens_in") or 0 for r in sent),
            "tokens_out": sum(r.get("tokens_out") or 0 for r in sent),
            "reasoning_tokens": sum(r.get("reasoning_tokens") or 0 for r in sent)}


def _group(rows: list[dict[str, Any]], key) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[str(key(r) or "unknown")].append(r)
    return {k: summarize(v) for k, v in sorted(groups.items())}


def report(store: Any, settings: Any, now: datetime | None = None,
           balance: dict[str, Any] | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = store.rows_since(month_start)
    day = [r for r in month if _when(r) >= day_start]
    today = summarize(day)
    paid_today = sum(r["cost_usd"] or 0 for r in day if r["tier"] == "paid")
    return {
        "currency": "USD",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today": today,
        "month": summarize(month),
        "month_by_model": _group(month, lambda r: r.get("model_used") or r["model_requested"]),
        "month_by_subject": _group(month, lambda r: r.get("subject")),
        "month_by_purpose": _group(month, lambda r: r["purpose"]),
        "month_by_batch": _group(month, batch_of),
        "month_by_failure": _group([r for r in month if r.get("failure_category")], lambda r: r["failure_category"]),
        "budget": {"requests_today": today["calls_sent"], "max_requests_per_day": settings.max_requests_per_day,
                   "requests_remaining": max(0, settings.max_requests_per_day - today["calls_sent"]),
                   "paid_usd_today": round(paid_today, 8), "max_usd_per_day": settings.max_usd_per_day,
                   "paid_usd_remaining": round(max(0.0, settings.max_usd_per_day - paid_today), 8),
                   "paid_unknown_today": today["unknown_cost_paid_calls"]},
        "openrouter_credits": balance or {"status": "not_checked"},
    }


def reconcile(store: Any, client: Any, days: int = 7, limit: int = 50) -> dict[str, Any]:
    """Compare recorded costs with OpenRouter's generation metadata; fill missing ones, report mismatches.

    Read-only towards OpenRouter (GET /generation). Recorded costs are never overwritten; a difference is
    reported for the operator to check against the OpenRouter Activity page.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = [r for r in store.rows_since(since) if r.get("generation_id") and r["status"] != "budget_blocked"
            and r.get("cost_source") != "generation_endpoint"][:limit]
    filled, matched, mismatched, unavailable = 0, 0, [], 0
    for r in rows:
        data = client.generation_stats(r["generation_id"])
        cost = (data or {}).get("total_cost")
        if not isinstance(cost, (int, float)):
            unavailable += 1
            continue
        if r["cost_usd"] is None:
            store.set_cost(r["call_id"], float(cost))
            filled += 1
        elif abs(float(cost) - r["cost_usd"]) > 1e-8:
            mismatched.append({"call_id": r["call_id"], "generation_id": r["generation_id"],
                               "recorded_usd": r["cost_usd"], "openrouter_usd": float(cost)})
        else:
            matched += 1
    return {"checked": len(rows), "matched": matched, "filled_missing": filled, "mismatched": mismatched,
            "metadata_unavailable": unavailable}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.llm.costs")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument("--credits", action="store_true", help="also read key allowance and account balance")
    rec = sub.add_parser("reconcile")
    rec.add_argument("--days", type=int, default=7)
    rec.add_argument("--limit", type=int, default=50)
    args = parser.parse_args(argv)

    from app.llm.client import OpenRouterClient
    from app.llm.paid import check_balance
    from app.llm.settings import LlmSettings
    from app.llm.usage import UsageStore
    from curriculum import db

    store, settings = UsageStore(db.database_url()), LlmSettings.load()
    if args.command == "report":
        balance = None
        if args.credits:
            with OpenRouterClient(settings) as client:
                balance = check_balance(client)
        out = report(store, settings, balance=balance)
    else:
        with OpenRouterClient(settings) as client:
            out = reconcile(store, client, args.days, args.limit)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
