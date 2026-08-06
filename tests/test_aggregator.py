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


def test_apply_mid_stale_ws_book_uses_tighter_threshold() -> None:
    """WHI-847: raw_ref=ws_book applies max_age_for_ws_quote_sec (tighter)."""
    # 3s delta: under default stale_threshold_sec=5, over ws max 2s.
    base = error_quote(
        mid=_MID,
        venue="binance",
        asset="BTC",
        side="buy",
        notional_usd=Decimal("10000"),
        instrument_type="spot",
        error_code="x",
        error_message="y",
        timestamp=_MID.timestamp + timedelta(seconds=3),
    )
    ws = base.model_copy(update={"raw_ref": "ws_book", "age_sec": 0.05})
    loose = apply_mid_stale(ws, stale_threshold_sec=5.0, ws_mid_max_age_sec=2.0)
    assert loose.mid_stale is True
    # TOB degradation appends ";tob_error:…" — still WS-served.
    ws_tob = base.model_copy(
        update={"raw_ref": "ws_book;tob_error:x:y", "age_sec": 0.05}
    )
    assert (
        apply_mid_stale(ws_tob, stale_threshold_sec=5.0, ws_mid_max_age_sec=2.0).mid_stale
        is True
    )
    # WHI-846 store row: age_sec set but no ws_book marker → keep 5s threshold.
    store = base.model_copy(update={"raw_ref": None, "age_sec": 12.0})
    assert (
        apply_mid_stale(store, stale_threshold_sec=5.0, ws_mid_max_age_sec=2.0).mid_stale
        is False
    )


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
            venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=0
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
            venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=0
        ),
    )
    with pytest.raises(InvalidNotionalError):
        await agg.collect("BTC", Decimal("12345"), venues=["mock"], use_cache=False)


@pytest.mark.asyncio
async def test_collect_mid_failure_propagates() -> None:
    agg = QuoteAggregator(
        FixedMid(fail=True),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=0
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
            venue_timeout_sec=0.05,
            venue_timeout_by_class={}, response_cache_ttl_sec=0.0
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
            form: str | None = None,
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
            form: str | None = None,
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
            form: str | None = None,
        ) -> list[str]:
            return ["BTC"]

    _REGISTRY[_TIMEOUT_SLUG] = _QuoteOkTobBoom()
    agg = QuoteAggregator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=0.0
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
            venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=2.0
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


@pytest.mark.asyncio
async def test_response_cache_second_request_zero_upstream_within_ttl() -> None:
    """WHI-844: within TTL, a second identical collect issues zero mid/upstream work."""
    mid_calls = {"n": 0}
    quote_calls = {"n": 0}

    class CountingMid(FixedMid):
        async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
            mid_calls["n"] += 1
            return await super().resolve(asset, snapshot_id=snapshot_id)

    class CountingMock(BaseAdapter):
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
            quote_calls["n"] += 1
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
            form: str | None = None,
        ) -> TopOfBook | None:
            return None

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
            form: str | None = None,
        ) -> list[str]:
            return ["BTC"]

    previous = _REGISTRY.get("mock")
    _REGISTRY["mock"] = CountingMock()
    try:
        clock = {"t": 0.0}
        agg = QuoteAggregator(
            CountingMid(),
            aggregator_settings=AggregatorSettings(
                venue_timeout_sec=3.0,
                venue_timeout_by_class={},
                response_cache_ttl_sec=35.0,
            ),
            clock=lambda: clock["t"],
        )
        await agg.collect("BTC", Decimal("10000"), venues=["mock"])
        mid_after_first = mid_calls["n"]
        quote_after_first = quote_calls["n"]
        assert mid_after_first == 1
        assert quote_after_first >= 1
        clock["t"] = 30.0  # still inside 35s TTL (matches FE poll interval)
        await agg.collect("BTC", Decimal("10000"), venues=["mock"])
        assert mid_calls["n"] == mid_after_first
        assert quote_calls["n"] == quote_after_first
    finally:
        if previous is None:
            _REGISTRY.pop("mock", None)
        else:
            _REGISTRY["mock"] = previous


