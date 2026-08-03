"""Binance CEX adapter: spot + USDT-M perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.1. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, Literal

import httpx

from spread_compare.adapters._cex_common import (
    DEFAULT_FEE_TIER,
    PLACEHOLDER_TAKER_BPS,
    AsyncRateLimiter,
    OrderbookLevels,
    build_quote_from_book,
    build_top_of_book,
    build_unsupported_quote,
    parse_levels,
    placeholder_fee_schedule,
    resolve_cex_instrument,
)
from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    AdapterTimeoutError,
    BaseAdapter,
    UnsupportedAssetError,
    default_instrument_type,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.bookwalk import walk_book
from spread_compare.cex_symbols import resolve_cex_symbol, supported_cex_assets
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)

logger = logging.getLogger(__name__)

_SPOT_BASE = "https://api.binance.com"
_FAPI_BASE = "https://fapi.binance.com"
# WHI-800: start limit=100 (weight 5); escalate only when walk exhausts depth.
_DEPTH_LIMITS: tuple[int, ...] = (100, 500, 1000)
# Well under 6000 weight/min spot / 2400 fapi: ~5 rps with limit=100 (weight 5).
_MIN_INTERVAL_S = 0.2
_MAX_RETRIES = 4
_BACKOFF_START_S = 0.5


@register_adapter
class BinanceAdapter(BaseAdapter):
    """Binance spot + USDT-M futures depth walker."""

    venue: str = "binance"
    venue_class: VenueClass = "cex"

    def __init__(self, *, timeout: float = 10.0) -> None:
        super().__init__(timeout=timeout)
        self._limiter = AsyncRateLimiter(_MIN_INTERVAL_S)

    async def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
    ) -> Quote:
        itype_default = instrument_type or default_instrument_type(self.venue_class)
        asset_key = asset.upper()
        tier = fee_tier or DEFAULT_FEE_TIER

        if mid.asset.upper() != asset_key:
            raise AdapterError(
                f"mid.asset={mid.asset!r} does not match asset={asset!r}"
            )

        try:
            book_side = resolve_cex_instrument(itype_default)
        except AdapterError as exc:
            return build_unsupported_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=itype_default,
                message=str(exc),
                fee_tier=tier,
            )

        symbol = resolve_cex_symbol(asset_key)
        if symbol is None:
            return build_unsupported_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=book_side,
                message=f"{asset} not supported by binance adapter",
                fee_tier=tier,
            )

        bids, asks = await self._fetch_depth_for_walk(
            symbol, book_side, side=side, notional_usd=notional_usd, mid=mid
        )
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=book_side,
            venue_symbol=symbol,
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=PLACEHOLDER_TAKER_BPS,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        asset_key = asset.upper()
        symbol = resolve_cex_symbol(asset_key)
        if symbol is None:
            raise UnsupportedAssetError(f"{asset} not supported by binance")
        book_side: Literal["spot", "perp"] = instrument_type or "spot"
        bids, asks = await self._fetch_depth(symbol, book_side, limit=_DEPTH_LIMITS[0])
        return build_top_of_book(
            venue=self.venue,
            asset=asset_key,
            instrument_type=book_side,
            mid=mid,
            bids=bids,
            asks=asks,
        )

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        itype = instrument_type or default_instrument_type(self.venue_class)
        return placeholder_fee_schedule(
            venue=self.venue,
            asset=asset.upper() if asset else None,
            instrument_type=itype,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        return supported_cex_assets()

    async def _fetch_depth_for_walk(
        self,
        symbol: str,
        book_side: Literal["spot", "perp"],
        *,
        side: Side,
        notional_usd: Decimal,
        mid: ReferenceMid,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        """Fetch depth, escalating limit when the walked side exhausts."""
        q_star = notional_usd / mid.mid
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
        book_side: Literal["spot", "perp"],
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
