"""Authoritative bps formulas (WHI-799 §4.5 / §5.2 / §6.3 / §4.6).

Adapters call these; the aggregator must never recompute spread or total cost.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from spread_compare.models import Side

_BPS = Decimal("10000")
_BPS_QUANT = Decimal("0.0001")  # WHI-799 §4.3 / §9: bps keep 4 decimal places


def _quantize_bps(value: Decimal) -> Decimal:
    return value.quantize(_BPS_QUANT, rounding=ROUND_HALF_UP)


def spread_bps(side: Side, effective_price: Decimal, mid: Decimal) -> Decimal:
    """Single-side effective spread in bps relative to reference mid (WHI-799 §4.5).

    Negative values are preserved (better than mid) — do not clamp to zero.
    """
    if mid == 0:
        raise ValueError("mid must be non-zero")
    if side == "buy":
        raw = (effective_price - mid) / mid * _BPS
    else:
        raw = (mid - effective_price) / mid * _BPS
    return _quantize_bps(raw)


def top_of_book_spread_bps(
    best_bid: Decimal,
    best_ask: Decimal,
    mid: Decimal,
) -> Decimal:
    """TOB width in bps: ``(ask - bid) / mid * 10_000`` (WHI-799 §6.3).

    Pass ``mid_ref`` for the main comparison field, or ``mid_local`` for the
    local-mid variant — same formula, different denominator.
    """
    if mid == 0:
        raise ValueError("mid must be non-zero")
    return _quantize_bps((best_ask - best_bid) / mid * _BPS)


@dataclass(frozen=True, slots=True)
class TotalCostResult:
    """Outputs of the §5.2 total-cost formula."""

    total_cost_bps: Decimal | None
    explicit_fee_bps: Decimal | None
    gas_bps: Decimal | None


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
    if notional_usd <= 0:
        raise ValueError(f"notional_usd must be positive, got {notional_usd}")

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
        )

    if gas_usd is None:
        gas = Decimal("0")
    else:
        gas = _quantize_bps(gas_usd / notional_usd * _BPS)

    explicit = _quantize_bps(trading_component + platform_fee_bps + gas)
    total = _quantize_bps(spread + trading_component + platform_fee_bps + gas)
    return TotalCostResult(
        total_cost_bps=total,
        explicit_fee_bps=explicit,
        gas_bps=gas,
    )


def round_trip_spread_bps(
    buy_spread_bps: Decimal | None,
    sell_spread_bps: Decimal | None,
) -> Decimal | None:
    """Sum of both sides; ``None`` if either side is missing (WHI-799 §4.6)."""
    if buy_spread_bps is None or sell_spread_bps is None:
        return None
    return _quantize_bps(buy_spread_bps + sell_spread_bps)


def half_spread_bps(
    buy_spread_bps: Decimal | None,
    sell_spread_bps: Decimal | None,
) -> Decimal | None:
    """Half of round-trip spread (WHI-799 §4.6)."""
    rt = round_trip_spread_bps(buy_spread_bps, sell_spread_bps)
    if rt is None:
        return None
    return _quantize_bps(rt / Decimal("2"))


def round_trip_total_cost_bps(
    buy_total_cost_bps: Decimal | None,
    sell_total_cost_bps: Decimal | None,
) -> Decimal | None:
    """Sum of both sides' total cost; ``None`` if either is missing (WHI-799 §4.6)."""
    if buy_total_cost_bps is None or sell_total_cost_bps is None:
        return None
    return _quantize_bps(buy_total_cost_bps + sell_total_cost_bps)


def basis_bps(venue_mark: Decimal, mid: Decimal) -> Decimal:
    """Venue mark vs reference mid in bps (WHI-799 §3.4).

    ``(venue_mark - mid) / mid * 10_000``. Never fold into ``spread_bps``.
    """
    if mid == 0:
        raise ValueError("mid must be non-zero")
    return _quantize_bps((venue_mark - mid) / mid * _BPS)

