"""Serve quotes from the local WS book registry (WHI-847).

Adapters call :func:`try_local_book` before REST. Age and mid freshness gates
live here so every venue shares one policy.
"""

from __future__ import annotations

from datetime import UTC, datetime

from spread_compare.local_book import BookHealth
from spread_compare.mids import is_mid_stale
from spread_compare.models import ReferenceMid
from spread_compare.settings import MidSettings, WsSettings, load_mid_settings, load_ws_settings
from spread_compare.ws_registry import ServableBook, WsBookRegistry, default_ws_registry


class LocalBookUnavailable(Exception):
    """Local book cannot be served; caller should fall back to REST or error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def try_local_book(
    venue: str,
    symbol: str,
    instrument_type: str,
    *,
    registry: WsBookRegistry | None = None,
    ws_settings: WsSettings | None = None,
) -> ServableBook | None:
    """Return a servable local book, or ``None`` to fall back to REST.

    When the book exists but is **too old** while WS is supposed to be active,
    raises :class:`LocalBookUnavailable` so the adapter can emit ``status=error``
    instead of a stale price (WHI-847 AC).
    """
    reg = registry if registry is not None else default_ws_registry()
    settings = ws_settings if ws_settings is not None else load_ws_settings()

    book = reg.get(venue, symbol, instrument_type)
    if book is None:
        return None

    # Healthy + fresh → serve.
    servable = reg.get_servable(
        venue, symbol, instrument_type, max_age_sec=settings.max_book_age_sec
    )
    if servable is not None:
        return servable

    # Book known but past max age while not simply disconnected → error, not REST
    # stale-serve of an old local book. REST is allowed when health is disconnected
    # / connecting (WS never synced).
    age = book.age_sec()
    if (
        book.health is BookHealth.HEALTHY
        and age is not None
        and age > settings.max_book_age_sec
    ):
        raise LocalBookUnavailable(
            "book_stale",
            f"{venue} {symbol} local book age_sec={age:.2f} > max={settings.max_book_age_sec}",
        )

    # resyncing / syncing / connecting / disconnected → REST fallback
    return None


def stamp_ws_quote_fields(
    *,
    mid: ReferenceMid,
    book_age_sec: float,
    quote_timestamp: datetime | None = None,
    mid_settings: MidSettings | None = None,
) -> dict[str, object]:
    """Extra Quote fields for WS-served rows (age + tighter mid_stale).

    Sets ``raw_ref=\"ws_book\"`` so the aggregator can apply
    ``max_age_for_ws_quote_sec`` without colliding with WHI-846 store rows that
    also carry ``age_sec``.
    """
    settings = mid_settings if mid_settings is not None else load_mid_settings()
    now = quote_timestamp or datetime.now(tz=UTC)
    # Tighter gate for WS books (default 2s); still the §3.2 abs(delta) rule.
    mid_stale = is_mid_stale(
        now,
        mid.timestamp,
        stale_threshold_sec=settings.max_age_for_ws_quote_sec,
    )
    return {
        "age_sec": book_age_sec,
        "mid_stale": mid_stale,
        # quote_stale stays False for live path unless we later wire best-age.
        "quote_stale": False,
        "raw_ref": "ws_book",
    }
