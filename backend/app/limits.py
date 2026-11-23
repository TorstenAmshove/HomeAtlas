"""Tiny in-memory sliding-window rate limiter.

Process-local on purpose: the backend runs as one process, and losing the counters on restart is
harmless. Imports nothing from `db`, `routes/` or any write-capable module."""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable, Hashable


class SlidingWindowLimiter:
    """Allows at most `max_calls` per `window_s` seconds for each key."""

    def __init__(self, max_calls: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        if max_calls < 1 or window_s <= 0:
            raise ValueError("max_calls must be >= 1 and window_s > 0")
        self.max_calls = max_calls
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[Hashable, deque[float]] = {}

    def allow(self, key: Hashable) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds). Rejected calls are not counted."""
        now = self._clock()
        # Drop expired entries for every key so abandoned keys don't accumulate.
        for k in list(self._hits):
            hits = self._hits[k]
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if not hits:
                del self._hits[k]
        hits = self._hits.setdefault(key, deque())
        if len(hits) >= self.max_calls:
            return False, max(1, math.ceil(hits[0] + self.window_s - now))
        hits.append(now)
        return True, 0

    def reset(self) -> None:
        self._hits.clear()
