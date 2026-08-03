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
    # Settlement / deployment chain when single-chain; None for multi-chain CEX/perp.
    chain: str | None = None
    notes: str = ""


# Exact table from docs/research/WHI-799-spread-fee-data-model.md §6.5 (+ chain for FE).
_VENUE_ROWS: Final[tuple[VenueInfo, ...]] = (
    VenueInfo("binance", "Binance", "cex", chain=None),
    VenueInfo("bybit", "Bybit", "cex", chain=None),
    VenueInfo("hyperliquid", "Hyperliquid", "perp_dex", chain="hyperliquid"),
    VenueInfo("lighter", "Lighter", "perp_dex", chain="lighter"),
    VenueInfo("apex", "ApeX", "perp_dex", chain="apex"),
    VenueInfo("uniswap_eth", "Uniswap (Ethereum)", "amm_dex", chain="ethereum"),
    VenueInfo("aerodrome_base", "Aerodrome (Base)", "amm_dex", chain="base"),
    VenueInfo("pancakeswap_bsc", "PancakeSwap (BSC)", "amm_dex", chain="bsc"),
    VenueInfo(
        "humidifi",
        "HumidiFi",
        "prop_amm",
        chain="solana",
        notes="Solana-only; Jupiter dexes=HumidiFi",
    ),
    VenueInfo(
        "tessera_solana",
        "Tessera (Solana)",
        "prop_amm",
        chain="solana",
        notes="Jupiter dexes=TesseraV (label ≠ slug)",
    ),
    VenueInfo(
        "tessera_base",
        "Tessera (Base)",
        "prop_amm",
        chain="base",
        notes="KyberSwap includedSources=tessera, chain base",
    ),
    VenueInfo(
        "tessera_bsc",
        "Tessera (BSC)",
        "prop_amm",
        chain="bsc",
        notes="KyberSwap includedSources=tessera, chain bsc",
    ),
    VenueInfo(
        "bisonfi",
        "BisonFi",
        "prop_amm",
        chain="solana",
        notes="Solana-only; Jupiter dexes=BisonFi",
    ),
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
