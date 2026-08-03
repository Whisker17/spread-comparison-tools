"""Stable venue slug registry (WHI-799 §6.5).

Slug strings are stable public identifiers — no aliases, no silent renames.
Tessera is three chain-qualified venues (v2); plain `tessera` is retired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from spread_compare.models import VenueClass


@dataclass(frozen=True, slots=True)
class VenueInfo:
    """Static metadata for a registered venue slug."""

    slug: str
    display_name: str
    venue_class: VenueClass
    notes: str = ""


def _v(slug: str, display_name: str, venue_class: VenueClass, notes: str = "") -> VenueInfo:
    return VenueInfo(slug=slug, display_name=display_name, venue_class=venue_class, notes=notes)


# Exact table from docs/research/WHI-799-spread-fee-data-model.md §6.5.
_VENUE_ROWS: Final[tuple[VenueInfo, ...]] = (
    _v("binance", "Binance", "cex"),
    _v("bybit", "Bybit", "cex"),
    _v("hyperliquid", "Hyperliquid", "perp_dex"),
    _v("lighter", "Lighter", "perp_dex"),
    _v("apex", "ApeX", "perp_dex"),
    _v("uniswap_eth", "Uniswap (Ethereum)", "amm_dex"),
    _v("aerodrome_base", "Aerodrome (Base)", "amm_dex"),
    _v("pancakeswap_bsc", "PancakeSwap (BSC)", "amm_dex"),
    _v("humidifi", "HumidiFi", "prop_amm", "Solana-only; Jupiter dexes=HumidiFi"),
    _v(
        "tessera_solana",
        "Tessera (Solana)",
        "prop_amm",
        "Jupiter dexes=TesseraV (label ≠ slug)",
    ),
    _v(
        "tessera_base",
        "Tessera (Base)",
        "prop_amm",
        "KyberSwap includedSources=tessera, chain base",
    ),
    _v(
        "tessera_bsc",
        "Tessera (BSC)",
        "prop_amm",
        "KyberSwap includedSources=tessera, chain bsc",
    ),
    _v("bisonfi", "BisonFi", "prop_amm", "Solana-only; Jupiter dexes=BisonFi"),
)

VENUES: Final[dict[str, VenueInfo]] = {v.slug: v for v in _VENUE_ROWS}


def get_venue(slug: str) -> VenueInfo:
    """Return metadata for a known slug or raise KeyError."""
    try:
        return VENUES[slug]
    except KeyError as exc:
        raise KeyError(f"unknown venue slug: {slug!r}") from exc


def known_slugs() -> frozenset[str]:
    """All registered venue slugs."""
    return frozenset(VENUES)
