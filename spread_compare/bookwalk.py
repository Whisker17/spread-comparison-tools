"""Shared walk-the-book → VWAP (WHI-799 §4.3).

This is the ONLY implementation adapters may use. Per-adapter copies are a
review-blocking defect (numeric drift on the project's core metric).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


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
    filled = Decimal("0")

    for price, size in levels:
        if size <= 0:
            continue
        take = size if size <= remaining else remaining
        quote_notional += price * take
        filled += take
        remaining -= take
        if remaining == 0:
            break

    if remaining > 0 or filled == 0:
        return None
    return quote_notional / filled
