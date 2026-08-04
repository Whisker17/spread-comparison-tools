"""Per-call quote budget / deadline (WHI-844).

``quote_with_timeout`` (and the simulator) set a monotonic deadline while an
adapter call is in flight. Limiters and 429 backoff paths consult
:func:`remaining_budget_s` so they can fail fast with ``rate_limited`` instead
of sleeping past the aggregator's timeout and being reported as ``timeout``.

No deadline means unlimited (direct adapter tests, startup probes).
"""

from __future__ import annotations

import asyncio
import contextvars
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from spread_compare.adapters.base import AdapterRateLimitedError
from spread_compare.ratelimit import RateLimitWaitExceeded


class _Limiter(Protocol):
    async def acquire(self, *, max_wait_s: float | None = None) -> None: ...


_deadline_mono: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "quote_deadline_mono", default=None
)


@contextmanager
def quote_deadline(timeout_s: float) -> Iterator[None]:
    """Bind a monotonic deadline for the current task/context."""
    if timeout_s < 0:
        raise ValueError("timeout_s must be >= 0")
    token = _deadline_mono.set(time.monotonic() + timeout_s)
    try:
        yield
    finally:
        _deadline_mono.reset(token)


def remaining_budget_s() -> float | None:
    """Seconds left under the active quote deadline, or ``None`` if unbound."""
    deadline = _deadline_mono.get()
    if deadline is None:
        return None
    return max(0.0, deadline - time.monotonic())


def would_exceed_budget(wait_s: float) -> bool:
    """True when sleeping ``wait_s`` would overrun the active quote deadline."""
    remaining = remaining_budget_s()
    if remaining is None:
        return False
    return wait_s > remaining


async def acquire_within_budget(limiter: _Limiter, *, venue: str) -> None:
    """Acquire a limiter slot, or raise :class:`AdapterRateLimitedError`.

    Short waits that fit the budget still sleep. When no deadline is bound,
    ``max_wait_s`` is unlimited (same as a plain ``acquire()``).
    """
    remaining = remaining_budget_s()
    try:
        await limiter.acquire(max_wait_s=remaining)
    except RateLimitWaitExceeded as exc:
        raise AdapterRateLimitedError(
            f"{venue}: rate limiter wait {exc.wait_s:.2f}s exceeds remaining "
            f"budget {exc.max_wait_s:.2f}s",
            retry_after_s=exc.wait_s,
        ) from exc


async def sleep_within_budget(
    wait_s: float,
    *,
    venue: str,
    reason: str = "rate limited",
) -> None:
    """Sleep ``wait_s``, or fail fast when it would exceed the quote budget.

    Used for upstream 429 / Retry-After backoffs (not for non-rate-limit 5xx).
    """
    if wait_s <= 0:
        return
    if would_exceed_budget(wait_s):
        raise AdapterRateLimitedError(
            f"{venue}: {reason}; retry_after={wait_s:.2f}s exceeds remaining "
            f"quote budget",
            retry_after_s=wait_s,
        )
    await asyncio.sleep(wait_s)
