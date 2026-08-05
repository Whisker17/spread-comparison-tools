"""In-memory order book for WebSocket ingest (WHI-847).

Levels are absolute quantities (qty 0 deletes). Walk math stays in
:mod:`spread_compare.bookwalk` — this module only stores and sequences.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from threading import RLock
from typing import Literal

from spread_compare.bookwalk import OrderbookLevels

BookSideName = Literal["bid", "ask"]


class BookHealth(StrEnum):
    """Per-symbol local book lifecycle (WHI-847).

    Staleness-by-age is enforced at serve time (``max_book_age_sec``), not as a
    separate health enum value — a book that was healthy and then aged out still
    reports HEALTHY so the age gate can emit ``book_stale`` (not REST fallback).
    """

    CONNECTING = "connecting"
    SYNCING = "syncing"
    HEALTHY = "healthy"
    RESYNCING = "resyncing"
    DISCONNECTED = "disconnected"


# States that may be served (freshness is checked separately).
_SERVABLE = frozenset({BookHealth.HEALTHY})


@dataclass
class LocalOrderBook:
    """Thread-safe price→size maps for one venue symbol.

    Bids and asks are stored as absolute sizes. Callers pass best-first lists
    out via :meth:`levels`. Sequence fields are venue-specific (update ids,
    nonces) and interpreted by the protocol handlers, not this class.
    """

    venue: str
    symbol: str
    instrument_type: str
    health: BookHealth = BookHealth.CONNECTING
    last_update_id: int | None = None
    # Optional second sequence (e.g. Bybit seq, Lighter nonce).
    last_seq: int | None = None
    updated_at: datetime | None = None
    updated_mono: float | None = None
    error_message: str | None = None
    _bids: dict[Decimal, Decimal] = field(default_factory=dict)
    _asks: dict[Decimal, Decimal] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, repr=False, compare=False)
    _clock: object = field(default=time.monotonic, repr=False, compare=False)

    def set_health(self, health: BookHealth, *, error: str | None = None) -> None:
        with self._lock:
            self.health = health
            if error is not None:
                self.error_message = error
            elif health is BookHealth.HEALTHY:
                self.error_message = None

    def clear_levels(self) -> None:
        with self._lock:
            self._bids.clear()
            self._asks.clear()

    def apply_snapshot(
        self,
        bids: OrderbookLevels,
        asks: OrderbookLevels,
        *,
        update_id: int | None = None,
        seq: int | None = None,
        health: BookHealth = BookHealth.HEALTHY,
        timestamp: datetime | None = None,
    ) -> None:
        """Replace the whole book (REST resync or venue snapshot frame)."""
        with self._lock:
            self._bids = {px: sz for px, sz in bids if sz > 0}
            self._asks = {px: sz for px, sz in asks if sz > 0}
            if update_id is not None:
                self.last_update_id = update_id
            if seq is not None:
                self.last_seq = seq
            self.health = health
            self.error_message = None
            self._touch(timestamp)

    def apply_level(
        self,
        side: BookSideName,
        price: Decimal,
        size: Decimal,
    ) -> None:
        """Absolute qty update; size 0 deletes the level."""
        with self._lock:
            book = self._bids if side == "bid" else self._asks
            if size == 0:
                book.pop(price, None)
            elif size > 0:
                book[price] = size
            else:
                raise ValueError(f"negative level size: {size}")

    def apply_levels(
        self,
        *,
        bids: OrderbookLevels | None = None,
        asks: OrderbookLevels | None = None,
        update_id: int | None = None,
        seq: int | None = None,
        timestamp: datetime | None = None,
        mark_healthy: bool = True,
    ) -> None:
        """Apply absolute bid/ask deltas then optionally advance sequence."""
        with self._lock:
            if bids is not None:
                for px, sz in bids:
                    if sz == 0:
                        self._bids.pop(px, None)
                    elif sz > 0:
                        self._bids[px] = sz
                    else:
                        raise ValueError(f"negative bid size: {sz}")
            if asks is not None:
                for px, sz in asks:
                    if sz == 0:
                        self._asks.pop(px, None)
                    elif sz > 0:
                        self._asks[px] = sz
                    else:
                        raise ValueError(f"negative ask size: {sz}")
            if update_id is not None:
                self.last_update_id = update_id
            if seq is not None:
                self.last_seq = seq
            if mark_healthy:
                self.health = BookHealth.HEALTHY
                self.error_message = None
            self._touch(timestamp)

    def levels(self) -> tuple[OrderbookLevels, OrderbookLevels]:
        """Return ``(bids, asks)`` best-first copies."""
        with self._lock:
            bids = sorted(self._bids.items(), key=lambda x: x[0], reverse=True)
            asks = sorted(self._asks.items(), key=lambda x: x[0])
            return list(bids), list(asks)

    def age_sec(self, *, now_mono: float | None = None) -> float | None:
        with self._lock:
            if self.updated_mono is None:
                return None
            clock = now_mono if now_mono is not None else float(self._clock())  # type: ignore[operator]
            return max(0.0, clock - self.updated_mono)

    def is_servable(self, *, max_age_sec: float, now_mono: float | None = None) -> bool:
        """True when healthy and younger than ``max_age_sec``."""
        with self._lock:
            if self.health not in _SERVABLE:
                return False
            age = self.age_sec(now_mono=now_mono)
            if age is None:
                return False
            return age <= max_age_sec

    def snapshot_meta(self) -> dict[str, object]:
        with self._lock:
            return {
                "venue": self.venue,
                "symbol": self.symbol,
                "instrument_type": self.instrument_type,
                "health": self.health.value,
                "last_update_id": self.last_update_id,
                "last_seq": self.last_seq,
                "updated_at": self.updated_at,
                "bid_levels": len(self._bids),
                "ask_levels": len(self._asks),
            }

    def _touch(self, timestamp: datetime | None) -> None:
        self.updated_at = timestamp or datetime.now(tz=UTC)
        self.updated_mono = float(self._clock())  # type: ignore[operator]
