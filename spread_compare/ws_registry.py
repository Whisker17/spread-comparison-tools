"""Process-wide registry of local order books (WHI-847).

Adapters read servable books here; WS feed tasks write them. Keys are
``(venue, symbol, instrument_type)`` so spot/perp never collide.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import Decimal

from spread_compare.bookwalk import OrderbookLevels
from spread_compare.local_book import BookHealth, LocalOrderBook

BookKey = tuple[str, str, str]  # venue, symbol, instrument_type


@dataclass(frozen=True, slots=True)
class ServableBook:
    """Snapshot of levels safe to walk for a quote."""

    bids: OrderbookLevels
    asks: OrderbookLevels
    age_sec: float
    updated_at: object  # datetime | None
    last_update_id: int | None
    health: BookHealth


class WsBookRegistry:
    """Map of local books + connection accounting for multiplex tests."""

    def __init__(self, *, max_book_age_sec: float = 5.0) -> None:
        self._max_book_age_sec = max_book_age_sec
        self._books: dict[BookKey, LocalOrderBook] = {}
        self._lock = threading.RLock()
        # stream_id → open connection count (normally 0 or 1).
        self._connections: dict[str, int] = {}

    @property
    def max_book_age_sec(self) -> float:
        return self._max_book_age_sec

    def set_max_book_age_sec(self, value: float) -> None:
        self._max_book_age_sec = value

    def get_or_create(
        self,
        venue: str,
        symbol: str,
        instrument_type: str,
    ) -> LocalOrderBook:
        key = (venue, symbol.upper(), instrument_type)
        with self._lock:
            book = self._books.get(key)
            if book is None:
                book = LocalOrderBook(
                    venue=venue,
                    symbol=symbol.upper(),
                    instrument_type=instrument_type,
                )
                self._books[key] = book
            return book

    def get(
        self,
        venue: str,
        symbol: str,
        instrument_type: str,
    ) -> LocalOrderBook | None:
        key = (venue, symbol.upper(), instrument_type)
        with self._lock:
            return self._books.get(key)

    def get_servable(
        self,
        venue: str,
        symbol: str,
        instrument_type: str,
        *,
        max_age_sec: float | None = None,
    ) -> ServableBook | None:
        book = self.get(venue, symbol, instrument_type)
        if book is None:
            return None
        age_limit = self._max_book_age_sec if max_age_sec is None else max_age_sec
        if not book.is_servable(max_age_sec=age_limit):
            return None
        bids, asks = book.levels()
        age = book.age_sec()
        if age is None:
            return None
        return ServableBook(
            bids=bids,
            asks=asks,
            age_sec=age,
            updated_at=book.updated_at,
            last_update_id=book.last_update_id,
            health=book.health,
        )

    def put_fixture_book(
        self,
        venue: str,
        symbol: str,
        instrument_type: str,
        bids: OrderbookLevels,
        asks: OrderbookLevels,
        *,
        update_id: int | None = 1,
        health: BookHealth = BookHealth.HEALTHY,
    ) -> LocalOrderBook:
        """Test helper: inject a healthy book without a WS connection."""
        book = self.get_or_create(venue, symbol, instrument_type)
        book.apply_snapshot(bids, asks, update_id=update_id, health=health)
        return book

    def mark_connection(self, stream_id: str, *, open: bool) -> None:
        with self._lock:
            cur = self._connections.get(stream_id, 0)
            if open:
                self._connections[stream_id] = cur + 1
            else:
                self._connections[stream_id] = max(0, cur - 1)

    def connection_count(self, stream_id: str) -> int:
        with self._lock:
            return self._connections.get(stream_id, 0)

    def total_connections(self) -> int:
        with self._lock:
            return sum(self._connections.values())

    def clear(self) -> None:
        with self._lock:
            self._books.clear()
            self._connections.clear()

    def book_count(self) -> int:
        with self._lock:
            return len(self._books)


_REGISTRY: WsBookRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def default_ws_registry() -> WsBookRegistry:
    """Process singleton; tests may :meth:`WsBookRegistry.clear` between cases."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        if _REGISTRY is None:
            _REGISTRY = WsBookRegistry()
        return _REGISTRY


def reset_ws_registry(registry: WsBookRegistry | None = None) -> WsBookRegistry:
    """Replace the process singleton (tests)."""
    global _REGISTRY
    with _REGISTRY_LOCK:
        _REGISTRY = registry if registry is not None else WsBookRegistry()
        return _REGISTRY


def depth_notional_usd(
    levels: OrderbookLevels,
    *,
    mid: Decimal,
    side: str,
) -> Decimal:
    """Rough notional capacity of a side at mid (for depth tests / logging)."""
    _ = side
    total = Decimal("0")
    for price, size in levels:
        total += price * size
    return total
