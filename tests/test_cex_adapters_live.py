"""Live smoke tests for Binance / Bybit adapters (WHI-802).

Skipped unless ``pytest --live`` is passed (see tests/conftest.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import pytest

import spread_compare.adapters  # noqa: F401
from spread_compare.adapters import get
from spread_compare.adapters.base import BaseAdapter
from spread_compare.models import NOTIONAL_TIERS_USD, Quote, ReferenceMid, Side, TopOfBook

_VENUES = ("binance", "bybit")
_SIDES: tuple[Side, ...] = ("buy", "sell")
_INSTRUMENTS: tuple[Literal["spot", "perp"], ...] = ("spot", "perp")


async def _approx_mid(adapter: BaseAdapter, venue: str) -> ReferenceMid:
    """Build a reference mid from the venue's own TOB (live smoke only).

    WHI-807 will own real mid resolution; here we only need a mid that lets
    Quotes validate. Using mid_local keeps the smoke independent of mid service.
    """
    seed = ReferenceMid(
        snapshot_id="live-seed",
        asset="BTC",
        mid=Decimal("100000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    tob = await adapter.get_orderbook_spread("BTC", mid=seed, instrument_type="spot")
    assert tob is not None
    source: Literal["binance_spot_tob", "bybit_spot_tob"] = (
        "binance_spot_tob" if venue == "binance" else "bybit_spot_tob"
    )
    return ReferenceMid(
        snapshot_id=f"live-{venue}-{int(datetime.now(tz=UTC).timestamp())}",
        asset="BTC",
        mid=tob.mid_local,
        mid_source=source,
        timestamp=datetime.now(tz=UTC),
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_doge_and_qqq_bstock_cex() -> None:
    """WHI-826/881 AC: DOGE (spot) and QQQ bstock (tokenized spot) return ok on CEX."""
    notional = Decimal("10000")
    for slug in _VENUES:
        adapter = get(slug)
        assert isinstance(adapter, BaseAdapter)
        await adapter.startup()
        try:
            # DOGE mid from venue TOB when listed.
            seed = ReferenceMid(
                snapshot_id="live-seed",
                asset="DOGE",
                mid=Decimal("0.15"),
                mid_source="binance_spot_tob",
                timestamp=datetime.now(tz=UTC),
            )
            tob = await adapter.get_orderbook_spread(
                "DOGE", mid=seed, instrument_type="spot"
            )
            assert tob is not None
            mid = ReferenceMid(
                snapshot_id=f"live-doge-{slug}",
                asset="DOGE",
                mid=tob.mid_local,
                mid_source="binance_spot_tob",
                timestamp=datetime.now(tz=UTC),
            )
            quote = await adapter.get_quote(
                "DOGE", "buy", notional, mid=mid, instrument_type="spot"
            )
            assert quote.status == "ok", (
                f"{slug} DOGE: {quote.status} {quote.error_message}"
            )
        finally:
            await adapter.aclose()

    # QQQ bstock is Binance-spot only in the catalog (Bybit has no bStocks).
    adapter = get("binance")
    assert isinstance(adapter, BaseAdapter)
    await adapter.startup()
    try:
        seed = ReferenceMid(
            snapshot_id="live-seed",
            asset="QQQ",
            mid=Decimal("500"),
            mid_source="binance_spot_tob",
            timestamp=datetime.now(tz=UTC),
        )
        tob = await adapter.get_orderbook_spread(
            "QQQ", mid=seed, instrument_type="spot", form="bstock"
        )
        assert tob is not None
        mid = ReferenceMid(
            snapshot_id="live-qqq-bstock",
            asset="QQQ",
            mid=tob.mid_local,
            mid_source="binance_spot_tob",
            timestamp=datetime.now(tz=UTC),
        )
        quote = await adapter.get_quote(
            "QQQ",
            "buy",
            notional,
            mid=mid,
            instrument_type="spot",
            form="bstock",
        )
        assert quote.status == "ok", (
            f"binance QQQ bstock: {quote.status} {quote.error_message}"
        )
        assert quote.form == "bstock"
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_live_quotes_all_tiers_sides_instruments(slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, BaseAdapter)
    await adapter.startup()
    try:
        mid = await _approx_mid(adapter, slug)
        for instrument in _INSTRUMENTS:
            for side in _SIDES:
                for notional in NOTIONAL_TIERS_USD:
                    quote = await adapter.get_quote(
                        "BTC",
                        side,
                        notional,
                        mid=mid,
                        instrument_type=instrument,
                    )
                    assert isinstance(quote, Quote)
                    assert quote.venue == slug
                    assert quote.asset == "BTC"
                    assert quote.side == side
                    assert quote.notional_usd == notional
                    assert quote.instrument_type == instrument
                    # Small tiers must clear on BTC depth; large may thin out.
                    if notional <= Decimal("10000"):
                        assert quote.status == "ok", (
                            f"{slug} {instrument} {side} N={notional}: "
                            f"status={quote.status!r} msg={quote.error_message!r}"
                        )
                    else:
                        assert quote.status in ("ok", "insufficient_liquidity"), (
                            f"{slug} {instrument} {side} N={notional}: "
                            f"status={quote.status!r} msg={quote.error_message!r}"
                        )
                    if quote.status == "ok":
                        assert quote.effective_price is not None
                        assert quote.spread_bps is not None
                        assert quote.total_cost_bps is not None
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_live_orderbook_spread_spot_and_perp(slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, BaseAdapter)
    await adapter.startup()
    try:
        mid = await _approx_mid(adapter, slug)
        for instrument in _INSTRUMENTS:
            tob = await adapter.get_orderbook_spread(
                "BTC",
                mid=mid,
                instrument_type=instrument,
            )
            assert isinstance(tob, TopOfBook)
            assert tob.venue == slug
            assert tob.instrument_type == instrument
            assert tob.best_ask > tob.best_bid
            assert tob.spread_bps >= 0
    finally:
        await adapter.aclose()
