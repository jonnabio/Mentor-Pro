"""In-process generation job queue for practice sessions (ADR-013).

One worker thread runs one set at a time (each set already generates slots in
parallel, ADR-012). Job state lives in PostgreSQL (`PracticeStore`); the
worker only moves it forward. Logs carry session IDs and statuses, never
items, answers or student data.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from app.generation.practice_set import PracticeSetResult, SetLimits, generate_set
from app.practice.store import PracticeStore

log = logging.getLogger("mentor_pro.practice")

# runner(session_row, on_slot_done) -> PracticeSetResult; injected for tests and mocked browser runs.
# The session row passed in carries only the allocation slots still missing (T013: the rest came from the
# bank) and `seed_items`, the bank items already in the set (for set-wide duplicate checks).
SetRunner = Callable[[dict[str, Any], Callable[[Any], None]], PracticeSetResult]


def missing_allocation(allocation: list[dict[str, Any]], filled: set[int]) -> list[dict[str, Any]]:
    """The allocation restricted to slots without an item, keeping objective, evidencia and slot numbers."""
    rows = []
    for row in allocation:
        slots = [s for s in row["slots"] if s["slot"] not in filled]
        if slots:
            rows.append({**row, "slots": slots, "questions": len(slots)})
    return rows


def live_set_runner(llm_factory: Callable[[], tuple[Any, Any, Any]], open_catalog: Callable[[], Any]) -> SetRunner:
    """Generate with OpenRouter through the validated engine and persist the set (ADR-011)."""
    def run(session: dict[str, Any], on_slot_done: Callable[[Any], None]) -> PracticeSetResult:
        limits = SetLimits.from_env()
        client, usage_store, generation_store = llm_factory()
        conn = open_catalog()
        try:
            result = generate_set(conn, client, usage_store, generation_store, session["baseline_version"],
                                  session["subject"], session["allocation"], limits, on_slot_done=on_slot_done,
                                  seed_items=session.get("seed_items", []))
        finally:
            conn.close()
            client.close()
        generation_store.add_set(result, session["baseline_version"], session["config"], session["allocation"],
                                 asdict(limits))
        return result
    return run


class JobQueue:
    def __init__(self, store: PracticeStore, runner: SetRunner):
        self.store, self.runner = store, runner
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="practice-job")

    def submit(self, session_id: str) -> None:
        self._pool.submit(self._run, session_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _run(self, session_id: str) -> None:
        session = self.store.get(session_id)
        if session is None or session["status"] != "queued":
            return
        self.store.mark_running(session_id)
        existing = self.store.items(session_id)  # bank items chosen when the session was created
        done = [len(existing)]
        pending = {**session, "allocation": missing_allocation(session["allocation"], {r["slot"] for r in existing}),
                   "seed_items": [r["item"] for r in existing]}

        def on_slot_done(_slot: Any) -> None:
            done[0] += 1
            self.store.progress(session_id, done[0])

        try:
            result = self.runner(pending, on_slot_done)
        except Exception as exc:  # noqa: BLE001 - any failure must end the job, not leave it running
            log.error("practice job %s failed: %s", session_id, type(exc).__name__)
            self.store.finish(session_id, "partial" if existing else "failed", "internal_error", None, [])
            return
        items = [{"slot": s.slot, "objective_code": s.objective_code, "evidence_id": s.evidence_id, "item": s.item,
                  "source": "generated", "source_request_id": s.request_id}
                 for s in result.slots if s.status == "accepted"]
        total = len(existing) + len(items)
        status = "complete" if total == session["slots_total"] else ("partial" if total else "failed")
        stop_reason = None if status == "complete" else (result.stop_reason or "slot_retries_exhausted")
        self.store.finish(session_id, status, stop_reason, result.practice_set_id, items)
        log.info("practice job %s finished: %s (%s bank + %s generated of %s)", session_id, status,
                 len(existing), len(items), session["slots_total"])
