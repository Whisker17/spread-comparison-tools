"""Quote invariant enforcement (WHI-799 §6.2)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from spread_compare.models import FeeBreakdown, Quote

_TS = datetime(2026, 8, 3, tzinfo=UTC)


def _base_kwargs() -> dict[str, object]:
    return {
        "snapshot_id": "snap-1",
        "venue": "mock",
        "asset": "BTC",
        "instrument_type": "spot",
        "side": "buy",
        "notional_usd": Decimal("10000"),
        "mid": Decimal("100000"),
        "mid_source": "binance_usdm_index",
        "mid_timestamp": _TS,
        "timestamp": _TS,
    }


def test_ok_quote_valid() -> None:
    q = Quote(
        **_base_kwargs(),  # type: ignore[arg-type]
        effective_price=Decimal("100044"),
        spread_bps=Decimal("4.4"),
        total_cost_bps=Decimal("14.4"),
        qty_base=Decimal("0.1"),
        fee_breakdown=FeeBreakdown(
            embedded_in_price=False,
            trading_fee_bps=Decimal("10"),
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=Decimal("10"),
        ),
        status="ok",
    )
    assert q.status == "ok"
    assert q.spread_bps == Decimal("4.4")


def test_ok_gas_unknown_requires_null_total() -> None:
    q = Quote(
        **_base_kwargs(),  # type: ignore[arg-type]
        effective_price=Decimal("100044"),
        spread_bps=Decimal("4.4"),
        total_cost_bps=None,
        qty_base=Decimal("0.1"),
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            platform_fee_bps=Decimal("0"),
            gas_unknown=True,
            explicit_fee_bps=None,
        ),
        status="ok",
    )
    assert q.total_cost_bps is None


def test_ok_missing_effective_price_raises() -> None:
    with pytest.raises(ValidationError):
        Quote(
            **_base_kwargs(),  # type: ignore[arg-type]
            effective_price=None,
            spread_bps=Decimal("4.4"),
            total_cost_bps=Decimal("4.4"),
            qty_base=Decimal("0.1"),
            fee_breakdown=FeeBreakdown(embedded_in_price=True, gas_unknown=False),
            status="ok",
        )


def test_ok_gas_unknown_with_total_raises() -> None:
    with pytest.raises(ValidationError):
        Quote(
            **_base_kwargs(),  # type: ignore[arg-type]
            effective_price=Decimal("100044"),
            spread_bps=Decimal("4.4"),
            total_cost_bps=Decimal("4.4"),
            qty_base=Decimal("0.1"),
            fee_breakdown=FeeBreakdown(
                embedded_in_price=True,
                gas_unknown=True,
                explicit_fee_bps=None,
            ),
            status="ok",
        )


def test_ok_known_gas_missing_total_raises() -> None:
    with pytest.raises(ValidationError):
        Quote(
            **_base_kwargs(),  # type: ignore[arg-type]
            effective_price=Decimal("100044"),
            spread_bps=Decimal("4.4"),
            total_cost_bps=None,
            qty_base=Decimal("0.1"),
            fee_breakdown=FeeBreakdown(embedded_in_price=True, gas_unknown=False),
            status="ok",
        )


def test_non_ok_with_price_fields_raises() -> None:
    with pytest.raises(ValidationError):
        Quote(
            **_base_kwargs(),  # type: ignore[arg-type]
            effective_price=Decimal("100044"),
            spread_bps=None,
            total_cost_bps=None,
            qty_base=None,
            fee_breakdown=FeeBreakdown(
                embedded_in_price=False,
                gas_unknown=False,
                explicit_fee_bps=None,
            ),
            status="insufficient_liquidity",
        )


def test_non_ok_with_explicit_fee_raises() -> None:
    with pytest.raises(ValidationError):
        Quote(
            **_base_kwargs(),  # type: ignore[arg-type]
            fee_breakdown=FeeBreakdown(
                embedded_in_price=False,
                gas_unknown=False,
                explicit_fee_bps=Decimal("10"),
            ),
            status="error",
        )


def test_non_ok_null_fields_valid() -> None:
    q = Quote(
        **_base_kwargs(),  # type: ignore[arg-type]
        fee_breakdown=FeeBreakdown(
            embedded_in_price=False,
            gas_unknown=False,
            explicit_fee_bps=None,
        ),
        status="no_quote",
    )
    assert q.effective_price is None
    assert q.spread_bps is None
