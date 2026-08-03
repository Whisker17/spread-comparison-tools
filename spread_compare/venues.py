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


# Exact table from docs/research/WHI-799-spread-fee-data-model.md §6.5.
VENUES: Final[dict[str, VenueInfo]] = {
    "binance": VenueInfo("binance", "Binance", "cex"),
    "bybit": VenueInfo("bybit", "Bybit", "cex"),
    "hyperliquid": VenueInfo("hyperliquid", "Hyperliquid", "perp_dex"),
    "lighter": VenueInfo("lighter", "Lighter", "perp_dex"),
    "apex": VenueInfo("apex", "ApeX", "perp_dex"),
    "uniswap_eth": VenueInfo("uniswap_eth", "Uniswap (Ethereum)", "amm_dex"),
    "aerodrome_base": VenueInfo("aerodrome_base", "Aerodrome (Base)", "amm_dex"),
    "pancakeswap_bsc": VenueInfo("pancakeswap_bsc", "PancakeSwap (BSC)", "amm_dex"),
    "humidifi": VenueInfo(
        "humidifi",
        "HumidiFi",
        "prop_amm",
        notes="Solana-only; Jupiter dexes=HumidiFi",
    ),
    "tessera_solana": VenueInfo(
        "tessera_solana",
        "Tessera (Solana)",
        "prop_amm",
        notes="Jupiter dexes=TesseraV (label ≠ slug)",
    ),
    "tessera_base": VenueInfo(
        "tessera_base",
        "Tessera (Base)",
        "prop_amm",
        notes="KyberSwap includedSources=tessera, chain base",
    ),
    "tessera_bsc": VenueInfo(
        "tessera_bsc",
        "Tessera (BSC)",
        "prop_amm",
        notes="KyberSwap includedSources=tessera, chain bsc",
    ),
    "bisonfi": VenueInfo(
        "bisonfi",
        "BisonFi",
        "prop_amm",
        notes="Solana-only; Jupiter dexes=BisonFi",
    ),
}


def get_venue(slug: str) -> VenueInfo:
    """Return metadata for a known slug or raise KeyError."""
    try:
        return VENUES[slug]
    except KeyError as exc:
        raise KeyError(f"unknown venue slug: {slug!r}") from exc


def known_slugs() -> frozenset[str]:
    """All registered venue slugs."""
    return frozenset(VENUES)
