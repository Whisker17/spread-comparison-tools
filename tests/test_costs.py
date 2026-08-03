"""Canonical spread / total-cost vectors from WHI-799 §4.5 / §4.7 / §5.2."""

from decimal import Decimal

from spread_compare.costs import (
    half_spread_bps,
    round_trip_spread_bps,
    round_trip_total_cost_bps,
    spread_bps,
    top_of_book_spread_bps,
    total_cost_bps,
)

MID = Decimal("100000")
P_BUY = Decimal("100044")
P_SELL = Decimal("99956")


def test_spread_bps_buy_fixture() -> None:
    assert spread_bps("buy", P_BUY, MID) == Decimal("4.4")


def test_spread_bps_sell_fixture() -> None:
    assert spread_bps("sell", P_SELL, MID) == Decimal("4.4")


def test_total_cost_cex_taker_10bps() -> None:
    result = total_cost_bps(
        Decimal("4.4"),
        embedded_in_price=False,
        trading_fee_bps=Decimal("10"),
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        gas_usd=None,
        notional_usd=Decimal("10000"),
    )
    assert result.total_cost_bps == Decimal("14.4")
    assert result.explicit_fee_bps == Decimal("10")
    assert result.gas_bps == Decimal("0")


def test_total_cost_prop_embedded() -> None:
    result = total_cost_bps(
        Decimal("4.4"),
        embedded_in_price=True,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        gas_usd=None,
        notional_usd=Decimal("10000"),
    )
    assert result.total_cost_bps == Decimal("4.4")
    assert result.explicit_fee_bps == Decimal("0")


def test_total_cost_gas_unknown_is_none() -> None:
    result = total_cost_bps(
        Decimal("4.4"),
        embedded_in_price=True,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=True,
        gas_usd=None,
        notional_usd=Decimal("10000"),
    )
    assert result.total_cost_bps is None
    assert result.explicit_fee_bps is None
    assert result.gas_bps is None


def test_top_of_book_spread_bps() -> None:
    # fixture best bid/ask around mid 100000 → width 20 → 2.0 bps vs mid_ref
    assert top_of_book_spread_bps(
        Decimal("99990"), Decimal("100010"), Decimal("100000")
    ) == Decimal("2.0000")


def test_basis_bps() -> None:
    from spread_compare.costs import basis_bps

    assert basis_bps(Decimal("100100"), Decimal("100000")) == Decimal("10")


def test_round_trip_helpers() -> None:
    assert round_trip_spread_bps(Decimal("4.4"), Decimal("4.4")) == Decimal("8.8000")
    assert half_spread_bps(Decimal("4.4"), Decimal("4.4")) == Decimal("4.4000")
    assert round_trip_total_cost_bps(Decimal("14.4"), Decimal("14.4")) == Decimal(
        "28.8000"
    )
    assert round_trip_spread_bps(Decimal("4.4"), None) is None
    assert round_trip_total_cost_bps(None, Decimal("14.4")) is None
