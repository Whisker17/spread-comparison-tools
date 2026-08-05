"""Process-wide rolling counters for upstream incidents (WHI-819).

Adapters and the poller record rate-limit hits here so the monitor can alert
on *sustained* 429s without scraping logs. No persistence — in-memory only.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Final

# Canonical sources the monitor thresholds cover.
RATE_LIMIT_SOURCES: Final[frozenset[str]] = frozenset({"jupiter", "kyber", "rpc"})


class RollingEventCounter:
    """Monotonic-clock timestamps of events, queryable over a trailing window."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = {}

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def record(self, source: str, *, now: float | None = None) -> None:
        """Append one event for ``source`` (e.g. ``jupiter`` / ``kyber`` / ``rpc``)."""
        key = source.strip().lower()
        if not key:
            return
        ts = self._clock() if now is None else now
        with self._lock:
            bucket = self._events.get(key)
            if bucket is None:
                bucket = deque()
                self._events[key] = bucket
            bucket.append(ts)

    def count(self, source: str, *, window_sec: float, now: float | None = None) -> int:
        """Events for ``source`` with age ≤ ``window_sec`` (prunes older entries)."""
        if window_sec < 0:
            raise ValueError(f"window_sec must be >= 0, got {window_sec}")
        key = source.strip().lower()
        ts = self._clock() if now is None else now
        cutoff = ts - window_sec
        with self._lock:
            bucket = self._events.get(key)
            if not bucket:
                return 0
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            return len(bucket)

    def counts(
        self, sources: frozenset[str] | set[str], *, window_sec: float
    ) -> dict[str, int]:
        """Count every source in ``sources`` over the same window."""
        return {s: self.count(s, window_sec=window_sec) for s in sorted(sources)}


_RATE_LIMITS: RollingEventCounter | None = None
_RATE_LIMITS_LOCK = threading.Lock()


def default_rate_limit_counter() -> RollingEventCounter:
    """Process singleton used by adapters + monitor."""
    global _RATE_LIMITS
    with _RATE_LIMITS_LOCK:
        if _RATE_LIMITS is None:
            _RATE_LIMITS = RollingEventCounter()
        return _RATE_LIMITS


def reset_rate_limit_counter(
    counter: RollingEventCounter | None = None,
) -> RollingEventCounter:
    """Replace the singleton (tests)."""
    global _RATE_LIMITS
    with _RATE_LIMITS_LOCK:
        _RATE_LIMITS = counter if counter is not None else RollingEventCounter()
        return _RATE_LIMITS


def record_rate_limit(source: str) -> None:
    """Convenience: record one rate-limit event on the process counter."""
    default_rate_limit_counter().record(source)
