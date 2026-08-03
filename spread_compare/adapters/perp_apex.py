"""ApeX Omni perp adapter: depth walk → Quote (WHI-803).

Endpoints: WHI-800 §4.3. Depth must use ``crossSymbolName`` (e.g. ``BTCUSDT``),
never the config ``symbol`` field (``BTC-USDT``) which returns null books.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from spread_compare.adapters._perp_common import (
    DEFAULT_FEE_TIER,
    AsyncRateLimiter,
    OrderbookLevels,
    build_quote_from_book,
    build_top_of_book,
    build_unsupported_quote,
    parse_levels,
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
from spread_compare.fees import get_fee_schedule
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

_BASE = "https://omni.apex.exchange/api"
_SYMBOLS_PATH = "/v3/symbols"
_DEPTH_PATH = "/v3/depth"
_TICKER_PATH = "/v3/ticker"
# IP limit 600 req / 60s (WHI-800 §4.3).
_MIN_INTERVAL_S = 0.15
_DEPTH_LIMIT = 100
_BLUE_CHIPS: tuple[str, ...] = ("BTC", "ETH", "SOL")


@dataclass(frozen=True, slots=True)
class _ApexSymbol:
    """Resolved symbol mapping for one logical base asset."""

    base: str
    config_symbol: str  # e.g. BTC-USDT (must NOT be used for depth)
    cross_symbol_name: str  # e.g. BTCUSDT (depth/ticker query key)


@register_adapter
class ApexAdapter(BaseAdapter):
    """ApeX Omni perpetual depth walker."""

    venue: str = "apex"
    venue_class: VenueClass = "perp_dex"

    def __init__(self, *, timeout: float = 10.0) -> None:
        super().__init__(timeout=timeout)
        self._limiter = AsyncRateLimiter(_MIN_INTERVAL_S)
        self._symbols_by_base: dict[str, _ApexSymbol] = {}
        self._mark_by_cross: dict[str, Decimal] = {}

    async def startup(self) -> None:
        if self._started:
            return
        await self._load_symbols()
        await self._warm_blue_chip_tickers()
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

        sym = self._symbols_by_base.get(asset_key)
        if sym is None:
            return build_unsupported_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=itype,
                message=f"{asset} not in apex symbols table (run startup)",
                fee_tier=tier,
            )

        bids, asks = await self._fetch_depth(sym.cross_symbol_name)
        mark = self._mark_by_cross.get(sym.cross_symbol_name)
        schedule = self.get_fees(asset_key, instrument_type=itype)
        if schedule.taker_bps is None:
            raise AdapterError(f"{self.venue}: fee schedule missing taker_bps")
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=itype,
            venue_symbol=sym.cross_symbol_name,
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=schedule.taker_bps,
            # funding_rate_8h still None on quote path (ticker field present but
            # not joined per-quote); funding_model is perp_continuous in config.
            funding_rate_8h=None,
            venue_mark=mark,
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        asset_key = asset.upper()
        require_mid_asset(mid, asset_key)
        if instrument_type not in (None, "perp"):
            raise UnsupportedAssetError(
                f"apex adapter only supports perp, got {instrument_type!r}"
            )
        sym = self._symbols_by_base.get(asset_key)
        if sym is None:
            raise UnsupportedAssetError(f"{asset} not supported by apex")
        bids, asks = await self._fetch_depth(sym.cross_symbol_name)
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
        return get_fee_schedule(
            self.venue,
            itype,
            asset=asset.upper() if asset else None,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        if self._symbols_by_base:
            blue = [c for c in _BLUE_CHIPS if c in self._symbols_by_base]
            rest = sorted(s for s in self._symbols_by_base if s not in _BLUE_CHIPS)
            return blue + rest
        return list(_BLUE_CHIPS)

    def cross_symbol_for(self, asset: str) -> str | None:
        """Return depth-query symbol for ``asset`` (tests: BTC → BTCUSDT)."""
        sym = self._symbols_by_base.get(asset.upper())
        return None if sym is None else sym.cross_symbol_name

    def config_symbol_for(self, asset: str) -> str | None:
        """Return config ``symbol`` field (tests: BTC → BTC-USDT; not for depth)."""
        sym = self._symbols_by_base.get(asset.upper())
        return None if sym is None else sym.config_symbol

    async def _load_symbols(self) -> None:
        payload = await self._get_json(f"{_BASE}{_SYMBOLS_PATH}")
        try:
            data = payload["data"]
            contracts = data["contractConfig"]["perpetualContract"]
            if not isinstance(contracts, list):
                raise AdapterFetchError("apex perpetualContract is not a list")
            by_base: dict[str, _ApexSymbol] = {}
            for row in contracts:
                if not isinstance(row, dict):
                    continue
                base = str(row.get("baseTokenId") or "").upper()
                cross = str(row.get("crossSymbolName") or "")
                config_sym = str(row.get("symbol") or "")
                if not base or not cross:
                    continue
                if base in by_base:
                    continue
                by_base[base] = _ApexSymbol(
                    base=base,
                    config_symbol=config_sym,
                    cross_symbol_name=cross,
                )
            if not by_base:
                raise AdapterFetchError("apex symbols returned no perpetual contracts")
            self._symbols_by_base = by_base
        except (KeyError, TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"apex symbols parse failed: {exc}") from exc

    async def _warm_blue_chip_tickers(self) -> None:
        """Cache funding/mark for blue chips once at startup (optional fields)."""
        for base in _BLUE_CHIPS:
            sym = self._symbols_by_base.get(base)
            if sym is None:
                continue
            try:
                await self._load_ticker(sym.cross_symbol_name)
            except AdapterError as exc:
                logger.warning(
                    "apex ticker warm-up failed for %s: %s", sym.cross_symbol_name, exc
                )

    async def _load_ticker(self, cross_symbol: str) -> None:
        payload = await self._get_json(
            f"{_BASE}{_TICKER_PATH}",
            params={"symbol": cross_symbol},
        )
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            return
        row = rows[0]
        if not isinstance(row, dict):
            return
        if row.get("markPrice") is not None:
            try:
                self._mark_by_cross[cross_symbol] = Decimal(str(row["markPrice"]))
            except (ArithmeticError, ValueError) as exc:
                raise AdapterFetchError(
                    f"apex markPrice not numeric for {cross_symbol}: {exc}"
                ) from exc

    async def _fetch_depth(
        self, cross_symbol: str
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        payload = await self._get_json(
            f"{_BASE}{_DEPTH_PATH}",
            params={"symbol": cross_symbol, "limit": str(_DEPTH_LIMIT)},
        )
        try:
            data = payload["data"]
            if data is None:
                raise AdapterFetchError(
                    f"apex depth data is null for symbol={cross_symbol!r} "
                    "(wrong symbol form? use crossSymbolName)"
                )
            raw_asks = data["a"]
            raw_bids = data["b"]
            if raw_asks is None or raw_bids is None:
                raise AdapterFetchError(
                    f"apex depth a/b null for symbol={cross_symbol!r}"
                )
            asks = parse_levels(raw_asks)
            bids = parse_levels(raw_bids)
        except (KeyError, TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"apex depth parse failed: {exc}") from exc
        if not bids or not asks:
            raise AdapterFetchError(f"apex empty book for {cross_symbol}")
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
            retry_statuses=frozenset({429}),
        )
        if not isinstance(payload, dict):
            raise AdapterFetchError(f"apex unexpected JSON type: {type(payload)}")
        return payload
