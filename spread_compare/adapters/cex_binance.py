"""Binance CEX adapter: spot + USDT-M perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.1. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import httpx

from spread_compare.adapters._cex_common import (
    CexBaseAdapter,
    CexBookSide,
    OrderbookLevels,
    parse_levels,
)
from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    AdapterTimeoutError,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.bookwalk import walk_book
from spread_compare.models import Side

logger = logging.getLogger(__name__)

_SPOT_BASE = "https://api.binance.com"
_FAPI_BASE = "https://fapi.binance.com"
# WHI-800: start limit=100 (weight 5); escalate only when walk exhausts depth.
# Tunables deferred to config YAML — see docs/DEFERRED_ISSUES.md (WHI-802).
_DEPTH_LIMITS: tuple[int, ...] = (100, 500, 1000)
_MAX_RETRIES = 4
_BACKOFF_START_S = 0.5


@register_adapter
class BinanceAdapter(CexBaseAdapter):
    """Binance spot + USDT-M futures depth walker."""

    venue: str = "binance"
    # Well under 6000 weight/min spot / 2400 fapi: ~5 rps with limit=100 (weight 5).
    _min_interval_s: float = 0.2

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

    async def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        delay = _BACKOFF_START_S
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await self._limiter.acquire()
            try:
                resp = await self.http.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"binance timeout: {url}") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"binance HTTP error: {exc}") from exc

            weight = resp.headers.get("x-mbx-used-weight-1m") or resp.headers.get(
                "x-mbx-used-weight"
            )
            if weight is not None:
                logger.info("binance x-mbx-used-weight-1m=%s url=%s", weight, url)

            if resp.status_code == 429:
                last_error = AdapterFetchError(
                    f"binance rate limited (429) attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"binance HTTP {resp.status_code}: {resp.text[:200]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise AdapterFetchError("binance response is not JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterFetchError(f"binance unexpected JSON type: {type(payload)}")
            return payload

        assert last_error is not None
        raise last_error
