"""Bybit CEX adapter: spot + linear perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.2. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
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

_BASE = "https://api.bybit.com"
# WHI-802: default limit=200 (covers $1k…$1M blue-chip walks for Phase 1).
_ORDERBOOK_LIMIT = 200
# Well under Bybit IP 600 req / 5s (~120 rps): ~10 rps.
_MIN_INTERVAL_S = 0.1
_MAX_RETRIES = 4
_BACKOFF_START_S = 0.5


@register_adapter
class BybitAdapter(BaseAdapter):
    """Bybit spot + linear perpetual orderbook walker."""

    venue: str = "bybit"
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
                message=f"{asset} not supported by bybit adapter",
                fee_tier=tier,
            )

        bids, asks = await self._fetch_orderbook(symbol, book_side)
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
            raise UnsupportedAssetError(f"{asset} not supported by bybit")
        book_side: Literal["spot", "perp"] = instrument_type or "spot"
        bids, asks = await self._fetch_orderbook(symbol, book_side)
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

    async def _fetch_orderbook(
        self,
        symbol: str,
        book_side: Literal["spot", "perp"],
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        category = "spot" if book_side == "spot" else "linear"
        url = f"{_BASE}/v5/market/orderbook"
        params = {
            "category": category,
            "symbol": symbol,
            "limit": str(_ORDERBOOK_LIMIT),
        }
        data = await self._request_json(url, params)
        try:
            result = data["result"]
            # Bybit: result.a = asks, result.b = bids as [px, sz] string arrays.
            asks = parse_levels(result["a"])
            bids = parse_levels(result["b"])
        except (KeyError, TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"bybit orderbook parse failed: {exc}") from exc
        return bids, asks

    async def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        delay = _BACKOFF_START_S
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await self._limiter.acquire()
            try:
                resp = await self.http.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"bybit timeout: {url}") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"bybit HTTP error: {exc}") from exc

            limit_status = resp.headers.get("X-Bapi-Limit-Status") or resp.headers.get(
                "x-bapi-limit-status"
            )
            if limit_status is not None:
                logger.info(
                    "bybit X-Bapi-Limit-Status=%s url=%s", limit_status, url
                )

            # IP throttle often returns 403; UID market-data may use retCode 10006.
            if resp.status_code in (403, 429):
                last_error = AdapterFetchError(
                    f"bybit rate limited (HTTP {resp.status_code}) attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"bybit HTTP {resp.status_code}: {resp.text[:200]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise AdapterFetchError("bybit response is not JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterFetchError(f"bybit unexpected JSON type: {type(payload)}")

            ret_code = payload.get("retCode")
            if ret_code == 10006:
                last_error = AdapterFetchError(
                    f"bybit retCode=10006 (too many visits) attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if ret_code not in (0, None):
                raise AdapterFetchError(
                    f"bybit retCode={ret_code} retMsg={payload.get('retMsg')!r}"
                )
            return payload

        assert last_error is not None
        raise last_error
