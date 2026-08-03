"""Hyperliquid perp adapter: L2 book walk → Quote (WHI-803 / WHI-826).

Endpoints: WHI-800 §4.1. Hard cap 20 levels/side — large notionals may return
``insufficient_liquidity`` (never fabricate depth).

HIP-3 equity perps use ``xyz:TSLA`` coin form; meta is loaded for the main book
and the ``xyz`` sub-dex only (WHI-798 §8 Q10). Scaled memes (``kPEPE``) normalize
via contract multiplier before cost formulas (WHI-826).
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
from spread_compare.perp_symbols import (
    HL_ALLOWED_DEXES,
    HL_PHASE1_ASSETS,
    UnsupportedPerpSymbolError,
    hl_logical_id,
    resolve_hl_coin,
)

logger = logging.getLogger(__name__)

_INFO_URL = "https://api.hyperliquid.xyz/info"
# HL hard-caps L2 at 20 levels/side (WHI-800 §4.1).
_MAX_LEVELS = 20
# l2Book weight=2; aggregate weight pool 1200/min → max ~600 l2Book/min.
# 0.12s floor ≈ 500/min (1000 weight) — under the pool with headroom.
_MIN_INTERVAL_S = 0.12
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
        # Full coin names present in allowed dexes (e.g. BTC, xyz:TSLA, kPEPE).
        self._universe_coins: set[str] = set()
        # Logical ids we can quote (TSLA, DOGE, …).
        self._logical_assets: list[str] = []

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
        tier = fee_tier or DEFAULT_FEE_TIER
        try:
            resolved = resolve_hl_coin(asset)
        except UnsupportedPerpSymbolError as exc:
            asset_key = asset.split(":", 1)[-1].upper() if ":" in asset else asset.upper()
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
        coin = resolved.venue_symbol
        asset_key = hl_logical_id(coin)

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

        if self._universe_coins and coin not in self._universe_coins:
            return build_unsupported_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=itype,
                message=f"{asset} (coin={coin!r}) not on hyperliquid allowed dexes",
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
            multiplier=resolved.multiplier,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        try:
            resolved = resolve_hl_coin(asset)
        except UnsupportedPerpSymbolError as exc:
            raise UnsupportedAssetError(str(exc)) from exc
        coin = resolved.venue_symbol
        asset_key = hl_logical_id(coin)
        require_mid_asset(mid, asset_key)
        if instrument_type not in (None, "perp"):
            raise UnsupportedAssetError(
                f"hyperliquid adapter only supports perp, got {instrument_type!r}"
            )
        if self._universe_coins and coin not in self._universe_coins:
            raise UnsupportedAssetError(
                f"{asset} (coin={coin!r}) not on hyperliquid allowed dexes"
            )
        bids, asks = await self._fetch_l2_book(coin)
        return build_top_of_book(
            venue=self.venue,
            asset=asset_key,
            mid=mid,
            bids=bids,
            asks=asks,
            instrument_type="perp",
            multiplier=resolved.multiplier,
        )

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        itype = instrument_type or default_instrument_type(self.venue_class)
        label: str | None
        if asset is None:
            label = None
        elif ":" in asset:
            label = asset
        else:
            label = asset.upper()
        return placeholder_fee_schedule(
            venue=self.venue,
            asset=label,
            instrument_type=itype,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        if self._logical_assets:
            return list(self._logical_assets)
        return list(HL_PHASE1_ASSETS)

    def _funding_rate_8h(self, coin: str) -> Decimal | None:
        hourly = self._funding_hourly.get(coin)
        if hourly is None:
            return None
        return hourly * _HOURS_PER_FUNDING_PERIOD

    async def _load_meta(self) -> None:
        """Load main book + xyz HIP-3 meta (whitelist only — WHI-798 §8 Q10)."""
        funding: dict[str, Decimal] = {}
        marks: dict[str, Decimal] = {}
        coins: set[str] = set()

        for dex in ("", "xyz"):
            body: dict[str, Any] = {"type": "metaAndAssetCtxs"}
            if dex:
                body["dex"] = dex
            payload = await self._post_info(body)
            try:
                if not isinstance(payload, list) or len(payload) < 2:
                    raise AdapterFetchError(
                        f"hyperliquid metaAndAssetCtxs unexpected shape: {type(payload)}"
                    )
                meta, ctxs = payload[0], payload[1]
                universe = meta["universe"]
                if not isinstance(universe, list) or not isinstance(ctxs, list):
                    raise AdapterFetchError("hyperliquid meta universe/ctxs not lists")
                for i, entry in enumerate(universe):
                    raw_name = str(entry["name"])
                    # Main book names are bare (preserve case: kPEPE ≠ KPEPE).
                    # xyz responses may be "TSLA" or "xyz:TSLA".
                    if dex and ":" not in raw_name:
                        coin = f"{dex}:{raw_name.upper()}"
                    elif ":" in raw_name:
                        d, n = raw_name.split(":", 1)
                        d_l = d.lower()
                        # Only whitelisted HIP-3 prefixes (main book has no prefix).
                        if d_l not in HL_ALLOWED_DEXES:
                            continue
                        coin = f"{d_l}:{n.upper()}"
                    else:
                        coin = raw_name
                    coins.add(coin)
                    if i >= len(ctxs):
                        break
                    ctx = ctxs[i]
                    if not isinstance(ctx, dict):
                        continue
                    if ctx.get("funding") is not None:
                        funding[coin] = Decimal(str(ctx["funding"]))
                    if ctx.get("markPx") is not None:
                        marks[coin] = Decimal(str(ctx["markPx"]))
            except (KeyError, TypeError, ArithmeticError, AdapterError) as exc:
                raise AdapterFetchError(
                    f"hyperliquid meta parse failed (dex={dex!r}): {exc}"
                ) from exc

        self._universe_coins = coins
        self._funding_hourly = funding
        self._mark_px = marks
        self._logical_assets = self._build_logical_list(coins)

    @staticmethod
    def _build_logical_list(coins: set[str]) -> list[str]:
        """Prefer Phase-1 order, then remaining logical ids sorted."""
        logicals = {hl_logical_id(c) for c in coins}
        # Also expose known overrides whose coins are present.
        ordered: list[str] = []
        for asset in HL_PHASE1_ASSETS:
            coin = resolve_hl_coin(asset).venue_symbol
            if coin in coins or asset in logicals:
                ordered.append(asset)
        for asset in sorted(logicals):
            if asset not in ordered:
                ordered.append(asset)
        return ordered

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
