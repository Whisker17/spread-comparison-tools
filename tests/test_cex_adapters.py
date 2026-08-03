"""CEX adapter unit tests (Binance + Bybit) — offline fixtures (WHI-802)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

import spread_compare.adapters  # noqa: F401 — ensure self-registration
from spread_compare.adapters import get
from spread_compare.adapters._cex_common import CexBaseAdapter, OrderbookLevels
from spread_compare.adapters.base import AdapterError, AdapterFetchError
from spread_compare.adapters.cex_binance import BinanceAdapter
from spread_compare.adapters.cex_bybit import BybitAdapter
from spread_compare.models import Quote, ReferenceMid, TopOfBook

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
    adapter: CexBaseAdapter,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
) -> None:
    """Inject a fixed book so get_quote / get_orderbook_spread need no network."""

    async def fake_book(
        *args: Any, **kwargs: Any
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        return bids, asks

    monkeypatch.setattr(adapter, "_fetch_book", fake_book)


@pytest.mark.parametrize("slug", _VENUES)
def test_registry_has_cex_adapters(slug: str) -> None:
    adapter = get(slug)
    assert adapter.venue == slug
    assert adapter.venue_class == "cex"
    assert isinstance(adapter, CexBaseAdapter)


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_quote_buy_canonical_section_4_7(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
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
    assert isinstance(adapter, CexBaseAdapter)
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
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _SHALLOW_BIDS, _SHALLOW_ASKS)
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert quote.status == "insufficient_liquidity"
    assert quote.effective_price is None
    assert quote.spread_bps is None
    assert quote.total_cost_bps is None
    assert quote.qty_base is None
    assert quote.fee_breakdown.explicit_fee_bps is None
    assert quote.fee_breakdown.gas_bps == Decimal("0")


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_perp_instrument_type(monkeypatch: pytest.MonkeyPatch, slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote(
        "BTC", "buy", Decimal("10000"), mid=_MID, instrument_type="perp"
    )
    assert quote.status == "ok"
    assert quote.instrument_type == "perp"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_fee_tier_label_echoed(monkeypatch: pytest.MonkeyPatch, slug: str) -> None:
    """fee_tier is labelled on the quote; Phase 1 bps stay default_taker (WHI-799 §11 Q3)."""
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote(
        "BTC", "buy", Decimal("10000"), mid=_MID, fee_tier="vip1"
    )
    assert quote.status == "ok"
    assert quote.fee_breakdown.fee_tier == "vip1"
    # Spot default_taker remains 10 bps even when vip1 label is echoed.
    assert quote.fee_breakdown.trading_fee_bps == Decimal("10")


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_unsupported_asset(monkeypatch: pytest.MonkeyPatch, slug: str) -> None:
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
    mid = _MID.model_copy(update={"asset": "DOGE"})
    quote = await adapter.get_quote("DOGE", "buy", Decimal("1000"), mid=mid)
    assert quote.status == "unsupported_asset"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_invalid_instrument_type_is_error(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote(
        "BTC", "buy", Decimal("1000"), mid=_MID, instrument_type="amm_pool"
    )
    assert quote.status == "error"
    assert quote.error_code == "unsupported_instrument_type"


@pytest.mark.parametrize("slug", _VENUES)
@pytest.mark.asyncio
async def test_get_orderbook_spread_spot_and_perp(
    monkeypatch: pytest.MonkeyPatch, slug: str
) -> None:
    adapter = get(slug)
    assert isinstance(adapter, CexBaseAdapter)
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
    assert isinstance(adapter, CexBaseAdapter)

    async def boom(*args: Any, **kwargs: Any) -> tuple[OrderbookLevels, OrderbookLevels]:
        raise AdapterFetchError("injected failure")

    monkeypatch.setattr(adapter, "_fetch_book", boom)

    with pytest.raises(AdapterError):
        await adapter.get_orderbook_spread("BTC", mid=_MID)


@pytest.mark.parametrize("slug", _VENUES)
def test_get_fees_config_backed(slug: str) -> None:
    adapter = get(slug)
    fees = adapter.get_fees("BTC")
    assert fees.venue == slug
    assert fees.asset == "BTC"
    assert fees.taker_bps == Decimal("10")  # spot default_taker
    assert fees.default_tier == "default_taker"
    assert fees.fee_embedded_in_quote is False
    assert fees.funding_model == "none"
    assert fees.source_urls
    fees_perp = adapter.get_fees("BTC", instrument_type="perp")
    assert fees_perp.funding_model == "perp_8h"
    assert fees_perp.taker_bps is not None
    assert fees_perp.taker_bps > 0


def test_adapters_import_bookwalk_and_costs() -> None:
    """Neither adapter reimplements walk/bps — shared modules only."""
    import inspect

    import spread_compare.adapters._cex_common as common_mod
    import spread_compare.adapters.cex_binance as binance_mod
    import spread_compare.adapters.cex_bybit as bybit_mod

    common_src = inspect.getsource(common_mod)
    assert "walk_book" in common_src
    assert "spread_bps" in common_src
    assert "total_cost_bps" in common_src

    for mod in (binance_mod, bybit_mod):
        src = inspect.getsource(mod)
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
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    bad_mid = _MID.model_copy(update={"asset": "ETH"})
    with pytest.raises(AdapterError, match="mid.asset"):
        await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=bad_mid)


@pytest.mark.asyncio
async def test_quote_uses_fee_schedule_taker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """trading_fee_bps comes from get_fees().taker_bps, not a parallel constant."""
    adapter = get("binance")
    assert isinstance(adapter, BinanceAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)

    def custom_fees(*args: Any, **kwargs: Any) -> Any:
        base = CexBaseAdapter.get_fees(adapter, "BTC")
        return base.model_copy(update={"taker_bps": Decimal("7.5")})

    monkeypatch.setattr(adapter, "get_fees", custom_fees)
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert quote.status == "ok"
    assert quote.fee_breakdown.trading_fee_bps == Decimal("7.5")
    assert quote.total_cost_bps == Decimal("11.9")  # 4.4 + 7.5


@pytest.mark.asyncio
async def test_cex_perp_quote_uses_config_taker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Perp trading_fee_bps match config/fees default_taker (not spot 10 bps)."""
    adapter = get("binance")
    assert isinstance(adapter, CexBaseAdapter)
    _patch_book(monkeypatch, adapter, _BIDS, _ASKS)
    quote = await adapter.get_quote(
        "BTC", "buy", Decimal("10000"), mid=_MID, instrument_type="perp"
    )
    assert quote.status == "ok"
    assert quote.instrument_type == "perp"
    assert quote.fee_breakdown.trading_fee_bps == Decimal("5")
    assert quote.total_cost_bps == Decimal("9.4")  # 4.4 + 5

    bybit = get("bybit")
    assert isinstance(bybit, CexBaseAdapter)
    _patch_book(monkeypatch, bybit, _BIDS, _ASKS)
    bq = await bybit.get_quote(
        "BTC", "buy", Decimal("10000"), mid=_MID, instrument_type="perp"
    )
    assert bq.status == "ok"
    assert bq.fee_breakdown.trading_fee_bps == Decimal("5.5")
    assert bq.total_cost_bps == Decimal("9.9")  # 4.4 + 5.5


