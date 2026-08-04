"""Shared async rate limiters (WHI-836).

One module for all adapters — no per-module copies of ``AsyncRateLimiter``.
Limiters re-bind their lock when the running event loop changes so module-level
instances survive pytest-asyncio loop swaps and Starlette TestClient.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class _LoopBoundLock:
    """asyncio.Lock that rebinds when the running event loop changes.

    Module-level limiter instances must survive pytest-asyncio loop swaps and
    Starlette TestClient re-entry.
    """

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock


class AsyncRateLimiter(_LoopBoundLock):
    """Strict min-interval throttle (one request slot at a time per instance).

    Use when the upstream requires spacing between calls. For window-capacity
    budgets (e.g. Jupiter's burst of N per second), prefer
    :class:`TokenBucketRateLimiter`.
    """

    def __init__(self, min_interval_s: float) -> None:
        super().__init__()
        if min_interval_s < 0:
            raise ValueError("min_interval_s must be >= 0")
        self._min_interval_s = min_interval_s
        self._last_mono = 0.0

    async def acquire(self) -> None:
        async with self._get_lock():
            now = time.monotonic()
            wait = self._min_interval_s - (now - self._last_mono)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_mono = time.monotonic()


class TokenBucketRateLimiter(_LoopBoundLock):
    """Token-bucket throttle matching window-capacity rate contracts.

    Upstream limits advertised as ``N requests per window`` (e.g. Jupiter
    ``x-ratelimit-remaining`` + ``x-ratelimit-current``) allow a burst of ``N``
    back-to-back calls, then refill at ``N / window_s`` tokens per second.
    """

    def __init__(self, *, capacity: int, window_s: float) -> None:
        super().__init__()
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._capacity = float(capacity)
        # Ceiling for header adaptation — never exceed the configured plan.
        self._capacity_ceiling = float(capacity)
        self._window_s = window_s
        self._tokens = float(capacity)
        self._refill_per_s = float(capacity) / window_s
        self._last_refill_mono = time.monotonic()

    @property
    def capacity(self) -> int:
        return int(self._capacity)

    @property
    def window_s(self) -> float:
        return self._window_s

    def set_capacity(self, capacity: int) -> None:
        """Change bucket capacity (e.g. keyed → keyless downgrade).

        Does not grant extra tokens beyond the new capacity; clips current
        balance if it exceeds the new cap. Also lowers the adaptation ceiling.
        """
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = float(capacity)
        self._capacity_ceiling = float(capacity)
        self._refill_per_s = float(capacity) / self._window_s
        if self._tokens > self._capacity:
            self._tokens = self._capacity

    def observe_remaining(self, remaining: int) -> None:
        """Sync local tokens to an upstream ``x-ratelimit-remaining`` value.

        Clamps to ``[0, capacity]``. Does not invent capacity; use
        :meth:`observe_window` when both remaining and current are known.
        Accrued fractional refill is applied first so a mid-window observe
        does not discard progress toward the next token.
        """
        if remaining < 0:
            remaining = 0
        now = time.monotonic()
        self._refill(now)
        self._tokens = min(float(remaining), self._capacity)

    def observe_window(self, *, remaining: int, current: int) -> None:
        """Adapt capacity from ``remaining + current`` and sync token balance.

        Jupiter (and similar) expose ``x-ratelimit-remaining`` and
        ``x-ratelimit-current``; their sum is the window capacity. Capacity is
        never raised above the configured ceiling (keyed/keyless plan).
        """
        if remaining < 0:
            remaining = 0
        if current < 0:
            current = 0
        total = remaining + current
        now = time.monotonic()
        self._refill(now)
        if total >= 1:
            # Never exceed the plan ceiling from config; may tighten if headers
            # show a smaller window (e.g. plan downgrade / partial window).
            new_cap = min(float(total), self._capacity_ceiling)
            self._capacity = new_cap
            self._refill_per_s = new_cap / self._window_s
        self._tokens = min(float(remaining), self._capacity)

    def _refill(self, now: float) -> None:
        elapsed = now - self._last_refill_mono
        if elapsed <= 0:
            return
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_per_s)
        self._last_refill_mono = now

    async def acquire(self) -> None:
        async with self._get_lock():
            while True:
                now = time.monotonic()
                self._refill(now)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                # Time until one full token is available.
                deficit = 1.0 - self._tokens
                wait = deficit / self._refill_per_s if self._refill_per_s > 0 else self._window_s
                if wait > 0:
                    await asyncio.sleep(wait)


class RollingWindowRateLimiter(_LoopBoundLock):
    """Cap requests in a rolling wall-clock window (e.g. 60 req / 60s)."""

    def __init__(self, *, max_requests: int, window_s: float) -> None:
        super().__init__()
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self._max_requests = max_requests
        self._window_s = window_s
        self._timestamps: deque[float] = deque()

    @property
    def max_requests(self) -> int:
        return self._max_requests

    @property
    def window_s(self) -> float:
        return self._window_s

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_s
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()

    async def acquire(self) -> None:
        async with self._get_lock():
            while True:
                now = time.monotonic()
                self._prune(now)
                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return
                wait = self._timestamps[0] + self._window_s - now
                if wait > 0:
                    await asyncio.sleep(wait)
