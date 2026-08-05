"""In-memory latest-quote store for pull-only venues (WHI-846).

Keyed by ``(venue, asset, instrument_type, notional_usd, side)``. Bounded by
construction (catalog × tiers × sides × venues); overwrite in place, no
eviction. **Never re-prices** stored quotes against a fresher mid — pairing
invariant is fixed at write time by the poller sweep.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from spread_compare.models import InstrumentType, Quote, Side


@dataclass(frozen=True, slots=True)
class QuoteStoreKey:
    """Lookup key for one stored leg."""

    venue: str
    asset: str
    instrument_type: InstrumentType
    notional_usd: Decimal
    side: Side

    def __str__(self) -> str:
        return (
            f"{self.venue}|{self.asset}|{self.instrument_type}|"
            f"{self.notional_usd}|{self.side}"
        )


@dataclass(slots=True)
class StoredQuote:
    """One store entry: quote frozen at observation time + metadata."""

    quote: Quote
    group: str
    observed_at: datetime
    observed_mono: float
    # Last successful *fresh sample* mono time. Failure paths that keep the
    # previous value leave this unchanged so max_stale_sec can expire them.
    last_success_mono: float


class QuoteStore:
    """Thread-safe latest-value map. Async callers share one process instance."""

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        import time

        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._entries: dict[QuoteStoreKey, StoredQuote] = {}

    def clear(self) -> None:
        """Drop all entries (tests)."""
        with self._lock:
            self._entries.clear()

    def put(
        self,
        key: QuoteStoreKey,
        quote: Quote,
        *,
        group: str,
        success: bool = True,
        observed_at: datetime | None = None,
    ) -> StoredQuote:
        """Insert or overwrite. ``success=False`` keeps last_success_mono from prior."""
        now_mono = self._clock()
        now_wall = observed_at or datetime.now(tz=UTC)
        with self._lock:
            prev = self._entries.get(key)
            if success:
                last_ok = now_mono
            elif prev is not None:
                last_ok = prev.last_success_mono
            else:
                last_ok = now_mono
            entry = StoredQuote(
                quote=quote,
                group=group,
                observed_at=now_wall,
                observed_mono=now_mono,
                last_success_mono=last_ok,
            )
            self._entries[key] = entry
            return entry

    def get(self, key: QuoteStoreKey) -> StoredQuote | None:
        with self._lock:
            return self._entries.get(key)

    def get_many(
        self, keys: Iterable[QuoteStoreKey]
    ) -> dict[QuoteStoreKey, StoredQuote]:
        with self._lock:
            return {k: self._entries[k] for k in keys if k in self._entries}

    def keys(self) -> list[QuoteStoreKey]:
        with self._lock:
            return list(self._entries.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# Process-wide store shared by poller (writer) and aggregator (reader).
_DEFAULT_STORE: QuoteStore | None = None
_DEFAULT_STORE_LOCK = threading.Lock()


def default_quote_store() -> QuoteStore:
    """Singleton store for the app process."""
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = QuoteStore()
        return _DEFAULT_STORE


def reset_default_quote_store() -> None:
    """Replace the singleton (tests)."""
    global _DEFAULT_STORE
    with _DEFAULT_STORE_LOCK:
        _DEFAULT_STORE = QuoteStore()
