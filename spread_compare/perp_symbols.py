"""Perp-DEX logical asset → venue coin / base id + contract multiplier (WHI-826).

CEX symbols live in :mod:`spread_compare.cex_symbols`. Perp DEXes use different
wire forms (HL ``xyz:TSLA`` / ``kPEPE``, Lighter/ApeX ``1000PEPE``). Multipliers
normalize venue contract units to the canonical 1× asset before cost formulas.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final


@dataclass(frozen=True, slots=True)
class PerpVenueSymbol:
    """Venue wire id for one logical asset on a perp DEX."""

    venue_symbol: str
    multiplier: Decimal = Decimal(1)


# Logical ids with explicit HL coin forms (HIP-3 equity + scaled memes).
# Everything else defaults to ``ASSET.upper()`` with multiplier 1.
_HL_OVERRIDES: Final[dict[str, PerpVenueSymbol]] = {
    "TSLA": PerpVenueSymbol("xyz:TSLA"),
    "NVDA": PerpVenueSymbol("xyz:NVDA"),
    "AAPL": PerpVenueSymbol("xyz:AAPL"),
    "MSFT": PerpVenueSymbol("xyz:MSFT"),
    "PEPE": PerpVenueSymbol("kPEPE", Decimal(1000)),
    "BONK": PerpVenueSymbol("kBONK", Decimal(1000)),
}

# Lighter / ApeX: 1000× meme bases; equity and others match the logical id.
_LIGHTER_OVERRIDES: Final[dict[str, PerpVenueSymbol]] = {
    "PEPE": PerpVenueSymbol("1000PEPE", Decimal(1000)),
    "BONK": PerpVenueSymbol("1000BONK", Decimal(1000)),
}

_APEX_OVERRIDES: Final[dict[str, PerpVenueSymbol]] = {
    "PEPE": PerpVenueSymbol("1000PEPE", Decimal(1000)),
    "BONK": PerpVenueSymbol("1000BONK", Decimal(1000)),
}

# Phase-1 logical assets that adapters advertise when meta is not yet loaded.
HL_PHASE1_ASSETS: Final[tuple[str, ...]] = (
    "BTC",
    "ETH",
    "SOL",
    "DOGE",
    "WIF",
    "XRP",
    "SUI",
    "LINK",
    "AVAX",
    "ADA",
    "BNB",
    "TSLA",
    "NVDA",
    "AAPL",
    "MSFT",
    "PEPE",
    "BONK",
)

# HIP-3 sub-dexes allowed for meta / books (WHI-798 §8 Q10: only xyz + main).
HL_ALLOWED_DEXES: Final[frozenset[str]] = frozenset({"", "xyz"})


def resolve_hl_coin(asset: str) -> PerpVenueSymbol:
    """Map logical asset → Hyperliquid coin form + multiplier."""
    key = asset.strip()
    if ":" in key:
        # Caller already passed a HIP-3 coin; preserve dex, uppercase name.
        dex, name = key.split(":", 1)
        dex_l = dex.lower()
        if dex_l not in HL_ALLOWED_DEXES or not name:
            return PerpVenueSymbol(key.upper() if ":" not in key else f"{dex}:{name.upper()}")
        return PerpVenueSymbol(f"{dex_l}:{name.upper()}")
    upper = key.upper()
    if upper in _HL_OVERRIDES:
        return _HL_OVERRIDES[upper]
    return PerpVenueSymbol(upper)


def resolve_lighter_symbol(asset: str) -> PerpVenueSymbol:
    """Map logical asset → Lighter ``orderBookDetails.symbol`` + multiplier."""
    upper = asset.upper()
    if upper in _LIGHTER_OVERRIDES:
        return _LIGHTER_OVERRIDES[upper]
    return PerpVenueSymbol(upper)


def resolve_apex_base(asset: str) -> PerpVenueSymbol:
    """Map logical asset → ApeX ``baseTokenId`` + multiplier."""
    upper = asset.upper()
    if upper in _APEX_OVERRIDES:
        return _APEX_OVERRIDES[upper]
    return PerpVenueSymbol(upper)


def hl_logical_id(coin: str) -> str:
    """Canonical logical id from an HL coin (``xyz:TSLA`` → ``TSLA``, ``kPEPE`` → ``PEPE``)."""
    coin = coin.strip()
    if ":" in coin:
        return coin.split(":", 1)[-1].upper()
    upper = coin.upper()
    if upper.startswith("K") and len(upper) > 1:
        # kPEPE / kBONK → PEPE / BONK (only known k-prefix scaled memes).
        rest = upper[1:]
        if rest in ("PEPE", "BONK"):
            return rest
    if upper.startswith("1000") and len(upper) > 4:
        return upper[4:]
    return upper
