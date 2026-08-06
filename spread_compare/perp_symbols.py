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
    # WHI-884 / WHI-883 P0 exact HIP-3 equities (never SPY/QQQ — proxy only).
    "CRCL": PerpVenueSymbol("xyz:CRCL"),
    "GOOGL": PerpVenueSymbol("xyz:GOOGL"),
    "AMD": PerpVenueSymbol("xyz:AMD"),
    "PLTR": PerpVenueSymbol("xyz:PLTR"),
    "META": PerpVenueSymbol("xyz:META"),
    "AMZN": PerpVenueSymbol("xyz:AMZN"),
    "MSTR": PerpVenueSymbol("xyz:MSTR"),
    "PEPE": PerpVenueSymbol("kPEPE", Decimal(1000)),
    "BONK": PerpVenueSymbol("kBONK", Decimal(1000)),
}

# Inverse of scaled HL coins (venue → logical) derived from overrides.
_HL_COIN_TO_LOGICAL: Final[dict[str, str]] = {
    entry.venue_symbol: logical for logical, entry in _HL_OVERRIDES.items()
}

# Lighter / ApeX: 1000× meme bases; equity and others match the logical id.
_SCALED_1000_OVERRIDES: Final[dict[str, PerpVenueSymbol]] = {
    "PEPE": PerpVenueSymbol("1000PEPE", Decimal(1000)),
    "BONK": PerpVenueSymbol("1000BONK", Decimal(1000)),
}

# Crypto + others on every perp DEX (and HL main book).
_PERP_DEX_CRYPTO: Final[tuple[str, ...]] = (
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
)

# Equity with exact HL ``xyz:`` markets (WHI-883 — never SPY/QQQ proxies).
_PERP_DEX_EQUITY_HL_EXACT: Final[tuple[str, ...]] = (
    "TSLA",
    "NVDA",
    "AAPL",
    "MSFT",
    "CRCL",
    "GOOGL",
    "AMD",
    "PLTR",
    "META",
    "AMZN",
    "MSTR",
)

# Equity listed on Lighter/ApeX (+ CEX) but **no** exact HL market (proxy only).
_PERP_DEX_EQUITY_NO_HL: Final[tuple[str, ...]] = ("SPY", "QQQ")

# Multiplier infrastructure (P1 catalog); not in assets.ASSETS.
_PERP_DEX_MEME: Final[tuple[str, ...]] = ("PEPE", "BONK")

# Hyperliquid cold ``supported_assets`` + HL WS: exact markets only.
# Name kept for adapter call sites; scope is HL-exact product surface.
HL_PHASE1_ASSETS: Final[tuple[str, ...]] = (
    _PERP_DEX_CRYPTO + _PERP_DEX_EQUITY_HL_EXACT + _PERP_DEX_MEME
)

# Lighter / ApeX / WS product set — includes SPY/QQQ (no HL exact).
PERP_DEX_SERVED_ASSETS: Final[tuple[str, ...]] = (
    _PERP_DEX_CRYPTO
    + _PERP_DEX_EQUITY_HL_EXACT
    + _PERP_DEX_EQUITY_NO_HL
    + _PERP_DEX_MEME
)

# HIP-3 sub-dex prefixes allowed beyond the main book (WHI-798 §8 Q10).
# Main book has no prefix; only ``xyz`` is whitelisted among HIP-3 dexes.
HL_ALLOWED_HIP3_DEXES: Final[frozenset[str]] = frozenset({"xyz"})
# Back-compat alias used by the HL adapter meta loop.
HL_ALLOWED_DEXES: Final[frozenset[str]] = HL_ALLOWED_HIP3_DEXES


class UnsupportedPerpSymbolError(ValueError):
    """Logical asset / coin form is not allowed on this venue map."""


# Underlyings with only HL proxy indices (xyz:SP500 / xyz:XYZ100) — never
# exact tickers. Bare resolution must fail closed (WHI-883 §5.4 / R4).
_HL_NO_EXACT: Final[frozenset[str]] = frozenset({"SPY", "QQQ"})


def resolve_hl_coin(asset: str) -> PerpVenueSymbol:
    """Map logical asset → Hyperliquid coin form + multiplier.

    Rejects disallowed HIP-3 dex prefixes (only ``xyz`` + main book) and
    equity underlyings with proxy-only HL markets (SPY/QQQ).
    """
    key = asset.strip()
    if ":" in key:
        dex, name = key.split(":", 1)
        dex_l = dex.lower()
        if not name or dex_l not in HL_ALLOWED_HIP3_DEXES:
            raise UnsupportedPerpSymbolError(
                f"hyperliquid dex {dex!r} not allowed (whitelist: xyz + main)"
            )
        return PerpVenueSymbol(f"{dex_l}:{name.upper()}")
    upper = key.upper()
    if upper in _HL_NO_EXACT:
        raise UnsupportedPerpSymbolError(
            f"hyperliquid has no exact market for {upper} "
            f"(proxy index only — do not map as exact)"
        )
    if upper in _HL_OVERRIDES:
        return _HL_OVERRIDES[upper]
    return PerpVenueSymbol(upper)


def resolve_scaled_1000_symbol(asset: str) -> PerpVenueSymbol:
    """Map logical asset → Lighter/ApeX-style ``1000X`` base when needed."""
    upper = asset.upper()
    if upper in _SCALED_1000_OVERRIDES:
        return _SCALED_1000_OVERRIDES[upper]
    return PerpVenueSymbol(upper)


def resolve_lighter_symbol(asset: str) -> PerpVenueSymbol:
    """Map logical asset → Lighter ``orderBookDetails.symbol`` + multiplier."""
    return resolve_scaled_1000_symbol(asset)


def resolve_apex_base(asset: str) -> PerpVenueSymbol:
    """Map logical asset → ApeX ``baseTokenId`` + multiplier."""
    return resolve_scaled_1000_symbol(asset)


def hl_logical_id(coin: str) -> str:
    """Canonical logical id from an HL coin (``xyz:TSLA`` → ``TSLA``, ``kPEPE`` → ``PEPE``)."""
    coin = coin.strip()
    if coin in _HL_COIN_TO_LOGICAL:
        return _HL_COIN_TO_LOGICAL[coin]
    for venue_coin, logical in _HL_COIN_TO_LOGICAL.items():
        if venue_coin.lower() == coin.lower():
            return logical
    if ":" in coin:
        return coin.split(":", 1)[-1].upper()
    return coin.upper()


def scaled_1000_logical_id(venue_symbol: str) -> str:
    """Map known scaled bases (``1000PEPE`` → ``PEPE``); else uppercased symbol.

    Only known overrides are inverted — arbitrary ``1000*`` markets stay as-is
    so ``supported_assets`` never advertises an unresolvable logical id.
    """
    sym = venue_symbol.upper()
    for logical, entry in _SCALED_1000_OVERRIDES.items():
        if entry.venue_symbol.upper() == sym:
            return logical
    return sym