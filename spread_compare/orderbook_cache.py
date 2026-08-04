"""Short-TTL orderbook snapshot cache (WHI-843).

Orderbook venues fetch the same book once and walk it at every notional tier.
The cache is keyed by venue + symbol + instrument_type + depth so a shallow
snapshot fetched for $100 is never reused to answer $1M.

Single-flight: concurrent callers for the same key share one upstream fetch.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TypeVar

from spread_compare.settings import load_orderbook_cache_settings

OrderbookLevels = list[tuple[Decimal, Decimal]]
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BookSnapshot:
    """One upstream orderbook snapshot with the depth it was fetched at."""

    bids: OrderbookLevels
    asks: OrderbookLevels
    depth: Hashable
    fetched_at_mono: float
    timestamp: datetime


def book_cache_key(
    venue: str,
    symbol: str,
    instrument_type: str,
    depth: Hashable,
) -> str:
    """Stable cache key. ``depth`` is the requested/returned limit (or token)."""
    return f"{venue}|{symbol}|{instrument_type}|{depth}"


class OrderbookSnapshotCache:
    """In-process short-TTL book cache with single-flight fetch coalescing."""

    def __init__(
        self,
        *,
        ttl_s: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if ttl_s is None:
            ttl_s = load_orderbook_cache_settings().ttl_sec
        if ttl_s < 0:
            raise ValueError(f"ttl_s must be >= 0, got {ttl_s}")
        self._ttl_s = ttl_s
        self._clock = clock or time.monotonic
        self._entries: dict[str, BookSnapshot] = {}
        self._inflight: dict[str, asyncio.Future[BookSnapshot]] = {}

    @property
    def ttl_s(self) -> float:
        return self._ttl_s

    def clear(self) -> None:
        """Drop all cached snapshots (in-flight work is left alone)."""
        self._entries.clear()

    def get_fresh(self, key: str) -> BookSnapshot | None:
        """Return a non-expired snapshot, or None."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        if self._clock() - entry.fetched_at_mono > self._ttl_s:
            return None
        return entry

    def put(
        self,
        key: str,
        *,
        bids: OrderbookLevels,
        asks: OrderbookLevels,
        depth: Hashable,
        timestamp: datetime | None = None,
    ) -> BookSnapshot:
        """Store a snapshot (also used by tests to seed depth-key fixtures)."""
        snap = BookSnapshot(
            bids=list(bids),
            asks=list(asks),
            depth=depth,
            fetched_at_mono=self._clock(),
            timestamp=timestamp or datetime.now(tz=UTC),
        )
        self._entries[key] = snap
        return snap

    async def get_or_fetch(
        self,
        key: str,
        fetch: Callable[[], Awaitable[tuple[OrderbookLevels, OrderbookLevels]]],
        *,
        depth: Hashable,
    ) -> BookSnapshot:
        """Return a fresh snapshot, coalescing concurrent fetches for ``key``."""
        hit = self.get_fresh(key)
        if hit is not None:
            return hit

        existing = self._inflight.get(key)
        if existing is not None:
            return await asyncio.shield(existing)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[BookSnapshot] = loop.create_future()
        self._inflight[key] = future

        try:
            bids, asks = await fetch()
            snap = self.put(key, bids=bids, asks=asks, depth=depth)
            if not future.done():
                future.set_result(snap)
            return snap
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
            raise
        finally:
            if self._inflight.get(key) is future:
                del self._inflight[key]


# Process-wide default cache shared by CEX/perp fetch paths.
_DEFAULT_CACHE = OrderbookSnapshotCache()


def default_orderbook_cache() -> OrderbookSnapshotCache:
    """Shared process-wide cache (tests may ``clear()`` between cases)."""
    return _DEFAULT_CACHE