@pytest.mark.asyncio
async def test_concurrent_identical_collect_single_flight() -> None:
    """WHI-844: two concurrent identical requests share one upstream fan-out."""
    import asyncio

    mid_calls = {"n": 0}
    gate = asyncio.Event()
    entered = asyncio.Event()

    class SlowMid(FixedMid):
        async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
            mid_calls["n"] += 1
            entered.set()
            await gate.wait()
            return await super().resolve(asset, snapshot_id=snapshot_id)

    agg = QuoteAggregator(
        SlowMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=35.0,
        ),
    )

    t1 = asyncio.create_task(agg.collect("BTC", Decimal("10000"), venues=["mock"]))
    await entered.wait()
    t2 = asyncio.create_task(agg.collect("BTC", Decimal("10000"), venues=["mock"]))
    # Second caller should attach to in-flight, not start another mid resolve.
    await asyncio.sleep(0.05)
    assert mid_calls["n"] == 1
    gate.set()
    p1, p2 = await asyncio.gather(t1, t2)
    assert p1.snapshot_id == p2.snapshot_id
    assert mid_calls["n"] == 1


@pytest.mark.asyncio
async def test_rate_limited_fail_fast_under_budget() -> None:
    """WHI-844: real limiter wait that exceeds budget returns rate_limited under timeout."""
    import time

    from spread_compare.budget import acquire_within_budget
    from spread_compare.ratelimit import TokenBucketRateLimiter

    class LimiterBlockedAdapter(BaseAdapter):
        venue: str = _TIMEOUT_SLUG
        venue_class: VenueClass = "cex"

        def __init__(self) -> None:
            super().__init__()
            # Capacity 1, 10s window; empty the bucket so acquire waits ~10s.
            self._limiter = TokenBucketRateLimiter(capacity=1, window_s=10.0)
            self._limiter.observe_remaining(0)

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
            # Budget-aware acquire only — must not sleep past the quote deadline.
            await acquire_within_budget(self._limiter, venue=self.venue)
            raise AssertionError("should have failed on acquire_within_budget")

        async def get_orderbook_spread(
            self,
            asset: str,
            *,
            mid: ReferenceMid,
            instrument_type: Literal["spot", "perp"] | None = None,
            form: str | None = None,
        ) -> TopOfBook | None:
            return None

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
            form: str | None = None,
        ) -> list[str]:
            return ["BTC"]

    previous = _REGISTRY.get(_TIMEOUT_SLUG)
    _REGISTRY[_TIMEOUT_SLUG] = LimiterBlockedAdapter()
    try:
        budget = 0.25
        agg = QuoteAggregator(
            FixedMid(),
            aggregator_settings=AggregatorSettings(
                venue_timeout_sec=budget,
                venue_timeout_by_class={},
                response_cache_ttl_sec=0.0,
            ),
        )
        t0 = time.monotonic()
        package = await agg.collect(
            "BTC",
            Decimal("10000"),
            venues=[_TIMEOUT_SLUG],
            use_cache=False,
        )
        elapsed = time.monotonic() - t0
        pair = package.pairs[0]
        assert pair.buy is not None
        assert pair.buy.status == "rate_limited"
        assert pair.buy.error_code == "rate_limited"
        assert pair.sell is not None
        assert pair.sell.status == "rate_limited"
        # Must finish well under the budget (fail-fast, not sleep-to-timeout).
        assert elapsed < budget * 0.9, f"elapsed {elapsed:.3f}s not fail-fast"
    finally:
        if previous is None:
            _REGISTRY.pop(_TIMEOUT_SLUG, None)
        else:
            _REGISTRY[_TIMEOUT_SLUG] = previous


def test_nvda_form_venue_expansion_multi_form() -> None:
    """WHI-881: tessera_bsc appears for both bstock and ondo; forms share mid identity."""
    from spread_compare.aggregator import venues_for_form_expansion
    from spread_compare.assets import live_forms

    forms = {f.id for f in live_forms("NVDA")}
    assert forms == {"perp", "bstock", "ondo"}

    venues = ["tessera_bsc", "pancakeswap_bsc", "binance", "hyperliquid", "bybit"]
    bstock = venues_for_form_expansion("NVDA", "bstock", venues)
    ondo = venues_for_form_expansion("NVDA", "ondo", venues)
    perp = venues_for_form_expansion("NVDA", "perp", venues)

    assert bstock == ["tessera_bsc", "pancakeswap_bsc", "binance"]
    assert ondo == ["tessera_bsc", "pancakeswap_bsc"]
    assert set(perp) == {"binance", "hyperliquid", "bybit"}
    # Dual form at one venue (acceptance: two distinct tessera_bsc rows).
    assert "tessera_bsc" in bstock and "tessera_bsc" in ondo

    # Crypto single-form expansion is unchanged (all requested venues).
    crypto = venues_for_form_expansion("BTC", None, venues)
    assert crypto == venues
