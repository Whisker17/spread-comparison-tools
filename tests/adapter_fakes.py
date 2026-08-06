"""Shared throwaway VenueAdapter stubs and mid fixtures (WHI-823 / WHI-807 / WHI-814)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from spread_compare.adapters.base import BaseAdapter
from spread_compare.mids import MidResolutionError, MidService
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.settings import MidSettings

DEFAULT_TEST_MID = ReferenceMid(
    snapshot_id="snap-test",
    asset="BTC",
    mid=Decimal("100000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
)

TEST_MID_SETTINGS = MidSettings(
    force_pyth=False,
    stale_threshold_sec=5,
    cache_max_age_sec=30,
    http_timeout_sec=5,
    max_age_for_ws_quote_sec=2.0,
    pyth_feed_ids={},
    stock_mid_p2_order=[
        {"form": "bstock", "venue": "binance"},
        {"form": "xstock_cex", "venue": "bybit"},
    ],
)


class FixedMid(MidService):
    """MidService stub that returns a fixed mid without HTTP."""

    def __init__(self, mid: ReferenceMid | None = None, *, fail: bool = False) -> None:
        super().__init__(TEST_MID_SETTINGS, client=None)
        self._fixed = mid or DEFAULT_TEST_MID
        self._fail = fail

    async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
        if self._fail:
            raise MidResolutionError("injected mid failure")
        return self._fixed.model_copy(
            update={"snapshot_id": snapshot_id, "asset": asset.upper()}
        )


class SlowAdapter(BaseAdapter):
    """Sleeps past venue_timeout_sec so fan-out records status=error."""

    venue: str = "binance"
    venue_class: VenueClass = "cex"

    async def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
        form: str | None = None,
    ) -> Quote:
        _ = form
        await asyncio.sleep(5)
        raise AssertionError("should have been cancelled by timeout")

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
        form: str | None = None,
    ) -> TopOfBook | None:
        _ = form
        return None

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        raise NotImplementedError

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
        form: str | None = None,
    ) -> list[str]:
        return ["BTC"]


class StubAdapter(BaseAdapter):
    """Minimal async adapter surface; subclasses must set a real ``venue`` slug."""

    venue: str = "stub_unregistered"
    venue_class: VenueClass = "cex"

    async def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
        form: str | None = None,
    ) -> Quote:
        _ = form
        raise NotImplementedError

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
        form: str | None = None,
    ) -> TopOfBook | None:
        _ = form
        return None

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        raise NotImplementedError

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
        form: str | None = None,
    ) -> list[str]:
        return []
