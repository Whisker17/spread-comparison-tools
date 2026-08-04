"""Unit tests for shared rate limiters (WHI-836)."""

from __future__ import annotations

import asyncio
import time

import pytest

from spread_compare.ratelimit import (
    AsyncRateLimiter,
    RollingWindowRateLimiter,
    TokenBucketRateLimiter,
)


@pytest.mark.asyncio
async def test_token_bucket_keyed_capacity_bursts_then_waits() -> None:
    """Capacity 10: ten acquisitions ≈0s; the eleventh waits for refill."""
    limiter = TokenBucketRateLimiter(capacity=10, window_s=1.0)
    t0 = time.monotonic()
    for _ in range(10):
        await limiter.acquire()
    burst_elapsed = time.monotonic() - t0
    assert burst_elapsed < 0.15, f"burst of 10 took {burst_elapsed:.3f}s"

    t1 = time.monotonic()
    await limiter.acquire()
    wait_elapsed = time.monotonic() - t1
    # Refill rate = 10/s → one token needs ~0.1s.
    assert wait_elapsed >= 0.08, f"11th acquire waited only {wait_elapsed:.3f}s"
    assert wait_elapsed < 0.5


@pytest.mark.asyncio
async def test_token_bucket_keyless_capacity_sixth_waits() -> None:
    """Capacity 5 (keyless): five free, sixth waits."""
    limiter = TokenBucketRateLimiter(capacity=5, window_s=1.0)
    t0 = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    assert time.monotonic() - t0 < 0.15

    t1 = time.monotonic()
    await limiter.acquire()
    wait_elapsed = time.monotonic() - t1
    # Refill rate = 5/s → one token needs ~0.2s.
    assert wait_elapsed >= 0.15, f"6th acquire waited only {wait_elapsed:.3f}s"
    assert wait_elapsed < 0.6


@pytest.mark.asyncio
async def test_token_bucket_concurrent_burst_fits_capacity() -> None:
    """Six concurrent acquires with capacity 10 finish near-instantly."""
    limiter = TokenBucketRateLimiter(capacity=10, window_s=1.0)
    t0 = time.monotonic()
    got: list[float] = []

    async def call() -> None:
        await limiter.acquire()
        got.append(time.monotonic() - t0)

    await asyncio.gather(*(call() for _ in range(6)))
    assert len(got) == 6
    assert max(got) < 0.15
    # All six within a 3s venue budget (the failure mode WHI-836 fixes).
    assert all(t < 3.0 for t in got)


@pytest.mark.asyncio
async def test_token_bucket_observe_window_adapts_capacity() -> None:
    limiter = TokenBucketRateLimiter(capacity=10, window_s=1.0)
    # Drain fully.
    for _ in range(10):
        await limiter.acquire()
    # Upstream says remaining=2, current=3 → capacity 5, tokens=2.
    limiter.observe_window(remaining=2, current=3)
    assert limiter.capacity == 5
    t0 = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    assert time.monotonic() - t0 < 0.15
    t1 = time.monotonic()
    await limiter.acquire()
    assert time.monotonic() - t1 >= 0.15


@pytest.mark.asyncio
async def test_async_rate_limiter_min_interval() -> None:
    limiter = AsyncRateLimiter(0.05)
    t0 = time.monotonic()
    await limiter.acquire()
    await limiter.acquire()
    assert time.monotonic() - t0 >= 0.045


@pytest.mark.asyncio
async def test_rolling_window_rate_limiter_caps_burst() -> None:
    limiter = RollingWindowRateLimiter(max_requests=3, window_s=0.4)
    t0 = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.35


def test_token_bucket_rejects_invalid_args() -> None:
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=0, window_s=1.0)
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(capacity=1, window_s=0.0)
