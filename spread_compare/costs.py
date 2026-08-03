"""Authoritative bps formulas (WHI-799 §4.5 / §5.2).

Adapters call these; the aggregator must never recompute spread or total cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from spread_compare.models import Side

_BPS = Decimal("10000")


def spread_bps(side: Side, effective_price: Decimal, mid: Decimal) -> Decimal:
    """Single-side effective spread in bps relative to reference mid (WHI-799 §4.5).

    Negative values are preserved (better than mid) — do not clamp to zero.
    """
    if mid == 0:
        raise ValueError("mid must be non-zero")
    if side == "buy":
        return (effective_price - mid) / mid * _BPS
    return (mid - effective_price) / mid * _BPS


@dataclass(frozen=True, slots=True)
class TotalCostResult:
    """Outputs of the §5.2 total-cost formula."""

    total_cost_bps: Decimal | None
    explicit_fee_bps: Decimal | None
    gas_bps: Decimal | None
    trading_component_bps: Decimal


def total_cost_bps(
    spread: Decimal,
    *,
    embedded_in_price: bool,
    trading_fee_bps: Decimal | None,
    platform_fee_bps: Decimal,
    gas_unknown: bool,
    gas_usd: Decimal | None,
    notional_usd: Decimal,
) -> TotalCostResult:
    """Compute total_cost_bps and explicit_fee_bps (WHI-799 §5.2).

    When ``gas_unknown`` is true, both total and explicit fee are ``None``
    (unknown gas must not sort as zero).
    """
    if embedded_in_price:
        trading_component = Decimal("0")
    else:
        if trading_fee_bps is None:
            raise ValueError(
                "trading_fee_bps is required when embedded_in_price is false"
            )
        trading_component = trading_fee_bps

    if gas_unknown:
        return TotalCostResult(
            total_cost_bps=None,
            explicit_fee_bps=None,
            gas_bps=None,
            trading_component_bps=trading_component,
        )

    if gas_usd is None:
        gas = Decimal("0")
    else:
        if notional_usd <= 0:
            raise ValueError(f"notional_usd must be positive, got {notional_usd}")
        gas = gas_usd / notional_usd * _BPS

    explicit = trading_component + platform_fee_bps + gas
    total = spread + trading_component + platform_fee_bps + gas
    return TotalCostResult(
        total_cost_bps=total,
        explicit_fee_bps=explicit,
        gas_bps=gas,
        trading_component_bps=trading_component,
    )
