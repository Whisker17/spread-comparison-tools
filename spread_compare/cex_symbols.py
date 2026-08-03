"""CEX logical-asset → venue-symbol map (WHI-798 §3.3 / WHI-826).

Adapters resolve symbols only through this module — never hardcode pairs in
request paths. Spot and USDT-M / linear perp often share a symbol string, but
memes and tokenized stocks do not: values carry separate spot/perp forms and
contract multipliers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from spread_compare.models import InstrumentType

CexBookSide = Literal["spot", "perp"]


@dataclass(frozen=True, slots=True)
class CexSymbol:
    """CEX wire symbols for one logical asset.

    ``None`` means the asset is not listed on that book. Multipliers convert
    venue contract units into canonical 1× asset units (e.g. ``1000PEPE`` → 1000).
    """

    spot: str | None = None
    perp: str | None = None
    spot_multiplier: Decimal = Decimal(1)
    perp_multiplier: Decimal = Decimal(1)


def _both(symbol: str, *, multiplier: Decimal = Decimal(1)) -> CexSymbol:
    return CexSymbol(
        spot=symbol,
        perp=symbol,
        spot_multiplier=multiplier,
        perp_multiplier=multiplier,
    )


def _spot_only(symbol: str, *, multiplier: Decimal = Decimal(1)) -> CexSymbol:
    return CexSymbol(spot=symbol, perp=None, spot_multiplier=multiplier)


def _perp_only(symbol: str, *, multiplier: Decimal = Decimal(1)) -> CexSymbol:
    return CexSymbol(perp=symbol, spot=None, perp_multiplier=multiplier)


# WHI-798 §3.3 / §5.3 / §6 — Phase 1 CEX coverage.
CEX_USDT_SYMBOLS: Final[dict[str, CexSymbol]] = {
    # Blue chips: same string both sides, mult 1.
    "BTC": _both("BTCUSDT"),
    "ETH": _both("ETHUSDT"),
    "SOL": _both("SOLUSDT"),
    # Tokenized stocks (bStocks): spot only.
    "QQQB": _spot_only("QQQBUSDT"),
    "SPCXB": _spot_only("SPCXBUSDT"),
    "NVDAB": _spot_only("NVDABUSDT"),
    # Equity perps: TradFi / linear perp only (no spot book under this id).
    "TSLA": _perp_only("TSLAUSDT"),
    "NVDA": _perp_only("NVDAUSDT"),
    "AAPL": _perp_only("AAPLUSDT"),
    "MSFT": _perp_only("MSFTUSDT"),
    # Others P0.
    "DOGE": _both("DOGEUSDT"),
    "WIF": _both("WIFUSDT"),
    "XRP": _both("XRPUSDT"),
    "SUI": _both("SUIUSDT"),
    "LINK": _both("LINKUSDT"),
    "AVAX": _both("AVAXUSDT"),
    "ADA": _both("ADAUSDT"),
    "BNB": _both("BNBUSDT"),
    # Memes P1 — spot is 1×, perp is 1000× contract (WHI-798 §5.3).
    "PEPE": CexSymbol(
        spot="PEPEUSDT",
        perp="1000PEPEUSDT",
        spot_multiplier=Decimal(1),
        perp_multiplier=Decimal(1000),
    ),
    "BONK": CexSymbol(
        spot="BONKUSDT",
        perp="1000BONKUSDT",
        spot_multiplier=Decimal(1),
        perp_multiplier=Decimal(1000),
    ),
    # Non-standard Bybit forms (e.g. AMD → AMDSTOCKUSDT) are expressible via
    # CexSymbol when those assets land; no Phase-1 entry yet.
}


def get_cex_symbol(asset: str) -> CexSymbol | None:
    """Return the full CEX symbol record, or ``None`` if unknown."""
    return CEX_USDT_SYMBOLS.get(asset.upper())


def resolve_cex_symbol(
    asset: str,
    instrument_type: InstrumentType | CexBookSide = "spot",
) -> str | None:
    """Return the CEX wire symbol for ``asset``/``instrument_type``, or ``None``."""
    entry = get_cex_symbol(asset)
    if entry is None:
        return None
    if instrument_type == "spot":
        return entry.spot
    if instrument_type == "perp":
        return entry.perp
    return None


def resolve_cex_multiplier(
    asset: str,
    instrument_type: InstrumentType | CexBookSide = "spot",
) -> Decimal:
    """Contract size in canonical 1× units; ``1`` when unknown or unscaled."""
    entry = get_cex_symbol(asset)
    if entry is None:
        return Decimal(1)
    if instrument_type == "spot":
        return entry.spot_multiplier
    if instrument_type == "perp":
        return entry.perp_multiplier
    return Decimal(1)


def supported_cex_assets(
    instrument_type: InstrumentType | CexBookSide | None = None,
) -> list[str]:
    """Sorted logical asset keys supported for the given book (or either)."""
    if instrument_type is None:
        return sorted(CEX_USDT_SYMBOLS)
    out: list[str] = []
    for asset, entry in CEX_USDT_SYMBOLS.items():
        if instrument_type == "spot" and entry.spot is not None:
            out.append(asset)
        elif instrument_type == "perp" and entry.perp is not None:
            out.append(asset)
    return sorted(out)
