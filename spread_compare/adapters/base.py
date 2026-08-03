"""VenueAdapter protocol and error hierarchy (WHI-799 §7)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)


class AdapterError(Exception):
    """Base error for adapter failures (fetch/timeout/parse).

    Orderbook venues must raise this (or a subclass) on TOB fetch failure —
    never return ``None`` for failure (``None`` means \"no orderbook concept\").
    """


class AdapterFetchError(AdapterError):
    """Upstream HTTP/RPC fetch or parse failed."""


class AdapterTimeoutError(AdapterError):
    """Upstream call timed out."""


class UnsupportedAssetError(AdapterError):
    """Asset is not supported by this venue for the requested instrument type."""


class VenueAdapter(Protocol):
    """Cross-venue adapter surface (WHI-799 §7)."""

    venue: str
    venue_class: VenueClass

    def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
    ) -> Quote:
        """Return a size-aware quote. Computes spread/total bps via shared formulas."""
        ...

    def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        """Return TOB for orderbook venues; always None for AMM/Prop.

        On fetch failure, raise AdapterError — do not return None.
        """
        ...

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        """Return the static fee schedule for this venue (numbers may be placeholders)."""
        ...

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        """Assets this adapter can quote for the given (or default) instrument type."""
        ...


def default_instrument_type(venue_class: VenueClass) -> InstrumentType:
    """Default instrument_type when the caller passes None (WHI-799 §7)."""
    mapping: dict[VenueClass, InstrumentType] = {
        "cex": "spot",
        "perp_dex": "perp",
        "amm_dex": "amm_pool",
        "prop_amm": "prop_amm",
    }
    return mapping[venue_class]
