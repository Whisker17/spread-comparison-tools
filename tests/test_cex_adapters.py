"""CEX adapter unit tests (Binance + Bybit) — offline fixtures (WHI-802)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

import spread_compare.adapters  # noqa: F401 — ensure self-registration
from spread_compare.adapters import get
from spread_compare.adapters._cex_common import OrderbookLevels
from spread_compare.adapters.base import AdapterError, AdapterFetchError
from spread_compare.adapters.cex_binance import BinanceAdapter
from spread_compare.adapters.cex_bybit import BybitAdapter
from spread_compare.models import NOTIONAL_TIERS_USD, Quote, ReferenceMid, TopOfBook

# WHI-799 §4.7 fixture book (symmetric about mid=100_000).
_ASKS: OrderbookLevels = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
_BIDS: OrderbookLevels = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]
_SHALLOW_ASKS: OrderbookLevels = [
    (Decimal("100010"), Decimal("0.01")),
]
_SHALLOW_BIDS: OrderbookLevels = [
    (Decimal("99990"), Decimal("0.01")),
]

_MID = ReferenceMid(
    snapshot_id="snap-cex-test",
    asset="BTC",
    mid=Decimal("100000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)

_VENUES = ("binance", "bybit")


def _patch_book(
    monkeypatch: pytest.MonkeyPatch,
    adapter: BinanceAdapter | BybitAdapter,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
) -> None:
    """Inject a fixed book so get_quote / get_orderbook_spread need no network."""

    async def fake_depth(
        *args: Any, **kwargs: Any
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        return bids, asks

    if isinstance(adapter, BinanceAdapter):
        monkeypatch.setattr(adapter, "_fetch_depth", fake_depth)
        monkeypatch.setattr(adapter, "_fetch_depth_for_walk", fake_depth)
    else:
        monkeypatch.setattr(adapter, "_fetch_orderbook", fake_depth)


@pytest.mark.parametrize("slug", _VENUES)
def test_registry_has_cex_adapters(slug: str) -> None:
    adapter = get(slug)
    assert adapter.venue == slug
    assert adapter.venue_class == "cex"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_quote_buy_canonical_section_4_7(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert isinstance(quote, Quote)
    assert quote.status == "ok"
    assert quote.venue == slug
    assert quote.effective_price == Decimal("100044")
    assert quote.spread_bps == Decimal("4.4")
    assert quote.total_cost_bps == Decimal("14.4")
    assert quote.qty_base == Decimal("0.1")
    assert quote.fee_breakdown.embedded_in_price is False
    assert quote.fee_breakdown.trading_fee_bps == Decimal("10")
    assert quote.fee_breakdown.gas_bps == Decimal("0")
    assert quote.fee_breakdown.explicit_fee_bps == Decimal("10")
    assert quote.instrument_type == "spot"
    assert quote.venue_symbol == "BTCUSDT"
    assert quote.qty_method == "base_from_mid"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_quote_sell_canonical_section_4_7(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote("BTC", "sell", Decimal("10000"), mid=_MID)
    assert quote.status == "ok"
    assert quote.effective_price == Decimal("99956")
    assert quote.spread_bps == Decimal("4.4")


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_insufficient_liquidity(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _SHALLOW_BIDS, _SHALLOW_ASKS)
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert quote.status == "insufficient_liquidity"
    assert quote.effective_price is None
    assert quote.spread_bps is None
    assert quote.total_cost_bps is None
    assert quote.qty_base is None
    assert quote.fee_breakdown.explicit_fee_bps is None
    # Invariants enforced by Quote model construction (would raise if violated).


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_perp_instrument_type(monkeypatch: pytest.MonkeyPatch, slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote(
        "BTC", "buy", Decimal("10000"), mid=_MID, instrument_type="perp"
    )
    assert quote.status == "ok"
    assert quote.instrument_type == "perp"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_unsupported_asset(monkeypatch: pytest.MonkeyPatch, slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    mid = _MID.model_copy(update={"asset": "DOGE"})
    quote = await adapter.get_quote("DOGE", "buy", Decimal("1000"), mid=mid)
    assert quote.status == "unsupported_asset"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_orderbook_spread_spot_and_perp(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)

    tob_spot = await adapter.get_orderbook_spread("BTC", mid=_MID)
    assert isinstance(tob_spot, TopOfBook)
    assert tob_spot.venue == slug
    assert tob_spot.instrument_type == "spot"
    assert tob_spot.best_bid == Decimal("99990")
    assert tob_spot.best_ask == Decimal("100010")
    assert tob_spot.mid_local == Decimal("100000")
    assert tob_spot.spread_bps == Decimal("2")
    assert tob_spot.spread_bps_local == Decimal("2")

    tob_perp = await adapter.get_orderbook_spread(
        "BTC", mid=_MID, instrument_type="perp"
    )
    assert tob_perp is not None
    assert tob_perp.instrument_type == "perp"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_orderbook_spread_fetch_failure_raises(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))

    async def boom(*args: Any, **kwargs: Any) -> tuple[OrderbookLevels, OrderbookLevels]:
        raise AdapterFetchError("injected failure")

    if isinstance(adapter, BinanceAdapter):
        monkeypatch.setattr(adapter, "_fetch_depth", boom)
    else:
        monkeypatch.setattr(adapter, "_fetch_orderbook", boom)

    with pytest.raises(AdapterError):
        await adapter.get_orderbook_spread("BTC", mid=_MID)


@pytest.mark.parametrize("slug", _VENUES)
def test_get_fees_placeholder(slug: str) -> None:
    adapter = get(slug)
    fees = adapter.get_fees("BTC")
    assert fees.venue == slug
    assert fees.taker_bps == Decimal("10")
    assert fees.default_tier == "default_taker"
    assert fees.fee_embedded_in_quote is False
    assert fees.funding_model == "none"
    fees_perp = adapter.get_fees("BTC", instrument_type="perp")
    assert fees_perp.funding_model == "perp_8h"


@pytest.mark.parametrize("slug", _VENUES)
def test_adapters_import_bookwalk_and_costs(slug: str) -> None:
    """Neither adapter reimplements walk/bps — shared modules only."""
    import inspect

    import spread_compare.adapters._cex_common as common_mod
    import spread_compare.adapters.cex_binance as binance_mod
    import spread_compare.adapters.cex_bybit as bybit_mod

    # Common path is the only place that calls walk_book / spread_bps.
    common_src = inspect.getsource(common_mod)
    assert "walk_book" in common_src
    assert "spread_bps" in common_src
    assert "total_cost_bps" in common_src

    for mod in (binance_mod, bybit_mod):
        src = inspect.getsource(mod)
        # Adapters must not redefine the formulas locally.
        assert "def walk_book" not in src
        assert "def spread_bps" not in src
        assert "def total_cost_bps" not in src


@pytest.mark.parametrize("slug", _VENUES)
def test_supported_assets_includes_btc(slug: str) -> None:
    assets = get(slug).supported_assets()
    assert "BTC" in assets
    assert "ETH" in assets
    assert "SOL" in assets


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_mid_asset_mismatch_raises(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, (BinanceAdapter, BybitAdapter))
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    bad_mid = _MID.model_copy(update={"asset": "ETH"})
    with pytest.raises(AdapterError, match="mid.asset"):
        await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=bad_mid)


# Keep NOTIONAL_TIERS_USD referenced so live tests and unit path stay aligned.
assert NOTIONAL_TIERS_USD[0] == Decimal("1000")
