"""Atomic per-call budget reservation (ADR-012).

Every HTTP attempt reserves one request before it is sent. Under one lock the
gate compares persisted usage plus reservations still in flight with the
daily request budget, an optional per-set call cap and, for paid calls, the
daily USD budget. Concurrent workers therefore can never send more calls than
a limit allows. Reservations are settled once their usage records are stored.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from app.llm.settings import LlmSettings


class UsageView(Protocol):
    def today(self) -> dict[str, Any]: ...


class BudgetGate:
    def __init__(self, store: UsageView, settings: LlmSettings, max_calls: int | None = None):
        self.store, self.settings, self.max_calls = store, settings, max_calls
        self._lock = threading.Lock()
        self._in_flight = 0
        self._paid_in_flight = 0
        self.sent = 0                 # calls reserved through this gate (the per-set count)
        self.refusal: str | None = None
        # T067: when set, a generation attempt starts only if the per-set cap still covers this many calls, so a
        # question is never generated and then left unchecked (solve or review blocked by the cap).
        self.attempt_calls = 0
        self._short = False

    def acquire(self, tier: str) -> bool:
        """Reserve one call; False (and `refusal` set) if any limit would be exceeded."""
        with self._lock:
            usage = self.store.today()
            if self.max_calls is not None and self.sent >= self.max_calls:
                return self._refuse("set call limit reached")
            if usage["requests"] + self._in_flight >= self.settings.max_requests_per_day:
                return self._refuse("daily request budget reached")
            if tier == "paid":
                # Cost is known only after the call: allow one paid call in flight at a time.
                # T055: unknown paid costs count at their worst-case liability until reconciled.
                exposure = usage.get("paid_exposure_usd", usage["paid_usd"])
                if (self._paid_in_flight or usage["paid_unknown"] > 0
                        or exposure >= self.settings.max_usd_per_day):
                    return self._refuse("paid fallback blocked by the daily USD budget")
                self._paid_in_flight += 1
            self._in_flight += 1
            self.sent += 1
            return True

    def settle(self, calls: int, paid_calls: int = 0) -> None:
        """Release reservations whose usage records are now in the store."""
        with self._lock:
            self._in_flight = max(0, self._in_flight - calls)
            self._paid_in_flight = max(0, self._paid_in_flight - paid_calls)

    def covers_attempt(self) -> bool:
        """T067: False (set limit reached) when `attempt_calls` is set and the per-set cap cannot cover it."""
        with self._lock:
            if self.attempt_calls and self.max_calls is not None                     and self.max_calls - self.sent < self.attempt_calls:
                self._short = True
                self.refusal = "set call limit reached"
                return False
            return True

    @property
    def set_limit_hit(self) -> bool:
        return self._short or (self.max_calls is not None and self.sent >= self.max_calls)

    def _refuse(self, reason: str) -> bool:
        self.refusal = reason
        return False
