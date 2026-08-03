"""Shared walk-the-book → VWAP (WHI-799 §4.3).

This is the ONLY implementation adapters may use. Per-adapter copies are a
review-blocking defect (numeric drift on the project's core metric).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

OrderbookLevels = list[tuple[Decimal, Decimal]]


def scale_book_to_canonical(
    levels: Sequence[tuple[Decimal, Decimal]],
    multiplier: Decimal,
) -> OrderbookLevels:
    """Convert contract-unit levels to 1× canonical (price/mult, size×mult).

    ``1000PEPE`` / ``kPEPE`` books quote per contract unit; after scaling,
    :func:`walk_book` and cost formulas share the same units as a 1× mid
    (WHI-826 / WHI-798 §5.3).
    """
    if multiplier == 1:
        return list(levels)
    if multiplier <= 0:
        raise ValueError(f"contract multiplier must be positive, got {multiplier}")
    return [(price / multiplier, size * multiplier) for price, size in levels]


def walk_book(
    levels: Sequence[tuple[Decimal, Decimal]],
    q_star: Decimal,
) -> Decimal | None:
    """Walk orderbook levels and return VWAP effective price for `q_star` base.

    Each level is ``(price, size_base)``. Levels must already be ordered from
    best to worst for the side being walked (asks ascending for buy, bids
    descending for sell). The last level may be partially filled.

    Returns ``None`` when cumulative depth is strictly less than ``q_star``.
    """
    if q_star <= 0:
        raise ValueError(f"q_star must be positive, got {q_star}")

    remaining = q_star
    quote_notional = Decimal("0")

    for price, size in levels:
        if size < 0:
            raise ValueError(f"level size must be non-negative, got {size}")
        if size == 0:
            continue
        take = size if size <= remaining else remaining
        quote_notional += price * take
        remaining -= take
        if remaining == 0:
            break

    if remaining > 0:
        return None
    return quote_notional / q_star
