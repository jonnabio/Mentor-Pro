"""Per-model rate-limit cooldown (T064).

A free model that is still rate limited (HTTP 429) after its bounded retries, or
that asks for a wait longer than the client's maximum back-off, is skipped by the
router until its cooldown ends. Without this every request, slot and seeding cell
called the same exhausted model again (production 2026-11-05..09: one fallback
model answered 429 to all 31 calls). The registry is process-wide and
thread-safe; it never sends a request and never changes budgets or the model list.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

DEFAULT_COOLDOWN_S = 300.0
MAX_COOLDOWN_S = 3600.0


class ModelCooldown:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._until: dict[str, float] = {}

    def start(self, model: str, seconds: float) -> None:
        """Skip `model` for `seconds` (bounded); a longer existing cooldown is kept."""
        seconds = min(MAX_COOLDOWN_S, max(0.0, seconds))
        with self._lock:
            self._until[model] = max(self._until.get(model, 0.0), self._clock() + seconds)

    def remaining(self, model: str) -> float:
        with self._lock:
            left = self._until.get(model, 0.0) - self._clock()
            if left <= 0:
                self._until.pop(model, None)
                return 0.0
            return left

    def clear(self) -> None:
        with self._lock:
            self._until.clear()


COOLDOWN = ModelCooldown()  # shared by every router call in the process
