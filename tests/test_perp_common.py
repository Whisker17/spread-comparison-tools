"""Unit tests for shared perp helpers (aggregation, rate limiter, quote shell)."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from spread_compare.adapters._perp_common import (
    aggregate_orders_by_price,
    build_quote_from_book,
)
from spread_compare.costs import basis_bps
from spread_compare.ratelimit import RollingWindowRateLimiter

# WHI-799 §4.7
_MID = Decimal("100000")
_ASKS = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
_BIDS = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]


def _ref_mid() -> object:
    from spread_compare.models import ReferenceMid

    return ReferenceMid(
        snapshot_id="snap-test",
        asset="BTC",
        mid=_MID,
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )


def test_aggregate_orders_by_price_sums_same_price() -> None:
    orders = [
        {"price": "100.0", "remaining_base_amount": "0.01"},
        {"price": "100.0", "remaining_base_amount": "0.02"},
        {"price": "101.0", "remaining_base_amount": "0.05"},
    ]
    asks = aggregate_orders_by_price(orders, descending=False)
    assert asks == [
        (Decimal("100.0"), Decimal("0.03")),
        (Decimal("101.0"), Decimal("0.05")),
    ]
    bids = aggregate_orders_by_price(orders, descending=True)
    assert bids[0][0] == Decimal("101.0")
    assert bids[1][0] == Decimal("100.0")


def test_build_quote_canonical_section_4_7() -> None:
    mid = _ref_mid()
    # HL Tier-0 default taker is 4.5 bps (config/fees/hyperliquid.yaml).
    quote = build_quote_from_book(
        venue="hyperliquid",
        asset="BTC",
        side="buy",
        notional_usd=Decimal("10000"),
        mid=mid,  # type: ignore[arg-type]
        instrument_type="perp",
        venue_symbol="BTC",
        bids=_BIDS,
        asks=_ASKS,
        trading_fee_bps=Decimal("4.5"),
    )
    assert quote.status == "ok"
    assert quote.effective_price == Decimal("100044")
    assert quote.spread_bps == Decimal("4.4")
    assert quote.total_cost_bps == Decimal("8.9")  # 4.4 + 4.5
    assert quote.qty_base == Decimal("0.1")
    assert quote.fee_breakdown.gas_bps == Decimal("0")
    assert quote.fee_breakdown.embedded_in_price is False
    assert quote.fee_breakdown.trading_fee_bps == Decimal("4.5")


def test_build_quote_insufficient_liquidity() -> None:
    mid = _ref_mid()
    shallow = [(Decimal("100010"), Decimal("0.01"))]
    quote = build_quote_from_book(
        venue="hyperliquid",
        asset="BTC",
        side="buy",
        notional_usd=Decimal("10000"),
        mid=mid,  # type: ignore[arg-type]
        instrument_type="perp",
        venue_symbol="BTC",
        bids=_BIDS,
        asks=shallow,
        trading_fee_bps=Decimal("4.5"),
    )
    assert quote.status == "insufficient_liquidity"
    assert quote.effective_price is None
    assert quote.spread_bps is None


def test_basis_bps() -> None:
    assert basis_bps(Decimal("100100"), Decimal("100000")) == Decimal("10")


@pytest.mark.asyncio
async def test_rolling_window_rate_limiter_caps_burst() -> None:
    limiter = RollingWindowRateLimiter(max_requests=3, window_s=0.4)
    t0 = time.monotonic()
    for _ in range(3):
        await limiter.acquire()
    # 4th must wait until the oldest falls out of the window.
    await limiter.acquire()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.35
