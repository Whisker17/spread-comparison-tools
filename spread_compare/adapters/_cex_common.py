"""Shared CEX adapter helpers (quote shell, fees, rate-limit backoff).

Not a venue module — leading underscore keeps auto-discovery from importing it
as an adapter. Binance and Bybit import from here; walk/bps math stay in
``bookwalk`` / ``costs`` only.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from spread_compare.adapters.base import AdapterError
from spread_compare.bookwalk import walk_book
from spread_compare.costs import spread_bps, top_of_book_spread_bps, total_cost_bps
from spread_compare.models import (
    FeeBreakdown,
    FeeSchedule,
    FundingModel,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
)

logger = logging.getLogger(__name__)

# TODO(WHI-812): replace placeholder taker with real default_taker schedule.
PLACEHOLDER_TAKER_BPS: Decimal = Decimal("10")
DEFAULT_FEE_TIER: str = "default_taker"

CexBookSide = Literal["spot", "perp"]
OrderbookLevels = list[tuple[Decimal, Decimal]]


class AsyncRateLimiter:
    """Simple min-interval throttle (one request slot at a time per instance)."""

    def __init__(self, min_interval_s: float) -> None:
        self._min_interval_s = min_interval_s
        self._lock = asyncio.Lock()
        self._last_mono = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval_s - (now - self._last_mono)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_mono = time.monotonic()


def parse_levels(raw: Sequence[Sequence[object]]) -> OrderbookLevels:
    """Parse ``[[price, size], ...]`` string/number rows into Decimal levels."""
    levels: OrderbookLevels = []
    for row in raw:
        if len(row) < 2:
            raise AdapterError(f"orderbook level has <2 fields: {row!r}")
        price = Decimal(str(row[0]))
        size = Decimal(str(row[1]))
        if size < 0:
            raise AdapterError(f"negative level size: {size}")
        levels.append((price, size))
    return levels


def non_ok_fees(*, fee_tier: str) -> FeeBreakdown:
    return FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=None,
    )


def build_quote_from_book(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    venue_symbol: str,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    fee_tier: str = DEFAULT_FEE_TIER,
    trading_fee_bps: Decimal = PLACEHOLDER_TAKER_BPS,
    funding_rate_8h: Decimal | None = None,
    timestamp: datetime | None = None,
) -> Quote:
    """Walk the book and assemble a ``Quote`` (shared CEX path)."""
    now = timestamp or datetime.now(tz=UTC)
    fees = non_ok_fees(fee_tier=fee_tier)
    q_star = notional_usd / mid.mid
    levels = asks if side == "buy" else bids
    p_star = walk_book(levels, q_star)
    if p_star is None:
        return Quote(
            snapshot_id=mid.snapshot_id,
            venue=venue,
            asset=asset,
            venue_symbol=venue_symbol,
            instrument_type=instrument_type,
            side=side,
            notional_usd=notional_usd,
            mid=mid.mid,
            mid_source=mid.mid_source,
            mid_timestamp=mid.timestamp,
            fee_breakdown=fees,
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
        trading_fee_bps=trading_fee_bps,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        gas_usd=None,
        notional_usd=notional_usd,
    )
    ok_fees = FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=trading_fee_bps,
        platform_fee_bps=Decimal("0"),
        gas_usd=None,
        gas_bps=cost.gas_bps,  # explicit 0 when gas_usd is None
        gas_unknown=False,
        funding_rate_8h=funding_rate_8h if instrument_type == "perp" else None,
        explicit_fee_bps=cost.explicit_fee_bps,
    )
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        venue_symbol=venue_symbol,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        effective_price=p_star,
        spread_bps=sp,
        fee_breakdown=ok_fees,
        total_cost_bps=cost.total_cost_bps,
        timestamp=now,
        status="ok",
        qty_base=q_star,
        qty_method="base_from_mid",
    )


def build_unsupported_quote(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    message: str,
    fee_tier: str = DEFAULT_FEE_TIER,
) -> Quote:
    now = datetime.now(tz=UTC)
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        fee_breakdown=non_ok_fees(fee_tier=fee_tier),
        timestamp=now,
        status="unsupported_asset",
        error_code="unsupported_asset",
        error_message=message,
    )


def build_top_of_book(
    *,
    venue: str,
    asset: str,
    instrument_type: CexBookSide,
    mid: ReferenceMid,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    timestamp: datetime | None = None,
) -> TopOfBook:
    if not bids or not asks:
        raise AdapterError(f"{venue}: empty bids or asks for TOB")
    best_bid, bid_size = bids[0]
    best_ask, ask_size = asks[0]
    mid_local = (best_bid + best_ask) / Decimal("2")
    now = timestamp or datetime.now(tz=UTC)
    return TopOfBook(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
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


def placeholder_fee_schedule(
    *,
    venue: str,
    asset: str | None,
    instrument_type: InstrumentType,
    taker_bps: Decimal = PLACEHOLDER_TAKER_BPS,
) -> FeeSchedule:
    funding: FundingModel = "perp_8h" if instrument_type == "perp" else "none"
    return FeeSchedule(
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        maker_bps=Decimal("0"),
        taker_bps=taker_bps,  # TODO(WHI-812)
        default_tier=DEFAULT_FEE_TIER,
        funding_model=funding,
        fee_embedded_in_quote=False,
        source_urls=[],
        updated_at=datetime.now(tz=UTC),
    )


def resolve_cex_instrument(
    instrument_type: InstrumentType | None,
) -> CexBookSide:
    """Map optional instrument_type to spot|perp; default spot (WHI-799 §7)."""
    if instrument_type is None:
        return "spot"
    if instrument_type in ("spot", "perp"):
        return instrument_type
    raise AdapterError(
        f"CEX adapters only support instrument_type spot|perp, got {instrument_type!r}"
    )
