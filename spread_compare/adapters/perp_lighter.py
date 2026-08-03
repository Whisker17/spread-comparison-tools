"""Lighter perp adapter: per-order book → aggregate → walk → Quote (WHI-803).

Endpoints: WHI-800 §4.2. Standard tier is 60 requests / rolling minute — enforced
client-side via :class:`RollingWindowRateLimiter`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

import httpx

from spread_compare.adapters._perp_common import (
    DEFAULT_FEE_TIER,
    PLACEHOLDER_TAKER_BPS,
    OrderbookLevels,
    RollingWindowRateLimiter,
    aggregate_orders_by_price,
    build_quote_from_book,
    build_top_of_book,
    build_unsupported_quote,
    placeholder_fee_schedule,
    resolve_perp_instrument,
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

_BASE = "https://mainnet.zklighter.elliot.ai"
_DETAILS_PATH = "/api/v1/orderBookDetails"
_ORDERS_PATH = "/api/v1/orderBookOrders"
# Standard tier: 60 req / rolling minute (WHI-800 §4.2). 429/405 on breach.
_DEFAULT_MAX_RPM = 60
_DEFAULT_WINDOW_S = 60.0
_ORDER_LIMIT = 100
_BLUE_CHIPS: tuple[str, ...] = ("BTC", "ETH", "SOL")
_MAX_RETRIES = 4
_BACKOFF_START_S = 0.5

# Offline / startup-failure fallback only (WHI-800 live 2026-08-03 snapshot).
# Prefer the orderBookDetails table whenever network warm-up succeeds.
_FALLBACK_MARKET_IDS: dict[str, int] = {
    "ETH": 0,
    "BTC": 1,
    "SOL": 2,
}


@dataclass(frozen=True, slots=True)
class _MarketMeta:
    market_id: int
    symbol: str
    mark_price: Decimal | None
    index_price: Decimal | None


@register_adapter
class LighterAdapter(BaseAdapter):
    """Lighter perpetual order-book walker (per-order rows aggregated by price)."""

    venue: str = "lighter"
    venue_class: VenueClass = "perp_dex"

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_requests_per_minute: int = _DEFAULT_MAX_RPM,
        rate_window_s: float = _DEFAULT_WINDOW_S,
    ) -> None:
        super().__init__(timeout=timeout)
        self._limiter = RollingWindowRateLimiter(
            max_requests=max_requests_per_minute,
            window_s=rate_window_s,
        )
        self._markets_by_symbol: dict[str, _MarketMeta] = {}

    async def startup(self) -> None:
        if self._started:
            return
        # Resolve market_id from live orderBookDetails when possible; fall back
        # to the documented blue-chip snapshot so offline startup_all() works.
        try:
            await self._load_markets()
        except Exception as exc:
            logger.warning(
                "lighter orderBookDetails failed; using blue-chip market_id "
                "fallback: %s",
                exc,
            )
            self._seed_fallback_markets()
        if not self._markets_by_symbol:
            self._seed_fallback_markets()
        await super().startup()

    def _seed_fallback_markets(self) -> None:
        self._markets_by_symbol = {
            sym: _MarketMeta(
                market_id=mid,
                symbol=sym,
                mark_price=None,
                index_price=None,
            )
            for sym, mid in _FALLBACK_MARKET_IDS.items()
        }

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
            itype = resolve_perp_instrument(itype_default)
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

        meta = self._markets_by_symbol.get(asset_key)
        if meta is None:
            return build_unsupported_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=itype,
                message=f"{asset} not in lighter market table (run startup)",
                fee_tier=tier,
            )

        bids, asks = await self._fetch_orders(meta.market_id)
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=itype,
            venue_symbol=str(meta.market_id),
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=PLACEHOLDER_TAKER_BPS,
            funding_rate_8h=None,  # not exposed on orderBookDetails (Phase 1)
            venue_mark=meta.mark_price,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        asset_key = asset.upper()
        if instrument_type not in (None, "perp"):
            raise UnsupportedAssetError(
                f"lighter adapter only supports perp, got {instrument_type!r}"
            )
        meta = self._markets_by_symbol.get(asset_key)
        if meta is None:
            raise UnsupportedAssetError(f"{asset} not supported by lighter")
        bids, asks = await self._fetch_orders(meta.market_id)
        return build_top_of_book(
            venue=self.venue,
            asset=asset_key,
            mid=mid,
            bids=bids,
            asks=asks,
            instrument_type="perp",
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
        if self._markets_by_symbol:
            blue = [c for c in _BLUE_CHIPS if c in self._markets_by_symbol]
            rest = sorted(s for s in self._markets_by_symbol if s not in _BLUE_CHIPS)
            return blue + rest
        return list(_BLUE_CHIPS)

    def market_id_for(self, asset: str) -> int | None:
        """Return cached ``market_id`` for ``asset`` (tests / debugging)."""
        meta = self._markets_by_symbol.get(asset.upper())
        return None if meta is None else meta.market_id

    async def _load_markets(self) -> None:
        payload = await self._request_json("GET", f"{_BASE}{_DETAILS_PATH}")
        try:
            details = payload.get("order_book_details")
            if not isinstance(details, list):
                raise AdapterFetchError(
                    "lighter orderBookDetails missing order_book_details list"
                )
            markets: dict[str, _MarketMeta] = {}
            for row in details:
                if not isinstance(row, dict):
                    continue
                symbol = str(row["symbol"]).upper()
                market_id = int(row["market_id"])
                mark = (
                    Decimal(str(row["mark_price"]))
                    if row.get("mark_price") is not None
                    else None
                )
                index = (
                    Decimal(str(row["index_price"]))
                    if row.get("index_price") is not None
                    else None
                )
                # Prefer first active-looking row; later duplicates ignored.
                if symbol in markets:
                    continue
                markets[symbol] = _MarketMeta(
                    market_id=market_id,
                    symbol=symbol,
                    mark_price=mark,
                    index_price=index,
                )
            if not markets:
                raise AdapterFetchError("lighter orderBookDetails returned no markets")
            self._markets_by_symbol = markets
        except (KeyError, TypeError, ValueError, ArithmeticError, AdapterError) as exc:
            raise AdapterFetchError(f"lighter market table parse failed: {exc}") from exc

    async def _fetch_orders(
        self, market_id: int
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        url = f"{_BASE}{_ORDERS_PATH}"
        params = {"market_id": str(market_id), "limit": str(_ORDER_LIMIT)}
        payload = await self._request_json("GET", url, params=params)
        try:
            raw_asks = payload.get("asks") or []
            raw_bids = payload.get("bids") or []
            if not isinstance(raw_asks, list) or not isinstance(raw_bids, list):
                raise AdapterFetchError("lighter orderBookOrders asks/bids not lists")
            asks = aggregate_orders_by_price(
                [o for o in raw_asks if isinstance(o, dict)],
                side="buy",  # asks: ascending price
            )
            bids = aggregate_orders_by_price(
                [o for o in raw_bids if isinstance(o, dict)],
                side="sell",  # bids: descending price
            )
        except (TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"lighter orders parse failed: {exc}") from exc
        if not bids or not asks:
            raise AdapterFetchError(
                f"lighter empty book for market_id={market_id}"
            )
        return bids, asks

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        delay = _BACKOFF_START_S
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await self._limiter.acquire()
            try:
                resp = await self.http.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"lighter timeout: {url}") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"lighter HTTP error: {exc}") from exc

            # Standard tier: 429 or 405 on breach (WHI-800 §4.2).
            if resp.status_code in (405, 429):
                last_error = AdapterFetchError(
                    f"lighter rate limited (HTTP {resp.status_code}) "
                    f"attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"lighter HTTP {resp.status_code}: {resp.text[:200]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise AdapterFetchError("lighter response is not JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterFetchError(f"lighter unexpected JSON type: {type(payload)}")
            code = payload.get("code")
            if code not in (None, 200, 0):
                raise AdapterFetchError(f"lighter code={code} body={str(payload)[:200]}")
            return payload

        assert last_error is not None
        raise last_error
