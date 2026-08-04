"""Price-impact capture and thresholding (WHI-845).

Adapters record ``price_impact_bps`` when the upstream reports it (or when a
mid-relative proxy is derived). This module applies the config threshold and
reclassifies ``status=ok`` → ``excessive_impact`` so the row stays visible with
its numbers but never participates in §5.2 best ranking or heat ranges.
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.models import Quote
from spread_compare.settings import load_impact_settings

_BPS = Decimal("10000")


def fraction_to_impact_bps(fraction: Decimal | float | str) -> Decimal:
    """Convert a unit-fraction impact (Jupiter ``priceImpactPct``) to bps.

    Jupiter returns a string fraction where ``0.01`` means 1% (= 100 bps), not a
    percent integer. Absolute value — impact direction is not used for the guard.
    """
    value = abs(Decimal(str(fraction)))
    return value * _BPS


def apply_impact_threshold(quote: Quote) -> Quote:
    """Reclassify an ok quote whose impact exceeds ``max_price_impact_bps``.

    Non-ok quotes and quotes without a measured impact pass through unchanged.
    ``excessive_impact`` quotes keep all price fields (WHI-799 §6.2 amendment).
    """
    if quote.status != "ok":
        return quote
    impact = quote.price_impact_bps
    if impact is None:
        return quote

    max_bps = Decimal(str(load_impact_settings().max_price_impact_bps))
    if impact <= max_bps:
        return quote

    return quote.model_copy(
        update={
            "status": "excessive_impact",
            "error_code": "excessive_impact",
            "error_message": (
                f"price impact {impact} bps exceeds max_price_impact_bps={max_bps}"
            ),
        }
    )
