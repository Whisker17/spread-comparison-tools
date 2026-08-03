"""Hyperliquid perp adapter: L2 book walk → Quote (WHI-803).

Endpoints: WHI-800 §4.1. Hard cap 20 levels/side — large notionals may return
``insufficient_liquidity`` (never fabricate depth).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Literal

from spread_compare.adapters._perp_common import (
    DEFAULT_FEE_TIER,
    PLACEHOLDER_TAKER_BPS,
    AsyncRateLimiter,
    OrderbookLevels,
    build_quote_from_book,
    build_top_of_book,
    build_unsupported_quote,
    placeholder_fee_schedule,
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

_INFO_URL = "https://api.hyperliquid.xyz/info"
# HL hard-caps L2 at 20 levels/side (WHI-800 §4.1).
_MAX_LEVELS = 20
# l2Book weight=2; aggregate weight pool 1200/min → max ~600 l2Book/min.
# 0.12s floor ≈ 500/min (1000 weight) — under the pool with headroom.
_MIN_INTERVAL_S = 0.12
# Blue chips always listed; HIP-3 coins pass through on request (WHI-810).
_BLUE_CHIPS: tuple[str, ...] = ("BTC", "ETH", "SOL")
# HL ``funding`` field is hourly; store 8h-equivalent for FeeBreakdown (WHI-799 §5.3).
_HOURS_PER_FUNDING_PERIOD = Decimal("8")


@register_adapter
class HyperliquidAdapter(BaseAdapter):
    """Hyperliquid perpetual L2 walker (info ``l2Book``)."""

    venue: str = "hyperliquid"
    venue_class: VenueClass = "perp_dex"

    def __init__(self, *, timeout: float = 10.0) -> None:
        super().__init__(timeout=timeout)
        self._limiter = AsyncRateLimiter(_MIN_INTERVAL_S)
        # coin → (hourly funding, mark px) from metaAndAssetCtxs at startup.
        self._funding_hourly: dict[str, Decimal] = {}
        self._mark_px: dict[str, Decimal] = {}
        self._universe: list[str] = []

    async def startup(self) -> None:
        if self._started:
            return
        await self._load_meta()
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
        coin = _normalize_hl_coin(asset)
        # Canonical asset id for blue chips; HIP-3 keeps the dex-prefixed coin form
        # until WHI-810 defines a separate logical id (venue form also in venue_symbol).
        asset_key = coin.split(":", 1)[-1] if ":" in coin else coin
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

        bids, asks = await self._fetch_l2_book(coin)
        funding_8h = self._funding_rate_8h(coin)
        mark = self._mark_px.get(coin)
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=itype,
            venue_symbol=coin,
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=PLACEHOLDER_TAKER_BPS,
            funding_rate_8h=funding_8h,
            venue_mark=mark,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        coin = _normalize_hl_coin(asset)
        asset_key = coin.split(":", 1)[-1] if ":" in coin else coin
        require_mid_asset(mid, asset_key)
        if instrument_type not in (None, "perp"):
            raise UnsupportedAssetError(
                f"hyperliquid adapter only supports perp, got {instrument_type!r}"
            )
        bids, asks = await self._fetch_l2_book(coin)
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
            asset=asset.upper() if asset and ":" not in asset else asset,
            instrument_type=itype,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        if self._universe:
            blue = [c for c in _BLUE_CHIPS if c in self._universe]
            rest = sorted(c for c in self._universe if c not in _BLUE_CHIPS)
            return blue + rest
        return list(_BLUE_CHIPS)

    def _funding_rate_8h(self, coin: str) -> Decimal | None:
        hourly = self._funding_hourly.get(coin)
        if hourly is None:
            return None
        return hourly * _HOURS_PER_FUNDING_PERIOD

    async def _load_meta(self) -> None:
        payload = await self._post_info({"type": "metaAndAssetCtxs"})
        try:
            if not isinstance(payload, list) or len(payload) < 2:
                raise AdapterFetchError(
                    f"hyperliquid metaAndAssetCtxs unexpected shape: {type(payload)}"
                )
            meta, ctxs = payload[0], payload[1]
            universe = meta["universe"]
            if not isinstance(universe, list) or not isinstance(ctxs, list):
                raise AdapterFetchError("hyperliquid meta universe/ctxs not lists")
            funding: dict[str, Decimal] = {}
            marks: dict[str, Decimal] = {}
            names: list[str] = []
            for i, entry in enumerate(universe):
                name = str(entry["name"])
                names.append(name)
                if i >= len(ctxs):
                    break
                ctx = ctxs[i]
                if not isinstance(ctx, dict):
                    continue
                if ctx.get("funding") is not None:
                    funding[name] = Decimal(str(ctx["funding"]))
                if ctx.get("markPx") is not None:
                    marks[name] = Decimal(str(ctx["markPx"]))
            self._universe = names
            self._funding_hourly = funding
            self._mark_px = marks
        except (KeyError, TypeError, ArithmeticError, AdapterError) as exc:
            raise AdapterFetchError(f"hyperliquid meta parse failed: {exc}") from exc

    async def _fetch_l2_book(self, coin: str) -> tuple[OrderbookLevels, OrderbookLevels]:
        payload = await self._post_info({"type": "l2Book", "coin": coin})
        try:
            if not isinstance(payload, dict):
                raise AdapterFetchError(
                    f"hyperliquid l2Book unexpected type: {type(payload)}"
                )
            levels = payload["levels"]
            if not isinstance(levels, list) or len(levels) < 2:
                raise AdapterFetchError("hyperliquid l2Book missing levels[0/1]")
            bids = self._parse_hl_levels(levels[0])
            asks = self._parse_hl_levels(levels[1])
        except (KeyError, TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"hyperliquid l2Book parse failed: {exc}") from exc
        if not bids or not asks:
            raise AdapterFetchError(f"hyperliquid empty book for coin={coin!r}")
        return bids, asks

    @staticmethod
    def _parse_hl_levels(raw: object) -> OrderbookLevels:
        if not isinstance(raw, list):
            raise AdapterError(f"level side is not a list: {type(raw)}")
        levels: OrderbookLevels = []
        for row in raw[:_MAX_LEVELS]:
            if not isinstance(row, dict):
                raise AdapterError(f"level row is not an object: {row!r}")
            try:
                price = Decimal(str(row["px"]))
                size = Decimal(str(row["sz"]))
            except (ArithmeticError, ValueError) as exc:
                raise AdapterError(f"level not numeric: {row!r}") from exc
            if size < 0:
                raise AdapterError(f"negative level size: {size}")
            levels.append((price, size))
        return levels

    async def _post_info(self, body: dict[str, Any]) -> Any:
        return await request_json(
            self.http,
            "POST",
            _INFO_URL,
            venue=self.venue,
            limiter=self._limiter,
            json_body=body,
            max_retries=4,
        )


def _normalize_hl_coin(asset: str) -> str:
    """Uppercase blue-chip coins; preserve HIP-3 ``dex:COIN`` form after strip."""
    coin = asset.strip()
    if ":" in coin:
        dex, name = coin.split(":", 1)
        return f"{dex}:{name.upper()}" if name else coin
    return coin.upper()
