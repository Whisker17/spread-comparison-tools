"""Contract-multiplier normalization guard (WHI-826 acceptance criterion).

A ``1000PEPE`` book and a ``kPEPE`` book at the same underlying price must
produce identical ``spread_bps``, matching a hand-computed 1× value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from spread_compare.adapters._cex_common import (
    OrderbookLevels,
)
from spread_compare.adapters._cex_common import (
    build_quote_from_book as cex_build,
)
from spread_compare.adapters._perp_common import (
    build_quote_from_book as perp_build,
)
from spread_compare.costs import spread_bps
from spread_compare.models import ReferenceMid

# Canonical 1× PEPE mid.
_MID_1X = Decimal("0.00001")
# 1000× contract mid/price = 1000 * 1×.
_MULT = Decimal("1000")
_MID_CONTRACT = _MID_1X * _MULT  # 0.01

# Contract-unit book: bid/ask around 0.01 with sizes in 1000PEPE units.
# After scale: prices /1000, sizes *1000 → 1× book around 0.00001.
_CONTRACT_ASKS: OrderbookLevels = [
    (Decimal("0.010001"), Decimal("500000")),  # 5e8 PEPE after scale
    (Decimal("0.010005"), Decimal("500000")),
]
_CONTRACT_BIDS: OrderbookLevels = [
    (Decimal("0.009999"), Decimal("500000")),
    (Decimal("0.009995"), Decimal("500000")),
]

# Same book already in 1× units (for hand-check).
_CANONICAL_ASKS: OrderbookLevels = [
    (px / _MULT, sz * _MULT) for px, sz in _CONTRACT_ASKS
]
_CANONICAL_BIDS: OrderbookLevels = [
    (px / _MULT, sz * _MULT) for px, sz in _CONTRACT_BIDS
]

_MID = ReferenceMid(
    snapshot_id="snap-mult",
    asset="PEPE",
    mid=_MID_1X,
    mid_source="binance_spot_tob",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)

_NOTIONAL = Decimal("10000")


def test_hand_computed_1x_spread() -> None:
    """Independent 1× walk matches formula spread_bps."""
    from spread_compare.bookwalk import walk_book

    q_star = _NOTIONAL / _MID_1X
    p_star = walk_book(_CANONICAL_ASKS, q_star)
    assert p_star is not None
    expected = spread_bps("buy", p_star, _MID_1X)
    # Sanity: effective is slightly above mid.
    assert p_star > _MID_1X
    assert expected > 0


@pytest.mark.asyncio
async def test_1000pepe_and_kpepe_identical_spread_bps() -> None:
    """CEX 1000PEPE path and HL kPEPE path yield the same spread_bps."""
    cex_quote = cex_build(
        venue="binance",
        asset="PEPE",
        side="buy",
        notional_usd=_NOTIONAL,
        mid=_MID,
        instrument_type="perp",
        venue_symbol="1000PEPEUSDT",
        bids=_CONTRACT_BIDS,
        asks=_CONTRACT_ASKS,
        trading_fee_bps=Decimal("10"),
        multiplier=_MULT,
    )
    hl_quote = perp_build(
        venue="hyperliquid",
        asset="PEPE",
        side="buy",
        notional_usd=_NOTIONAL,
        mid=_MID,
        instrument_type="perp",
        venue_symbol="kPEPE",
        bids=_CONTRACT_BIDS,
        asks=_CONTRACT_ASKS,
        trading_fee_bps=Decimal("10"),
        multiplier=_MULT,
    )
    assert cex_quote.status == "ok"
    assert hl_quote.status == "ok"
    assert cex_quote.spread_bps == hl_quote.spread_bps
    assert cex_quote.effective_price == hl_quote.effective_price

    # Match hand-computed 1× value (no multiplier on canonical book).
    from spread_compare.bookwalk import walk_book

    q_star = _NOTIONAL / _MID_1X
    p_star = walk_book(_CANONICAL_ASKS, q_star)
    assert p_star is not None
    hand = spread_bps("buy", p_star, _MID_1X)
    assert cex_quote.spread_bps == hand
    assert hl_quote.spread_bps == hand


def test_unscaled_book_without_multiplier_is_meaningless() -> None:
    """Guard: forgetting multiplier produces a wildly different spread."""
    # Small notional so both paths still fill; wrong mult still mis-prices.
    notional = Decimal("1")
    broken = cex_build(
        venue="binance",
        asset="PEPE",
        side="buy",
        notional_usd=notional,
        mid=_MID,
        instrument_type="perp",
        venue_symbol="1000PEPEUSDT",
        bids=_CONTRACT_BIDS,
        asks=_CONTRACT_ASKS,
        trading_fee_bps=Decimal("10"),
        multiplier=Decimal(1),  # wrong
    )
    fixed = cex_build(
        venue="binance",
        asset="PEPE",
        side="buy",
        notional_usd=notional,
        mid=_MID,
        instrument_type="perp",
        venue_symbol="1000PEPEUSDT",
        bids=_CONTRACT_BIDS,
        asks=_CONTRACT_ASKS,
        trading_fee_bps=Decimal("10"),
        multiplier=_MULT,
    )
    assert broken.status == "ok"
    assert fixed.status == "ok"
    assert broken.spread_bps != fixed.spread_bps
    # Broken compares ~0.01 vs mid 0.00001 → ~10_000_000 bps class error.
    assert broken.spread_bps is not None and broken.spread_bps > Decimal("100000")
