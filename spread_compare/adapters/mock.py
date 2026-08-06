"""Deterministic mock adapter serving the WHI-799 §4.7 fixture book.

Registered as ``mock`` so WHI-807 can develop aggregation without live venues.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from spread_compare.adapters.base import (
    AdapterError,
    BaseAdapter,
    UnsupportedAssetError,
    default_instrument_type,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.bookwalk import walk_book
from spread_compare.costs import spread_bps, top_of_book_spread_bps, total_cost_bps
from spread_compare.models import (
    FeeBreakdown,
    FeeSchedule,
    FundingModel,
    InstrumentType,
    QtyMethod,
    Quote,
    QuoteStatus,
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
_DEFAULT_FEE_TIER = "default_taker"


def _non_ok_fees(*, fee_tier: str) -> FeeBreakdown:
    """FeeBreakdown for non-ok quotes (no explicit fee components filled)."""
    return FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=None,
    )


def _quote_shell(
    *,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    status: QuoteStatus,
    fee_breakdown: FeeBreakdown,
    timestamp: datetime,
    venue_symbol: str | None = None,
    effective_price: Decimal | None = None,
    spread_bps_value: Decimal | None = None,
    total_cost_bps_value: Decimal | None = None,
    qty_base: Decimal | None = None,
    qty_method: QtyMethod | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> Quote:
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue="mock",
        asset=asset,
        venue_symbol=venue_symbol,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        effective_price=effective_price,
        spread_bps=spread_bps_value,
        fee_breakdown=fee_breakdown,
        total_cost_bps=total_cost_bps_value,
        timestamp=timestamp,
        status=status,
        qty_base=qty_base,
        qty_method=qty_method,
        error_code=error_code,
        error_message=error_message,
    )


@register_adapter
class MockAdapter(BaseAdapter):
    """CEX-shaped mock with the §4.7 fixture orderbook."""

    venue: str = "mock"
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
        _ = form  # WHI-881: accept form; mock has no stock forms
        itype = instrument_type or default_instrument_type(self.venue_class)
        now = datetime.now(tz=UTC)
        asset_key = asset.upper()
        tier = fee_tier or _DEFAULT_FEE_TIER
        fees = _non_ok_fees(fee_tier=tier)

        if asset_key not in _SUPPORTED:
            return _quote_shell(
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="unsupported_asset",
                fee_breakdown=fees,
                timestamp=now,
                error_code="unsupported_asset",
                error_message=f"{asset} not supported by mock",
            )

        if mid.asset.upper() != asset_key:
            raise AdapterError(
                f"mid.asset={mid.asset!r} does not match asset={asset!r}"
            )

        q_star = notional_usd / mid.mid
        levels = _ASKS if side == "buy" else _BIDS
        p_star = walk_book(levels, q_star)
        if p_star is None:
            return _quote_shell(
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="insufficient_liquidity",
                fee_breakdown=fees,
                timestamp=now,
                venue_symbol=f"{asset_key}USDT",
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
        ok_fees = FeeBreakdown(
            embedded_in_price=False,
            fee_tier=tier,
            trading_fee_bps=_TAKER_BPS,
            platform_fee_bps=Decimal("0"),
            gas_usd=None,
            gas_bps=cost.gas_bps,
            gas_unknown=False,
            explicit_fee_bps=cost.explicit_fee_bps,
        )
        return _quote_shell(
            mid=mid,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            instrument_type=itype,
            status="ok",
            fee_breakdown=ok_fees,
            timestamp=now,
            venue_symbol=f"{asset_key}USDT",
            effective_price=p_star,
            spread_bps_value=sp,
            total_cost_bps_value=cost.total_cost_bps,
            qty_base=q_star,
            qty_method="base_from_mid",
        )

    async def get_quotes_batch(
        self,
        asset: str,
        sides: Sequence[Side],
        notionals: Sequence[Decimal],
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
        form: str | None = None,
    ) -> list[Quote]:
        """Walk the fixture book at every notional × side (shared timestamp)."""
        if not notionals or not sides:
            raise AdapterError("get_quotes_batch requires notionals and sides")
        shared_ts = datetime.now(tz=UTC)
        out: list[Quote] = []
        for n in notionals:
            for side in sides:
                q = await self.get_quote(
                    asset,
                    side,
                    n,
                    mid=mid,
                    instrument_type=instrument_type,
                    fee_tier=fee_tier,
                    form=form,
                )
                out.append(q.model_copy(update={"timestamp": shared_ts}))
        return out

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
        form: str | None = None,
    ) -> TopOfBook | None:
        _ = form
        if asset.upper() not in _SUPPORTED:
            raise UnsupportedAssetError(f"{asset} not supported by mock")
        itype: Literal["spot", "perp"] = instrument_type or "spot"
        best_ask, ask_size = _ASKS[0]
        best_bid, bid_size = _BIDS[0]
        mid_local = (best_bid + best_ask) / Decimal("2")
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
            spread_bps=top_of_book_spread_bps(best_bid, best_ask, mid.mid),
            spread_bps_local=top_of_book_spread_bps(best_bid, best_ask, mid_local),
            timestamp=now,
        )

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        itype = instrument_type or default_instrument_type(self.venue_class)
        funding: FundingModel = "perp_8h" if itype == "perp" else "none"
        return FeeSchedule(
            venue=self.venue,
            asset=asset,
            instrument_type=itype,
            maker_bps=Decimal("0"),
            taker_bps=_TAKER_BPS,
            default_tier=_DEFAULT_FEE_TIER,
            funding_model=funding,
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
