"""Deterministic mock adapter serving the WHI-799 §4.7 fixture book.

Registered as ``mock`` so WHI-807 can develop aggregation without live venues.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from spread_compare.adapters.base import (
    UnsupportedAssetError,
    default_instrument_type,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.bookwalk import walk_book
from spread_compare.costs import spread_bps, total_cost_bps
from spread_compare.models import (
    FeeBreakdown,
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)

# WHI-799 §4.7 buy asks / sell bids (symmetric about mid=100_000).
_ASKS: list[tuple[Decimal, Decimal]] = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
_BIDS: list[tuple[Decimal, Decimal]] = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]

_TAKER_BPS = Decimal("10")
_SUPPORTED = ("BTC",)


@register_adapter
class MockAdapter:
    """CEX-shaped mock with the §4.7 fixture orderbook."""

    venue: str = "mock"
    venue_class: VenueClass = "cex"

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
        itype = instrument_type or default_instrument_type(self.venue_class)
        now = datetime.now(tz=UTC)
        empty_fees = FeeBreakdown(
            embedded_in_price=False,
            fee_tier=fee_tier or "default_taker",
            trading_fee_bps=None,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=None,
        )

        if asset.upper() not in _SUPPORTED:
            return Quote(
                snapshot_id=mid.snapshot_id,
                venue=self.venue,
                asset=asset,
                instrument_type=itype,
                side=side,
                notional_usd=notional_usd,
                mid=mid.mid,
                mid_source=mid.mid_source,
                mid_timestamp=mid.timestamp,
                fee_breakdown=empty_fees,
                timestamp=now,
                status="unsupported_asset",
                error_code="unsupported_asset",
                error_message=f"{asset} not supported by mock",
            )

        if mid.asset.upper() != asset.upper():
            return Quote(
                snapshot_id=mid.snapshot_id,
                venue=self.venue,
                asset=asset,
                instrument_type=itype,
                side=side,
                notional_usd=notional_usd,
                mid=mid.mid,
                mid_source=mid.mid_source,
                mid_timestamp=mid.timestamp,
                fee_breakdown=empty_fees,
                timestamp=now,
                status="error",
                error_code="mid_asset_mismatch",
                error_message=f"mid.asset={mid.asset!r} does not match asset={asset!r}",
            )

        q_star = notional_usd / mid.mid
        levels = _ASKS if side == "buy" else _BIDS
        p_star = walk_book(levels, q_star)
        if p_star is None:
            return Quote(
                snapshot_id=mid.snapshot_id,
                venue=self.venue,
                asset=asset,
                venue_symbol=f"{asset.upper()}USDT",
                instrument_type=itype,
                side=side,
                notional_usd=notional_usd,
                mid=mid.mid,
                mid_source=mid.mid_source,
                mid_timestamp=mid.timestamp,
                fee_breakdown=empty_fees,
                timestamp=now,
                status="insufficient_liquidity",
                qty_method="base_from_mid",
                error_code="insufficient_liquidity",
                error_message=f"depth < q_star={q_star}",
            )

        sp = spread_bps(side, p_star, mid.mid)
        cost = total_cost_bps(
            sp,
            embedded_in_price=False,
            trading_fee_bps=_TAKER_BPS,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            gas_usd=None,
            notional_usd=notional_usd,
        )
        fees = FeeBreakdown(
            embedded_in_price=False,
            fee_tier=fee_tier or "default_taker",
            trading_fee_bps=_TAKER_BPS,
            platform_fee_bps=Decimal("0"),
            gas_usd=None,
            gas_bps=cost.gas_bps,
            gas_unknown=False,
            explicit_fee_bps=cost.explicit_fee_bps,
        )
        return Quote(
            snapshot_id=mid.snapshot_id,
            venue=self.venue,
            asset=asset.upper(),
            venue_symbol=f"{asset.upper()}USDT",
            instrument_type=itype,
            side=side,
            notional_usd=notional_usd,
            mid=mid.mid,
            mid_source=mid.mid_source,
            mid_timestamp=mid.timestamp,
            mid_stale=False,
            effective_price=p_star,
            spread_bps=sp,
            fee_breakdown=fees,
            total_cost_bps=cost.total_cost_bps,
            timestamp=now,
            status="ok",
            qty_base=q_star,
            qty_method="base_from_mid",
        )

    def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        if asset.upper() not in _SUPPORTED:
            raise UnsupportedAssetError(f"{asset} not supported by mock")
        itype: Literal["spot", "perp"] = instrument_type or "spot"
        best_ask, ask_size = _ASKS[0]
        best_bid, bid_size = _BIDS[0]
        mid_local = (best_bid + best_ask) / Decimal("2")
        width = best_ask - best_bid
        now = datetime.now(tz=UTC)
        return TopOfBook(
            snapshot_id=mid.snapshot_id,
            venue=self.venue,
            asset=asset.upper(),
            instrument_type=itype,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            mid_local=mid_local,
            mid_ref=mid.mid,
            mid_timestamp=mid.timestamp,
            spread_bps=width / mid.mid * Decimal("10000"),
            spread_bps_local=width / mid_local * Decimal("10000"),
            timestamp=now,
        )

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        itype = instrument_type or default_instrument_type(self.venue_class)
        return FeeSchedule(
            venue=self.venue,
            asset=asset,
            instrument_type=itype,
            maker_bps=Decimal("0"),
            taker_bps=_TAKER_BPS,
            default_tier="default_taker",
            funding_model="none" if itype == "spot" else "perp_8h",
            fee_embedded_in_quote=False,
            source_urls=[],
            updated_at=datetime.now(tz=UTC),
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        return list(_SUPPORTED)
