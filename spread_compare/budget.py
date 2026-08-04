"""Per-call quote budget / deadline (WHI-844).

``quote_with_timeout`` (and the simulator) set a monotonic deadline while an
adapter call is in flight. Limiters and 429 backoff paths consult
:func:`remaining_budget_s` so they can fail fast with ``rate_limited`` instead
of sleeping past the aggregator's timeout and being reported as ``timeout``.

No deadline means unlimited (direct adapter tests, startup probes).
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Iterator
from contextlib import contextmanager

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
