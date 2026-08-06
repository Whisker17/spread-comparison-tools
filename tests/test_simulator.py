"""Unit tests for TradeSimulator pure helpers and fan-out (WHI-814)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Literal

import pytest

import spread_compare.adapters  # noqa: F401 — register mock
from spread_compare.adapters.base import BaseAdapter
from spread_compare.adapters.registry import _REGISTRY
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
from spread_compare.simulator import (
    InvalidSimulateAmountError,
    InvalidSimulatePairError,
    TradeSimulator,
    amount_to_notional_usd,
    expected_output_from_quote,
    rank_and_flag_best,
    resolve_simulate_pair,
)
from spread_compare.simulator import SimulateRow as SimRow
from tests.adapter_fakes import DEFAULT_TEST_MID, FixedMid, SlowAdapter

_MID = DEFAULT_TEST_MID.model_copy(update={"snapshot_id": "snap-sim"})

_TEST_AGG = AggregatorSettings(venue_timeout_sec=3.0,
            venue_timeout_by_class={}, response_cache_ttl_sec=0.0)


def test_resolve_pair_sell_non_stable() -> None:
    pair = resolve_simulate_pair("BTC", "USDC")
    assert pair.asset == "BTC"
    assert pair.side == "sell"
    assert pair.stable_leg == "USDC"


def test_resolve_pair_buy_non_stable() -> None:
    pair = resolve_simulate_pair("USDT", "SOL")
    assert pair.asset == "SOL"
    assert pair.side == "buy"
    assert pair.stable_leg == "USDT"


def test_resolve_pair_unknown_asset() -> None:
    with pytest.raises(InvalidSimulatePairError, match="unknown asset") as exc:
        resolve_simulate_pair("NOTACOIN", "USDC")
    assert exc.value.reason == "unknown_asset"


def test_resolve_pair_cross_pair_distinguished_from_unknown() -> None:
    with pytest.raises(InvalidSimulatePairError, match="cross pair") as exc:
        resolve_simulate_pair("WETH", "cbBTC")
    assert exc.value.reason == "cross_pair"
    # Message must not look like a catalog miss for known non-stables.
    assert "unknown asset" not in str(exc.value).lower()


def test_resolve_pair_both_stable() -> None:
    with pytest.raises(InvalidSimulatePairError) as exc:
        resolve_simulate_pair("USDC", "USDT")
    assert exc.value.reason == "cross_pair"


def test_amount_to_notional_sell_base() -> None:
    pair = resolve_simulate_pair("BTC", "USDC")
    # Free-form: 0.5 BTC × 100_000 = 50_000 (not a WHI-799 tier).
    n = amount_to_notional_usd(Decimal("0.5"), pair=pair, mid=Decimal("100000"))
    assert n == Decimal("50000")


def test_amount_to_notional_sell_stable() -> None:
    pair = resolve_simulate_pair("USDC", "BTC")
    n = amount_to_notional_usd(Decimal("12345.67"), pair=pair, mid=Decimal("100000"))
    assert n == Decimal("12345.67")


def test_amount_rejects_non_positive() -> None:
    pair = resolve_simulate_pair("BTC", "USDC")
    with pytest.raises(InvalidSimulateAmountError):
        amount_to_notional_usd(Decimal("0"), pair=pair, mid=Decimal("1"))


def test_expected_output_sell_and_buy_inverted() -> None:
    fees = FeeBreakdown(
        embedded_in_price=False,
        trading_fee_bps=Decimal("10"),
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=Decimal("10"),
    )
    sell_q = Quote(
        snapshot_id=_MID.snapshot_id,
        venue="mock",
        asset="BTC",
        instrument_type="spot",
        side="sell",
        notional_usd=Decimal("10000"),
        mid=_MID.mid,
        mid_source=_MID.mid_source,
        mid_timestamp=_MID.timestamp,
        effective_price=Decimal("99956"),
        spread_bps=Decimal("4.4"),
        fee_breakdown=fees,
        total_cost_bps=Decimal("14.4"),
        timestamp=_MID.timestamp,
        status="ok",
        qty_base=Decimal("0.1"),
        qty_method="base_from_mid",
    )
    # Selling 0.1 BTC @ 99956 → 9995.6 USDC out.
    assert expected_output_from_quote(sell_q, side="sell") == Decimal("9995.6")

    buy_q = sell_q.model_copy(
        update={"side": "buy", "effective_price": Decimal("100044")}
    )
    # Buying: base out = notional / effective_price (not mid-sized qty_base).
    assert expected_output_from_quote(buy_q, side="buy") == (
        Decimal("10000") / Decimal("100044")
    )


def test_rank_gas_unknown_high_output_not_best() -> None:
    """§5.2: highest expected_output with gas_unknown must not be best."""
    fees_ok = FeeBreakdown(
        embedded_in_price=False,
        trading_fee_bps=Decimal("10"),
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=Decimal("10"),
    )
    fees_gas = FeeBreakdown(
        embedded_in_price=True,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=True,
        explicit_fee_bps=None,
    )
    ts = _MID.timestamp
    gas_row = SimRow(
        venue="amm_gas_unknown",
        venue_symbol="BTC/USDC",
        instrument_type="amm_pool",
        expected_output=Decimal("10000"),
        effective_price=Decimal("100000"),
        spread_bps=Decimal("1"),
        fee_breakdown=fees_gas,
        total_cost_bps=None,
        timestamp=ts,
        status="ok",
    )
    ok_row = SimRow(
        venue="cex_ok",
        venue_symbol="BTCUSDT",
        instrument_type="spot",
        expected_output=Decimal("9990"),
        effective_price=Decimal("99900"),
        spread_bps=Decimal("4"),
        fee_breakdown=fees_ok,
        total_cost_bps=Decimal("14"),
        timestamp=ts,
        status="ok",
    )
    ranked = rank_and_flag_best([gas_row, ok_row])
    assert ranked[0].venue == "amm_gas_unknown"
    assert ranked[0].best is False
    assert ranked[1].venue == "cex_ok"
    assert ranked[1].best is True


@pytest.mark.asyncio
async def test_simulate_both_directions_mock() -> None:
    sim = TradeSimulator(FixedMid(_MID), aggregator_settings=_TEST_AGG)
    sell_pkg = await sim.simulate(
        "BTC", "USDC", Decimal("0.1"), venues=["mock"], snapshot_id="snap-sell"
    )
    assert sell_pkg.side == "sell"
    assert sell_pkg.notional_usd == Decimal("10000")  # 0.1 * 100000
    assert sell_pkg.snapshot_id == "snap-sell"
    sell_row = next(r for r in sell_pkg.rows if r.venue == "mock")
    assert sell_row.status == "ok"
    assert sell_row.effective_price is not None
    assert sell_row.expected_output is not None
    # sell: qty_base * P_star ≈ 0.1 * 99956 = 9995.6
    assert sell_row.expected_output == Decimal("0.1") * sell_row.effective_price
    assert sell_row.best is True
    assert sell_row.total_cost_bps is not None

    buy_pkg = await sim.simulate(
        "USDC", "BTC", Decimal("10000"), venues=["mock"], snapshot_id="snap-buy"
    )
    assert buy_pkg.side == "buy"
    assert buy_pkg.notional_usd == Decimal("10000")
    buy_row = next(r for r in buy_pkg.rows if r.venue == "mock")
    assert buy_row.status == "ok"
    assert buy_row.effective_price is not None
    assert buy_row.expected_output == Decimal("10000") / buy_row.effective_price
    # Price semantics inverted vs sell.
    assert sell_row.effective_price is not None
    assert buy_row.effective_price > sell_row.effective_price


@pytest.mark.asyncio
async def test_simulate_free_form_notional_not_snapped() -> None:
    """Off-tier notional must pass through (0.123 BTC → $12_300)."""
    sim = TradeSimulator(FixedMid(_MID), aggregator_settings=_TEST_AGG)
    pkg = await sim.simulate(
        "BTC", "USDC", Decimal("0.123"), venues=["mock"], snapshot_id="snap-free"
    )
    assert pkg.notional_usd == Decimal("12300")
    assert Decimal("12300") not in (
        Decimal("1000"),
        Decimal("10000"),
        Decimal("100000"),
        Decimal("1000000"),
    )
    row = pkg.rows[0]
    # Mock has depth for ~0.18 BTC; 0.123 should still walk.
    assert row.status == "ok"
    assert row.expected_output is not None


@pytest.mark.asyncio
async def test_simulate_not_supported_listed() -> None:
    sim = TradeSimulator(
        FixedMid(_MID.model_copy(update={"asset": "SOL", "mid": Decimal("150")})),
        aggregator_settings=_TEST_AGG,
    )
    pkg = await sim.simulate("SOL", "USDC", Decimal("10"), venues=["mock"])
    row = next(r for r in pkg.rows if r.venue == "mock")
    assert row.status == "not_supported"
    assert row.expected_output is None
    assert row.best is False
    assert row.error_code == "not_supported"


@pytest.mark.asyncio
async def test_simulate_mid_failure_propagates() -> None:
    from spread_compare.mids import MidResolutionError

    sim = TradeSimulator(FixedMid(fail=True), aggregator_settings=_TEST_AGG)
    with pytest.raises(MidResolutionError):
        await sim.simulate("BTC", "USDC", Decimal("0.1"), venues=["mock"])


# --- timeout + gas_unknown adapters ---

_EXTRA_SLUG = "binance"


class _GasUnknownHighOutput(BaseAdapter):
    """Returns ok + gas_unknown with better-than-mock effective price."""

    venue: str = _EXTRA_SLUG
    venue_class: VenueClass = "amm_dex"

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
        qty = notional_usd / mid.mid
        # Slightly better than mid so expected_output beats mock after fees-in-price.
        p_star = mid.mid if side == "buy" else mid.mid  # mid-aligned → max output
        if side == "sell":
            # Bump sell price above mock's ~99956 so output ranks first.
            p_star = mid.mid + Decimal("100")
        else:
            p_star = mid.mid - Decimal("100")
        return Quote(
            snapshot_id=mid.snapshot_id,
            venue=self.venue,
            asset=asset.upper(),
            venue_symbol=f"{asset.upper()}/USDC",
            instrument_type=instrument_type or "amm_pool",
            side=side,
            notional_usd=notional_usd,
            mid=mid.mid,
            mid_source=mid.mid_source,
            mid_timestamp=mid.timestamp,
            effective_price=p_star,
            spread_bps=Decimal("1"),
            fee_breakdown=FeeBreakdown(
                embedded_in_price=True,
                trading_fee_bps=None,
                platform_fee_bps=Decimal("0"),
                gas_unknown=True,
                explicit_fee_bps=None,
            ),
            total_cost_bps=None,
            timestamp=mid.timestamp,
            status="ok",
            qty_base=qty,
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
    ) -> list[str]:
        return ["BTC"]


@pytest.fixture
def park_extra_adapter() -> Iterator[None]:
    previous = _REGISTRY.get(_EXTRA_SLUG)
    try:
        yield
    finally:
        if previous is None:
            _REGISTRY.pop(_EXTRA_SLUG, None)
        else:
            _REGISTRY[_EXTRA_SLUG] = previous


@pytest.mark.asyncio
async def test_simulate_single_venue_timeout_degrades(
    park_extra_adapter: None,
) -> None:
    _REGISTRY[_EXTRA_SLUG] = SlowAdapter()
    sim = TradeSimulator(
        FixedMid(_MID),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=0.05,
            venue_timeout_by_class={}, response_cache_ttl_sec=0.0
        ),
    )
    pkg = await sim.simulate(
        "BTC", "USDC", Decimal("0.1"), venues=["mock", _EXTRA_SLUG]
    )
    by_v = {r.venue: r for r in pkg.rows}
    assert by_v["mock"].status == "ok"
    assert by_v[_EXTRA_SLUG].status == "error"
    assert by_v[_EXTRA_SLUG].error_code == "timeout"
    assert pkg.rows  # package still succeeds


@pytest.mark.asyncio
async def test_simulate_gas_unknown_not_best_end_to_end(
    park_extra_adapter: None,
) -> None:
    _REGISTRY[_EXTRA_SLUG] = _GasUnknownHighOutput()
    sim = TradeSimulator(FixedMid(_MID), aggregator_settings=_TEST_AGG)
    pkg = await sim.simulate(
        "BTC", "USDC", Decimal("0.1"), venues=["mock", _EXTRA_SLUG]
    )
    by_v = {r.venue: r for r in pkg.rows}
    gas = by_v[_EXTRA_SLUG]
    mock = by_v["mock"]
    assert gas.status == "ok"
    assert gas.total_cost_bps is None
    assert gas.expected_output is not None and mock.expected_output is not None
    assert gas.expected_output > mock.expected_output
    assert gas.best is False
    assert mock.best is True
    # Sorted by expected_output desc → gas first, but not best.
    assert pkg.rows[0].venue == _EXTRA_SLUG
