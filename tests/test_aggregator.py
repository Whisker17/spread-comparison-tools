"""Aggregator unit tests: fan-out, degradation, SizeQuotePair assembly (WHI-807)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Literal

import pytest

import spread_compare.adapters  # noqa: F401 — register mock
from spread_compare.adapters.base import BaseAdapter
from spread_compare.adapters.registry import _REGISTRY
from spread_compare.aggregator import (
    InvalidNotionalError,
    QuoteAggregator,
    apply_mid_stale,
    assemble_pair,
    error_quote,
)
from spread_compare.mids import MidResolutionError
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
from spread_compare.settings import AggregatorSettings
from tests.adapter_fakes import DEFAULT_TEST_MID, FixedMid, SlowAdapter

_MID = DEFAULT_TEST_MID.model_copy(update={"snapshot_id": "snap-agg"})


def test_apply_mid_stale() -> None:
    q = error_quote(
        mid=_MID,
        venue="mock",
        asset="BTC",
        side="buy",
        notional_usd=Decimal("10000"),
        instrument_type="spot",
        error_code="x",
        error_message="y",
        timestamp=_MID.timestamp + timedelta(seconds=10),
    )
    stamped = apply_mid_stale(q, stale_threshold_sec=5)
    assert stamped.mid_stale is True
    assert stamped.status == "error"


def test_assemble_pair_round_trip_from_ok_legs() -> None:
    fees = FeeBreakdown(
        embedded_in_price=False,
        trading_fee_bps=Decimal("10"),
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=Decimal("10"),
    )
    buy = Quote(
        snapshot_id=_MID.snapshot_id,
        venue="mock",
        asset="BTC",
        instrument_type="spot",
        side="buy",
        notional_usd=Decimal("10000"),
        mid=_MID.mid,
        mid_source=_MID.mid_source,
        mid_timestamp=_MID.timestamp,
        effective_price=Decimal("100044"),
        spread_bps=Decimal("4.4"),
        fee_breakdown=fees,
        total_cost_bps=Decimal("14.4"),
        timestamp=_MID.timestamp,
        status="ok",
        qty_base=Decimal("0.1"),
        qty_method="base_from_mid",
    )
    sell = buy.model_copy(
        update={
            "side": "sell",
            "effective_price": Decimal("99956"),
            "spread_bps": Decimal("4.4"),
            "total_cost_bps": Decimal("14.4"),
        }
    )
    pair = assemble_pair(
        mid=_MID,
        venue="mock",
        asset="BTC",
        instrument_type="spot",
        notional_usd=Decimal("10000"),
        buy=buy,
        sell=sell,
        top_of_book=None,
        stale_threshold_sec=5,
    )
    assert pair.round_trip_spread_bps == Decimal("8.8")
    assert pair.half_spread_bps == Decimal("4.4")
    assert pair.round_trip_total_cost_bps == Decimal("28.8")


@pytest.mark.asyncio
async def test_collect_happy_path_mock() -> None:
    agg = QuoteAggregator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0, response_cache_ttl_sec=0
        ),
    )
    package = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["mock"],
        snapshot_id="snap-happy",
        use_cache=False,
    )
    assert package.snapshot_id == "snap-happy"
    assert package.mid.mid == Decimal("100000")
    assert len(package.pairs) == 1
    pair = package.pairs[0]
    assert pair.venue == "mock"
    assert pair.buy is not None and pair.buy.status == "ok"
    assert pair.sell is not None and pair.sell.status == "ok"
    assert pair.buy.snapshot_id == pair.sell.snapshot_id == "snap-happy"
    assert pair.buy.mid == pair.sell.mid == package.mid.mid
    assert pair.buy.mid_source == pair.sell.mid_source == package.mid.mid_source
    assert pair.round_trip_spread_bps == Decimal("8.8")
    assert pair.top_of_book is not None


@pytest.mark.asyncio
async def test_collect_invalid_notional() -> None:
    agg = QuoteAggregator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0, response_cache_ttl_sec=0
        ),
    )
    with pytest.raises(InvalidNotionalError):
        await agg.collect("BTC", Decimal("12345"), venues=["mock"], use_cache=False)


@pytest.mark.asyncio
async def test_collect_mid_failure_propagates() -> None:
    agg = QuoteAggregator(
        FixedMid(fail=True),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0, response_cache_ttl_sec=0
        ),
    )
    with pytest.raises(MidResolutionError):
        await agg.collect("BTC", Decimal("10000"), venues=["mock"], use_cache=False)


# --- timeout injection via a temporary second adapter ---

_TIMEOUT_SLUG = "binance"  # WHI-799 slug; not normally registered until real adapter lands


@pytest.fixture
def slow_binance_adapter() -> Iterator[None]:
    """Temporarily park a slow adapter under the binance slug, then restore."""
    previous = _REGISTRY.get(_TIMEOUT_SLUG)
    _REGISTRY[_TIMEOUT_SLUG] = SlowAdapter()
    try:
        yield
    finally:
        if previous is None:
            _REGISTRY.pop(_TIMEOUT_SLUG, None)
        else:
            _REGISTRY[_TIMEOUT_SLUG] = previous


@pytest.mark.asyncio
async def test_single_venue_timeout_degrades_to_error(
    slow_binance_adapter: None,
) -> None:
    agg = QuoteAggregator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=0.05, response_cache_ttl_sec=0.0
        ),
    )
    package = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["mock", _TIMEOUT_SLUG],
        use_cache=False,
    )
    by_venue = {p.venue: p for p in package.pairs}
    assert by_venue["mock"].buy is not None
    assert by_venue["mock"].buy.status == "ok"
    assert by_venue[_TIMEOUT_SLUG].buy is not None
    assert by_venue[_TIMEOUT_SLUG].buy.status == "error"
    assert by_venue[_TIMEOUT_SLUG].buy.error_code == "timeout"
    assert by_venue[_TIMEOUT_SLUG].sell is not None
    assert by_venue[_TIMEOUT_SLUG].sell.status == "error"


@pytest.mark.asyncio
async def test_orderbook_tob_failure_stamps_raw_ref(
    slow_binance_adapter: None,
) -> None:
    """CEX TOB failure must not look like AMM None — stamp raw_ref on ok legs."""

    class _QuoteOkTobBoom(BaseAdapter):
        venue: str = _TIMEOUT_SLUG
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
        ) -> Quote:
            from spread_compare.models import FeeBreakdown

            fees = FeeBreakdown(
                embedded_in_price=False,
                trading_fee_bps=Decimal("10"),
                platform_fee_bps=Decimal("0"),
                gas_unknown=False,
                explicit_fee_bps=Decimal("10"),
            )
            return Quote(
                snapshot_id=mid.snapshot_id,
                venue=self.venue,
                asset=asset.upper(),
                instrument_type=instrument_type or "spot",
                side=side,
                notional_usd=notional_usd,
                mid=mid.mid,
                mid_source=mid.mid_source,
                mid_timestamp=mid.timestamp,
                effective_price=mid.mid,
                spread_bps=Decimal("0"),
                fee_breakdown=fees,
                total_cost_bps=Decimal("10"),
                timestamp=mid.timestamp,
                status="ok",
                qty_base=notional_usd / mid.mid,
                qty_method="base_from_mid",
            )

        async def get_orderbook_spread(
            self,
            asset: str,
            *,
            mid: ReferenceMid,
            instrument_type: Literal["spot", "perp"] | None = None,
        ) -> TopOfBook | None:
            from spread_compare.adapters.base import AdapterFetchError

            raise AdapterFetchError("book down")

        def get_fees(
            self,
            asset: str | None = None,
            *,
            instrument_type: InstrumentType | None = None,
        ) -> FeeSchedule:
            raise NotImplementedError

        def supported_assets(
            self,
            *,
            instrument_type: InstrumentType | None = None,
        ) -> list[str]:
            return ["BTC"]

    _REGISTRY[_TIMEOUT_SLUG] = _QuoteOkTobBoom()
    agg = QuoteAggregator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0, response_cache_ttl_sec=0.0
        ),
    )
    package = await agg.collect(
        "BTC", Decimal("10000"), venues=[_TIMEOUT_SLUG], use_cache=False
    )
    pair = package.pairs[0]
    assert pair.top_of_book is None
    assert pair.buy is not None and pair.buy.status == "ok"
    assert pair.buy.raw_ref is not None and pair.buy.raw_ref.startswith("tob_error:")
    assert pair.sell is not None and pair.sell.raw_ref is not None


@pytest.mark.asyncio
async def test_response_cache_hits() -> None:
    calls = {"n": 0}

    class CountingMid(FixedMid):
        async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
            calls["n"] += 1
            return await super().resolve(asset, snapshot_id=snapshot_id)

    clock = {"t": 0.0}
    agg = QuoteAggregator(
        CountingMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0, response_cache_ttl_sec=2.0
        ),
        clock=lambda: clock["t"],
    )
    p1 = await agg.collect("BTC", Decimal("10000"), venues=["mock"])
    p2 = await agg.collect("BTC", Decimal("10000"), venues=["mock"])
    assert p1.snapshot_id == p2.snapshot_id
    assert calls["n"] == 1
    clock["t"] = 3.0
    p3 = await agg.collect("BTC", Decimal("10000"), venues=["mock"])
    assert calls["n"] == 2
    assert p3.snapshot_id != p1.snapshot_id
