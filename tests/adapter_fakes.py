"""Shared throwaway VenueAdapter stubs for registry/discovery tests (WHI-823)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from spread_compare.adapters.base import BaseAdapter
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)


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
    ) -> Quote:
        raise NotImplementedError

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
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
    ) -> list[str]:
        return []
