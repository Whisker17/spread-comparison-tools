"""Pull-only quote store + poller (WHI-846)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

import pytest

import spread_compare.adapters  # noqa: F401 — register mock
from spread_compare.adapters.base import BaseAdapter
from spread_compare.adapters.registry import _REGISTRY
from spread_compare.aggregator import QuoteAggregator
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
from spread_compare.poller import (
    PullQuotePoller,
    group_for_venue,
    is_poller_class,
    stamp_stored_quote,
)
from spread_compare.quote_store import QuoteStore, QuoteStoreKey
from spread_compare.settings import (
    AggregatorSettings,
    PollerGroupSettings,
    PollerSettings,
    clear_settings_cache,
    load_poller_settings,
)
from tests.adapter_fakes import DEFAULT_TEST_MID, TEST_MID_SETTINGS, FixedMid

_TS = datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC)
_MID = DEFAULT_TEST_MID.model_copy(
    update={"snapshot_id": "sweep-1", "timestamp": _TS, "asset": "BTC"}
)


def _ok_quote(
    *,
    venue: str = "humidifi",
    side: Side = "buy",
    notional: Decimal = Decimal("10000"),
    mid: ReferenceMid = _MID,
    spread: Decimal = Decimal("5"),
    snapshot_id: str | None = None,
) -> Quote:
    return Quote(
        snapshot_id=snapshot_id or mid.snapshot_id,
        venue=venue,
        asset=mid.asset,
        instrument_type="prop_amm",
        side=side,
        notional_usd=notional,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        effective_price=mid.mid * (Decimal("1") + spread / Decimal("10000")),
        spread_bps=spread,
        total_cost_bps=spread,
        qty_base=notional / mid.mid,
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=Decimal("0"),
            gas_bps=Decimal("0"),
        ),
        timestamp=mid.timestamp,
        status="ok",
    )


def _poller_settings(**group_overrides: object) -> PollerSettings:
    groups = {
        "jupiter": PollerGroupSettings(
            interval_sec=15.0,
            budget_share=0.6,
            max_quote_age_for_best_sec=30.0,
            max_stale_sec=90.0,
        ),
        "kyber": PollerGroupSettings(
            interval_sec=30.0,
            max_rps=2.0,
            max_quote_age_for_best_sec=60.0,
            max_stale_sec=120.0,
        ),
        "rpc": PollerGroupSettings(
            interval_sec=20.0,
            max_rps=5.0,
            max_quote_age_for_best_sec=40.0,
            max_stale_sec=100.0,
        ),
    }
    for k, v in group_overrides.items():
        if k in groups and isinstance(v, PollerGroupSettings):
            groups[k] = v
    return PollerSettings(
        enabled=True,
        poller_served_classes=["amm_dex", "prop_amm"],
        notionals_usd=[
            Decimal("100"),
            Decimal("1000"),
            Decimal("10000"),
            Decimal("100000"),
            Decimal("1000000"),
        ],
        groups=groups,
    )


def test_load_poller_settings_defaults() -> None:
    clear_settings_cache()
    s = load_poller_settings()
    assert s.enabled is True
    assert set(s.poller_served_classes) == {"amm_dex", "prop_amm"}
    assert s.groups["jupiter"].interval_sec == 15.0
    assert s.groups["jupiter"].budget_share == 0.6


def test_group_for_venue_mapping() -> None:
    assert group_for_venue("humidifi", "prop_amm") == "jupiter"
    assert group_for_venue("tessera_bsc", "prop_amm") == "kyber"
    assert group_for_venue("uniswap_eth", "amm_dex") == "rpc"
    assert group_for_venue("binance", "cex") is None


def test_is_poller_class_respects_enabled() -> None:
    enabled = _poller_settings()
    assert is_poller_class("prop_amm", enabled)
    assert is_poller_class("amm_dex", enabled)
    assert not is_poller_class("cex", enabled)
    disabled = enabled.model_copy(update={"enabled": False})
    assert not is_poller_class("prop_amm", disabled)


def test_store_put_get_no_reprice() -> None:
    store = QuoteStore(clock=lambda: 100.0)
    q = _ok_quote(spread=Decimal("5.5"))
    key = QuoteStoreKey(
        venue="humidifi",
        asset="BTC",
        instrument_type="prop_amm",
        notional_usd=Decimal("10000"),
        side="buy",
    )
    store.put(key, q, group="jupiter", success=True, observed_at=_TS)
    got = store.get(key)
    assert got is not None
    assert got.quote.spread_bps == Decimal("5.5")
    assert got.quote.mid == _MID.mid
    # Pairing invariant: stored mid is frozen even if a fresher mid exists.
    fresher = _MID.model_copy(update={"mid": Decimal("200000")})
    assert got.quote.mid != fresher.mid
    assert got.quote.spread_bps == Decimal("5.5")


def test_stamp_stored_quote_age_and_stale() -> None:
    q = _ok_quote()
    fresh = stamp_stored_quote(q, age_sec=10.0, max_quote_age_for_best_sec=30.0)
    assert fresh.quote_stale is False
    assert fresh.age_sec == 10.0
    stale = stamp_stored_quote(q, age_sec=45.0, max_quote_age_for_best_sec=30.0)
    assert stale.quote_stale is True
    assert stale.spread_bps == q.spread_bps  # numbers preserved


class _CountingPropAdapter(BaseAdapter):
    """Prop AMM stub that counts get_quote calls."""

    venue: str = "humidifi"
    venue_class: VenueClass = "prop_amm"
    calls: int = 0

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
        _ = fee_tier, instrument_type
        type(self).calls += 1
        return _ok_quote(
            venue=self.venue,
            side=side,
            notional=notional_usd,
            mid=mid.model_copy(update={"asset": asset.upper()}),
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        _ = asset, mid, instrument_type
        return None

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        _ = asset, instrument_type
        return FeeSchedule(
            venue=self.venue,
            instrument_type="prop_amm",
            fee_embedded_in_quote=True,
            updated_at=_TS,
        )

    def supported_assets(
        self, *, instrument_type: InstrumentType | None = None
    ) -> list[str]:
        _ = instrument_type
        return ["BTC"]


@pytest.fixture
def counting_humidifi() -> Iterator[_CountingPropAdapter]:
    """Replace humidifi with a counting stub; restore after."""
    prev = _REGISTRY.get("humidifi")
    _CountingPropAdapter.calls = 0
    adapter = _CountingPropAdapter()
    _REGISTRY["humidifi"] = adapter
    yield adapter
    if prev is not None:
        _REGISTRY["humidifi"] = prev
    else:
        _REGISTRY.pop("humidifi", None)


@pytest.mark.asyncio
async def test_sweep_one_snapshot_and_mid_per_asset(
    counting_humidifi: _CountingPropAdapter,
) -> None:
    store = QuoteStore()
    settings = _poller_settings()
    # Only sweep one notional to keep the plan small.
    settings = settings.model_copy(update={"notionals_usd": [Decimal("10000")]})
    mids_seen: list[str] = []

    class TrackingMid(FixedMid):
        async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
            mids_seen.append(snapshot_id)
            return await super().resolve(asset, snapshot_id=snapshot_id)

    poller = PullQuotePoller(
        TrackingMid(_MID),
        store=store,
        settings=settings,
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        sleep=lambda _s: None,
    )
    snap = await poller.run_sweep("jupiter")
    assert snap
    assert len(set(mids_seen)) == 1
    assert mids_seen[0] == snap
    # BTC buy+sell at one notional for humidifi (+ other jupiter venues if
    # registered with supported assets). At least humidifi was called.
    assert counting_humidifi.calls >= 2
    key = QuoteStoreKey(
        venue="humidifi",
        asset="BTC",
        instrument_type="prop_amm",
        notional_usd=Decimal("10000"),
        side="buy",
    )
    entry = store.get(key)
    assert entry is not None
    assert entry.quote.snapshot_id == snap
    assert entry.quote.mid == _MID.mid


@pytest.mark.asyncio
async def test_aggregator_reads_store_zero_upstream(
    counting_humidifi: _CountingPropAdapter,
) -> None:
    store = QuoteStore(clock=lambda: 0.0)
    settings = _poller_settings()
    snap = "store-snap"
    mid = _MID.model_copy(update={"snapshot_id": snap})
    for side in ("buy", "sell"):
        store.put(
            QuoteStoreKey(
                venue="humidifi",
                asset="BTC",
                instrument_type="prop_amm",
                notional_usd=Decimal("10000"),
                side=side,  # type: ignore[arg-type]
            ),
            _ok_quote(side=side, mid=mid, snapshot_id=snap),  # type: ignore[arg-type]
            group="jupiter",
            success=True,
            observed_at=_TS,
        )

    calls_before = counting_humidifi.calls
    agg = QuoteAggregator(
        FixedMid(_MID),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store,
        clock=lambda: 5.0,  # age = 5s
    )
    pkg = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["humidifi"],
        use_cache=False,
    )
    assert counting_humidifi.calls == calls_before  # zero upstream
    assert len(pkg.pairs) == 1
    pair = pkg.pairs[0]
    assert pair.venue == "humidifi"
    assert pair.buy is not None
    assert pair.buy.snapshot_id == snap
    assert pair.buy.age_sec == 5.0
    assert pair.buy.quote_stale is False
    assert pair.buy.spread_bps == Decimal("5")


@pytest.mark.asyncio
async def test_pairing_invariant_not_repriced_on_read() -> None:
    store = QuoteStore(clock=lambda: 0.0)
    settings = _poller_settings()
    old_mid = _MID.model_copy(
        update={"snapshot_id": "old-snap", "mid": Decimal("100000")}
    )
    q = _ok_quote(mid=old_mid, spread=Decimal("7.25"), snapshot_id="old-snap")
    store.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="buy",
        ),
        q,
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    # Fresh mid service would return a different mid for package metadata.
    fresh = old_mid.model_copy(
        update={"snapshot_id": "fresh-snap", "mid": Decimal("999999")}
    )
    agg = QuoteAggregator(
        FixedMid(fresh),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store,
        clock=lambda: 1.0,
    )
    pkg = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["humidifi"],
        side="buy",
        use_cache=False,
    )
    buy = pkg.pairs[0].buy
    assert buy is not None
    assert buy.mid == Decimal("100000")  # frozen at sweep
    assert buy.spread_bps == Decimal("7.25")
    assert buy.snapshot_id == "old-snap"


@pytest.mark.asyncio
async def test_stale_marker_after_max_age_for_best() -> None:
    store = QuoteStore(clock=lambda: 0.0)
    settings = _poller_settings()
    store.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="buy",
        ),
        _ok_quote(),
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    agg = QuoteAggregator(
        FixedMid(_MID),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store,
        clock=lambda: 45.0,  # > 30s max_quote_age_for_best
    )
    pkg = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["humidifi"],
        side="buy",
        use_cache=False,
    )
    buy = pkg.pairs[0].buy
    assert buy is not None
    assert buy.status == "ok"
    assert buy.quote_stale is True
    assert buy.age_sec == 45.0
    assert buy.spread_bps is not None  # still visible


@pytest.mark.asyncio
async def test_failed_sweep_keeps_previous_then_expires() -> None:
    mono = {"t": 0.0}

    def clock() -> float:
        return mono["t"]

    store = QuoteStore(clock=clock)
    settings = _poller_settings()
    jup = settings.groups["jupiter"]
    key = QuoteStoreKey(
        venue="humidifi",
        asset="BTC",
        instrument_type="prop_amm",
        notional_usd=Decimal("10000"),
        side="buy",
    )
    good = _ok_quote(spread=Decimal("3"))
    store.put(key, good, group="jupiter", success=True, observed_at=_TS)
    assert store.get(key) is not None

    # Simulate poller failure path: put previous with success=False.
    mono["t"] = 10.0
    store.put(key, good, group="jupiter", success=False, observed_at=_TS)
    entry = store.get(key)
    assert entry is not None
    assert entry.quote.spread_bps == Decimal("3")
    assert entry.last_success_mono == 0.0

    # Past max_stale_sec: poller replaces with error.
    mono["t"] = jup.max_stale_sec + 1
    poller = PullQuotePoller(
        FixedMid(_MID),
        store=store,
        settings=settings,
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        clock=clock,
        wall_clock=lambda: _TS + timedelta(seconds=mono["t"]),
        sleep=lambda _s: None,
    )
    # Drive the private failure path.
    poller._record_failure_from_quote(  # noqa: SLF001
        key,
        Quote(
            snapshot_id=_MID.snapshot_id,
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            side="buy",
            notional_usd=Decimal("10000"),
            mid=_MID.mid,
            mid_source=_MID.mid_source,
            mid_timestamp=_MID.timestamp,
            fee_breakdown=FeeBreakdown(embedded_in_price=True),
            timestamp=_TS,
            status="error",
            error_code="adapter_error",
            error_message="boom",
        ),
        group="jupiter",
        cfg=jup,
        mid=_MID,
    )
    expired = store.get(key)
    assert expired is not None
    assert expired.quote.status == "error"
    assert expired.quote.error_code == "adapter_error"


@pytest.mark.asyncio
async def test_concurrent_collect_same_upstream_count(
    counting_humidifi: _CountingPropAdapter,
) -> None:
    """N concurrent GET /quotes readers do not multiply upstream calls."""
    store = QuoteStore(clock=lambda: 0.0)
    settings = _poller_settings()
    for side in ("buy", "sell"):
        store.put(
            QuoteStoreKey(
                venue="humidifi",
                asset="BTC",
                instrument_type="prop_amm",
                notional_usd=Decimal("10000"),
                side=side,  # type: ignore[arg-type]
            ),
            _ok_quote(side=side),  # type: ignore[arg-type]
            group="jupiter",
            success=True,
            observed_at=_TS,
        )
    before = counting_humidifi.calls
    agg = QuoteAggregator(
        FixedMid(_MID),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store,
        clock=lambda: 1.0,
    )
    await asyncio.gather(
        *[
            agg.collect(
                "BTC",
                Decimal("10000"),
                venues=["humidifi"],
                use_cache=False,
            )
            for _ in range(5)
        ]
    )
    assert counting_humidifi.calls == before


@pytest.mark.asyncio
async def test_mixed_live_and_store_snapshot_ids(
    counting_humidifi: _CountingPropAdapter,
) -> None:
    """Package may mix live snapshot_id with store-backed rows (WHI-846)."""
    store = QuoteStore(clock=lambda: 0.0)
    settings = _poller_settings()
    store_snap = "store-only-snap"
    store.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="buy",
        ),
        _ok_quote(snapshot_id=store_snap, mid=_MID.model_copy(
            update={"snapshot_id": store_snap}
        )),
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    # Use mock venue as live path (cex class, not poller-served).
    agg = QuoteAggregator(
        FixedMid(_MID),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store,
        clock=lambda: 2.0,
    )
    pkg = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["mock", "humidifi"],
        side="buy",
        use_cache=False,
    )
    by_venue = {p.venue: p for p in pkg.pairs}
    assert "mock" in by_venue and "humidifi" in by_venue
    mock_buy = by_venue["mock"].buy
    hum_buy = by_venue["humidifi"].buy
    assert mock_buy is not None and hum_buy is not None
    # Live row uses package snapshot; store row keeps sweep snapshot.
    assert mock_buy.snapshot_id == pkg.snapshot_id
    assert hum_buy.snapshot_id == store_snap
    assert hum_buy.age_sec == 2.0
    assert counting_humidifi.calls == 0


def test_inter_call_delay_respects_budget_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _poller_settings()
    poller = PullQuotePoller(
        FixedMid(_MID),
        store=QuoteStore(),
        settings=settings,
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
    )
    # Keyed: 90 calls / 15s = 6 RPS; budget 0.6 * 10 = 6 → delay ≈ 1/6.
    monkeypatch.setenv("JUPITER_API_KEY", "test-key")
    delay = poller._inter_call_delay(  # noqa: SLF001
        "jupiter", settings.groups["jupiter"], n_calls=90
    )
    assert abs(delay - (1.0 / 6.0)) < 1e-9

    # Keyless: capacity 5 → max 3 RPS → delay ≈ 1/3 (stricter than interval).
    monkeypatch.delenv("JUPITER_API_KEY", raising=False)
    delay_keyless = poller._inter_call_delay(  # noqa: SLF001
        "jupiter", settings.groups["jupiter"], n_calls=90
    )
    assert abs(delay_keyless - (1.0 / 3.0)) < 1e-9


@pytest.mark.asyncio
async def test_freshest_leg_wins_pair_identity() -> None:
    """When buy is stale-kept and sell is fresh, serve the fresh sell (WHI-846)."""
    store = QuoteStore(clock=lambda: 100.0)
    settings = _poller_settings()
    old_mid = _MID.model_copy(update={"snapshot_id": "old-snap", "mid": Decimal("100000")})
    new_mid = _MID.model_copy(update={"snapshot_id": "new-snap", "mid": Decimal("100100")})
    # Stale buy observed earlier.
    store.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="buy",
        ),
        _ok_quote(side="buy", mid=old_mid, snapshot_id="old-snap", spread=Decimal("9")),
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    # Force older observed_mono by writing with a frozen clock then advancing.
    # Re-put buy as failed keep so observed_mono stays low; put sell fresh later.
    mono = {"t": 10.0}
    store2 = QuoteStore(clock=lambda: mono["t"])
    store2.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="buy",
        ),
        _ok_quote(side="buy", mid=old_mid, snapshot_id="old-snap", spread=Decimal("9")),
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    mono["t"] = 50.0
    store2.put(
        QuoteStoreKey(
            venue="humidifi",
            asset="BTC",
            instrument_type="prop_amm",
            notional_usd=Decimal("10000"),
            side="sell",
        ),
        _ok_quote(side="sell", mid=new_mid, snapshot_id="new-snap", spread=Decimal("2")),
        group="jupiter",
        success=True,
        observed_at=_TS,
    )
    agg = QuoteAggregator(
        FixedMid(new_mid),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=2.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
        mid_settings=TEST_MID_SETTINGS,
        poller_settings=settings,
        quote_store=store2,
        clock=lambda: 55.0,
    )
    pkg = await agg.collect(
        "BTC",
        Decimal("10000"),
        venues=["humidifi"],
        use_cache=False,
    )
    pair = pkg.pairs[0]
    assert pair.sell is not None
    assert pair.sell.snapshot_id == "new-snap"
    assert pair.sell.spread_bps == Decimal("2")
    # Buy dropped as foreign snapshot; truthful mismatch, not not_yet_sampled.
    assert pair.buy is not None
    assert pair.buy.status == "error"
    assert pair.buy.error_code == "snapshot_mismatch"


def test_failed_refresh_preserves_observed_mono_for_age() -> None:
    """Failed keep-previous must not reset age (WHI-846 best gate)."""
    mono = {"t": 0.0}
    store = QuoteStore(clock=lambda: mono["t"])
    key = QuoteStoreKey(
        venue="humidifi",
        asset="BTC",
        instrument_type="prop_amm",
        notional_usd=Decimal("10000"),
        side="buy",
    )
    store.put(key, _ok_quote(), group="jupiter", success=True, observed_at=_TS)
    mono["t"] = 40.0
    store.put(key, _ok_quote(), group="jupiter", success=False, observed_at=_TS)
    entry = store.get(key)
    assert entry is not None
    assert entry.observed_mono == 0.0  # not reset to 40
    assert entry.last_success_mono == 0.0
    age = mono["t"] - entry.observed_mono
    stamped = stamp_stored_quote(
        entry.quote, age_sec=age, max_quote_age_for_best_sec=30.0
    )
    assert stamped.quote_stale is True
