"""Binance CEX adapter: spot + USDT-M perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.1. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.adapters._cex_common import (
    CexBaseAdapter,
    CexBookSide,
    OrderbookLevels,
    parse_levels,
)
from spread_compare.adapters.base import AdapterError, AdapterFetchError
from spread_compare.adapters.registry import register_adapter
from spread_compare.bookwalk import walk_book
from spread_compare.models import Side
from spread_compare.orderbook_cache import book_cache_key

_SPOT_BASE = "https://api.binance.com"
_FAPI_BASE = "https://fapi.binance.com"
# WHI-800: start limit=100 (weight 5); escalate only when walk exhausts depth.
# Tunables deferred to config YAML — see docs/DEFERRED_ISSUES.md (WHI-802).
_DEPTH_LIMITS: tuple[int, ...] = (100, 500, 1000)


@register_adapter
class BinanceAdapter(CexBaseAdapter):
    """Binance spot + USDT-M futures depth walker."""

    venue: str = "binance"
    # Well under 6000 weight/min spot / 2400 fapi: ~5 rps with limit=100 (weight 5).
    _min_interval_s: float = 0.2
    _retry_http_statuses: frozenset[int] = frozenset({429})
    _rate_limit_log_headers: tuple[str, ...] = (
        "x-mbx-used-weight-1m",
        "x-mbx-used-weight",
    )

    async def _fetch_book(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        side: Side | None = None,
        q_star: Decimal | None = None,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        if side is not None and q_star is not None:
            return await self._fetch_depth_escalating(symbol, book_side, side, q_star)
        return await self._fetch_depth(symbol, book_side, limit=_DEPTH_LIMITS[0])

    async def _fetch_depth_escalating(
        self,
        symbol: str,
        book_side: CexBookSide,
        side: Side,
        q_star: Decimal,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        # Prefer a deeper cached book that already fills q_star (WHI-843 depth key).
        for limit in reversed(_DEPTH_LIMITS):
            key = book_cache_key(self.venue, symbol, book_side, limit)
            hit = self._book_cache.get_fresh(key)
            if hit is None:
                continue
            levels = hit.asks if side == "buy" else hit.bids
            if walk_book(levels, q_star) is not None:
                return hit.bids, hit.asks

        last: tuple[OrderbookLevels, OrderbookLevels] | None = None
        for limit in _DEPTH_LIMITS:
            bids, asks = await self._fetch_depth(symbol, book_side, limit=limit)
            last = (bids, asks)
            levels = asks if side == "buy" else bids
            if walk_book(levels, q_star) is not None:
                return bids, asks
        assert last is not None
        return last

    async def _fetch_depth(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        limit: int,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        async def _raw() -> tuple[OrderbookLevels, OrderbookLevels]:
            if book_side == "spot":
                url = f"{_SPOT_BASE}/api/v3/depth"
            else:
                url = f"{_FAPI_BASE}/fapi/v1/depth"
            params = {"symbol": symbol, "limit": str(limit)}
            data = await self._request_json(url, params)
            try:
                bids = parse_levels(data["bids"])
                asks = parse_levels(data["asks"])
            except (KeyError, TypeError, AdapterError) as exc:
                raise AdapterFetchError(f"binance depth parse failed: {exc}") from exc
            return bids, asks

        # Depth is part of the cache key — a limit=100 book never answers limit=1000.
        snap = await self._cached_depth_fetch(
            symbol, book_side, depth=limit, fetch=_raw
        )
        return snap.bids, snap.asks
