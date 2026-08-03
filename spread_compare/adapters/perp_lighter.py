"""Lighter perp adapter: per-order book → aggregate → walk → Quote (WHI-803).

Endpoints: WHI-800 §4.2. Standard tier is 60 requests / rolling minute — enforced
client-side via :class:`RollingWindowRateLimiter`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from spread_compare.adapters._perp_common import (
    DEFAULT_FEE_TIER,
    OrderbookLevels,
    RollingWindowRateLimiter,
    aggregate_orders_by_price,
    build_quote_from_book,
    build_top_of_book,
    build_unsupported_quote,
    request_json,
    require_mid_asset,
    resolve_perp_instrument,
)
from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    BaseAdapter,
    UnsupportedAssetError,
    default_instrument_type,
    require_taker_bps,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import (
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.perp_symbols import resolve_lighter_symbol, scaled_1000_logical_id

logger = logging.getLogger(__name__)

_BASE = "https://mainnet.zklighter.elliot.ai"
_DETAILS_PATH = "/api/v1/orderBookDetails"
_ORDERS_PATH = "/api/v1/orderBookOrders"
# Standard tier: 60 req / rolling minute (WHI-800 §4.2). 429/405 on breach.
_DEFAULT_MAX_RPM = 60
_DEFAULT_WINDOW_S = 60.0
_ORDER_LIMIT = 100
_BLUE_CHIPS: tuple[str, ...] = ("BTC", "ETH", "SOL")


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
        await self._load_markets()
        await super().startup()

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
        resolved = resolve_lighter_symbol(asset_key)
        tier = fee_tier or DEFAULT_FEE_TIER

        require_mid_asset(mid, asset_key)

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

        meta = self._markets_by_symbol.get(resolved.venue_symbol)
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
        schedule = self.get_fees(asset_key, instrument_type=itype)
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=itype,
            venue_symbol=meta.symbol,
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=require_taker_bps(self.venue, schedule),
            funding_rate_8h=None,  # not exposed on orderBookDetails (Phase 1)
            venue_mark=meta.mark_price,
            multiplier=resolved.multiplier,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        asset_key = asset.upper()
        resolved = resolve_lighter_symbol(asset_key)
        require_mid_asset(mid, asset_key)
        if instrument_type not in (None, "perp"):
            raise UnsupportedAssetError(
                f"lighter adapter only supports perp, got {instrument_type!r}"
            )
        meta = self._markets_by_symbol.get(resolved.venue_symbol)
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
            multiplier=resolved.multiplier,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        if self._markets_by_symbol:
            logicals = {scaled_1000_logical_id(sym) for sym in self._markets_by_symbol}
            blue = [c for c in _BLUE_CHIPS if c in logicals]
            rest = sorted(s for s in logicals if s not in _BLUE_CHIPS)
            return blue + rest
        return list(_BLUE_CHIPS)

    def market_id_for(self, asset: str) -> int | None:
        """Return cached ``market_id`` for ``asset`` (tests / debugging)."""
        resolved = resolve_lighter_symbol(asset)
        meta = self._markets_by_symbol.get(resolved.venue_symbol)
        return None if meta is None else meta.market_id

    async def _load_markets(self) -> None:
        payload = await self._get_json(f"{_BASE}{_DETAILS_PATH}")
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
        payload = await self._get_json(url, params=params)
        try:
            raw_asks = payload.get("asks") or []
            raw_bids = payload.get("bids") or []
            if not isinstance(raw_asks, list) or not isinstance(raw_bids, list):
                raise AdapterFetchError("lighter orderBookOrders asks/bids not lists")
            asks = aggregate_orders_by_price(
                [o for o in raw_asks if isinstance(o, dict)],
                descending=False,
            )
            bids = aggregate_orders_by_price(
                [o for o in raw_bids if isinstance(o, dict)],
                descending=True,
            )
        except (TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"lighter orders parse failed: {exc}") from exc
        if not bids or not asks:
            raise AdapterFetchError(
                f"lighter empty book for market_id={market_id}"
            )
        return bids, asks

    async def _get_json(
        self, url: str, *, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        payload = await request_json(
            self.http,
            "GET",
            url,
            venue=self.venue,
            limiter=self._limiter,
            params=params,
            retry_statuses=frozenset({405, 429}),
            ok_codes=frozenset({None, 200, 0}),
        )
        if not isinstance(payload, dict):
            raise AdapterFetchError(f"lighter unexpected JSON type: {type(payload)}")
        return payload