@pytest.mark.asyncio
async def test_binance_depth_escalation_on_shallow_first_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When limit=100 walks short, Binance escalates to deeper limits."""
    adapter = get("binance")
    assert isinstance(adapter, BinanceAdapter)
    calls: list[int] = []

    async def fake_depth(
        symbol: str, book_side: str, *, limit: int
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        calls.append(limit)
        if limit < 500:
            return _SHALLOW_BIDS, _SHALLOW_ASKS
        return _BIDS, _ASKS

    monkeypatch.setattr(adapter, "_fetch_depth", fake_depth)
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert quote.status == "ok"
    assert quote.spread_bps == Decimal("4.4")
    assert 100 in calls
    assert 500 in calls


def test_bybit_is_bybit_adapter() -> None:
    assert isinstance(get("bybit"), BybitAdapter)


@pytest.mark.asyncio
async def test_request_json_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline coverage for CexBaseAdapter._request_json 429 backoff path."""
    adapter = BinanceAdapter()
    # Skip min-interval waits.
    monkeypatch.setattr(adapter._limiter, "acquire", _async_noop)

    attempts = {"n": 0}

    class FakeResp:
        def __init__(self, status_code: int, body: dict[str, object]) -> None:
            self.status_code = status_code
            self.headers: dict[str, str] = {"x-mbx-used-weight-1m": "10"}
            self.text = str(body)
            self._body = body

        def json(self) -> dict[str, object]:
            return self._body

    class FakeHttp:
        async def get(
            self, url: str, params: dict[str, str] | None = None
        ) -> FakeResp:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return FakeResp(429, {"error": "rate"})
            return FakeResp(200, {"bids": [["1", "1"]], "asks": [["2", "1"]]})

        async def aclose(self) -> None:
            return None

    adapter._client = FakeHttp()  # type: ignore[assignment]
    monkeypatch.setattr(adapter, "_max_retries", 4)
    monkeypatch.setattr(adapter, "_backoff_start_s", 0.0)

    data = await adapter._request_json(
        "https://example.test/depth", {"symbol": "BTCUSDT"}
    )
    assert data["bids"] == [["1", "1"]]
    assert attempts["n"] == 3
    await adapter.aclose()


async def _async_noop() -> None:
    return None
