"""Live smokes for Hyperliquid / Lighter / ApeX (WHI-803).

Skipped unless ``pytest --live`` is passed (see tests/conftest.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from spread_compare.adapters.perp_apex import ApexAdapter
from spread_compare.adapters.perp_hyperliquid import HyperliquidAdapter
from spread_compare.adapters.perp_lighter import LighterAdapter
from spread_compare.models import NOTIONAL_TIERS_USD, Quote, ReferenceMid, Side

_ASSETS = ("BTC", "ETH", "SOL")
_SIDES: tuple[Side, ...] = ("buy", "sell")

# Approximate mids for live smokes (only need order of magnitude for q_star).
_APPROX_MID: dict[str, Decimal] = {
    "BTC": Decimal("60000"),
    "ETH": Decimal("2000"),
    "SOL": Decimal("80"),
}


def _mid(asset: str) -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="live-smoke",
        asset=asset,
        mid=_APPROX_MID[asset],
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )


def _assert_quote_shape(quote: Quote, *, allow_insufficient: bool = False) -> None:
    assert quote.instrument_type == "perp"
    assert quote.fee_breakdown.embedded_in_price is False
    if quote.status == "ok":
        assert quote.effective_price is not None
        assert quote.spread_bps is not None
        assert quote.qty_base is not None
        assert quote.total_cost_bps is not None
    elif allow_insufficient and quote.status == "insufficient_liquidity":
        assert quote.effective_price is None
    else:
        pytest.fail(f"unexpected quote status {quote.status!r}: {quote.error_message}")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_hyperliquid_quotes_and_tob() -> None:
    adapter = HyperliquidAdapter()
    try:
        await adapter.startup()
        saw_funding = False
        for asset in _ASSETS:
            mid = _mid(asset)
            tob = await adapter.get_orderbook_spread(asset, mid=mid)
            assert tob is not None
            assert tob.best_bid > 0
            assert tob.best_ask > tob.best_bid
            for side in _SIDES:
                for notional in NOTIONAL_TIERS_USD:
                    quote = await adapter.get_quote(
                        asset, side, notional, mid=mid
                    )
                    # $1M on HL may legitimately be insufficient_liquidity.
                    allow_il = notional >= Decimal("1000000")
                    _assert_quote_shape(quote, allow_insufficient=allow_il)
                    if quote.fee_breakdown.funding_rate_8h is not None:
                        saw_funding = True
        assert saw_funding, "expected funding_rate_8h non-null on Hyperliquid"
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_lighter_quotes_and_tob() -> None:
    adapter = LighterAdapter()
    try:
        await adapter.startup()
        for asset in _ASSETS:
            mid = _mid(asset)
            tob = await adapter.get_orderbook_spread(asset, mid=mid)
            assert tob is not None
            assert tob.best_bid > 0
            assert tob.best_ask > tob.best_bid
            for side in _SIDES:
                for notional in NOTIONAL_TIERS_USD:
                    quote = await adapter.get_quote(
                        asset, side, notional, mid=mid
                    )
                    _assert_quote_shape(quote, allow_insufficient=True)
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_apex_quotes_and_tob() -> None:
    adapter = ApexAdapter()
    try:
        await adapter.startup()
        assert adapter.cross_symbol_for("BTC") == "BTCUSDT"
        for asset in _ASSETS:
            mid = _mid(asset)
            tob = await adapter.get_orderbook_spread(asset, mid=mid)
            assert tob is not None
            assert tob.best_bid > 0
            assert tob.best_ask > tob.best_bid
            for side in _SIDES:
                for notional in NOTIONAL_TIERS_USD:
                    quote = await adapter.get_quote(
                        asset, side, notional, mid=mid
                    )
                    _assert_quote_shape(quote, allow_insufficient=True)
                    if quote.status == "ok":
                        assert quote.venue_symbol is not None
                        assert "-" not in quote.venue_symbol
    finally:
        await adapter.aclose()
