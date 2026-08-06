"""CEX logical-asset → venue-symbol map (WHI-798 §3.3 / WHI-826 / WHI-881).

Adapters resolve symbols only through this module — never hardcode pairs in
request paths. Spot and USDT-M / linear perp often share a symbol string, but
memes and stock forms do not: values carry separate spot/perp forms and
contract multipliers.

WHI-881: stock resolution is ``(asset, form)``-aware — bstock/xstock_cex hang
off the tokenized form; equity perps off ``form=perp``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from spread_compare.models import InstrumentType

CexBookSide = Literal["spot", "perp"]


@dataclass(frozen=True, slots=True)
class CexSymbol:
    """CEX wire symbols for one logical asset (or one stock form).

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


# Crypto / others: asset-keyed (form is always null).
_CRYPTO_CEX: Final[dict[str, CexSymbol]] = {
    "BTC": _both("BTCUSDT"),
    "ETH": _both("ETHUSDT"),
    "SOL": _both("SOLUSDT"),
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
}

# Stock forms: (underlying, form) → CexSymbol.
# Wire symbols are explicit catalog maps — never ``{TICKER}B`` string templates.
_STOCK_CEX: Final[dict[tuple[str, str], CexSymbol]] = {
    # Equity perps (form=perp). Default wire is {TICKER}USDT (Binance TradFi /
    # Bybit linear common form). Venue-specific exceptions live in
    # ``_STOCK_CEX_VENUE_OVERRIDES`` (e.g. Bybit AMDSTOCKUSDT).
    ("TSLA", "perp"): _perp_only("TSLAUSDT"),
    ("NVDA", "perp"): _perp_only("NVDAUSDT"),
    ("AAPL", "perp"): _perp_only("AAPLUSDT"),
    ("MSFT", "perp"): _perp_only("MSFTUSDT"),
    ("QQQ", "perp"): _perp_only("QQQUSDT"),
    ("CRCL", "perp"): _perp_only("CRCLUSDT"),
    ("GOOGL", "perp"): _perp_only("GOOGLUSDT"),
    ("AMD", "perp"): _perp_only("AMDUSDT"),
    ("PLTR", "perp"): _perp_only("PLTRUSDT"),
    ("META", "perp"): _perp_only("METAUSDT"),
    ("AMZN", "perp"): _perp_only("AMZNUSDT"),
    ("SPY", "perp"): _perp_only("SPYUSDT"),
    ("MSTR", "perp"): _perp_only("MSTRUSDT"),
    # bStocks CEX spot (Binance *B).
    ("NVDA", "bstock"): _spot_only("NVDABUSDT"),
    ("QQQ", "bstock"): _spot_only("QQQBUSDT"),
    ("SPCX", "bstock"): _spot_only("SPCXBUSDT"),
    ("TSLA", "bstock"): _spot_only("TSLABUSDT"),
    ("AAPL", "bstock"): _spot_only("AAPLBUSDT"),
    ("MSFT", "bstock"): _spot_only("MSFTBUSDT"),
    ("CRCL", "bstock"): _spot_only("CRCLBUSDT"),
    ("GOOGL", "bstock"): _spot_only("GOOGLBUSDT"),
    ("AMD", "bstock"): _spot_only("AMDBUSDT"),
    ("PLTR", "bstock"): _spot_only("PLTRBUSDT"),
    ("META", "bstock"): _spot_only("METABUSDT"),
    ("AMZN", "bstock"): _spot_only("AMZNBUSDT"),
    ("SPY", "bstock"): _spot_only("SPYBUSDT"),
    ("MSTR", "bstock"): _spot_only("MSTRBUSDT"),
    # Bybit xStocks CEX spot (*X).
    ("NVDA", "xstock_cex"): _spot_only("NVDAXUSDT"),
    ("TSLA", "xstock_cex"): _spot_only("TSLAXUSDT"),
    ("AAPL", "xstock_cex"): _spot_only("AAPLXUSDT"),
    ("SPCX", "xstock_cex"): _spot_only("SPCXXUSDT"),
    ("CRCL", "xstock_cex"): _spot_only("CRCLXUSDT"),
    ("GOOGL", "xstock_cex"): _spot_only("GOOGLXUSDT"),
    ("META", "xstock_cex"): _spot_only("METAXUSDT"),
    ("AMZN", "xstock_cex"): _spot_only("AMZNXUSDT"),
}

# (asset, form, book_side, venue) → wire symbol when it diverges from ``_STOCK_CEX``.
# Book_side is spot|perp. Only exceptional cases — never a full second map.
_STOCK_CEX_VENUE_OVERRIDES: Final[dict[tuple[str, str, str, str], str]] = {
    # Bybit linear uses AMDSTOCKUSDT (WHI-798 §4.4 / WHI-883).
    ("AMD", "perp", "perp", "bybit"): "AMDSTOCKUSDT",
}

# Flat asset-keyed view for call sites that still resolve without form
# (crypto / others only). Stock underlyings are NOT listed here under bare id
# for dual-form assets — callers must pass form for stocks.
CEX_USDT_SYMBOLS: Final[dict[str, CexSymbol]] = dict(_CRYPTO_CEX)


def get_cex_symbol(asset: str, *, form: str | None = None) -> CexSymbol | None:
    """Return the CEX symbol record for ``asset`` (and optional stock ``form``).

    Stock underlyings require ``form`` — no silent bare-asset → perp alias
    (WHI-799 §6.2 / WHI-881). Callers that need the perp book pass
    ``form="perp"`` explicitly (e.g. mid mark sampling).

    Venue-specific wire exceptions are applied in :func:`resolve_cex_symbol`
    via ``venue=`` — the base record stays the common (usually Binance) form.
    """
    key = asset.upper()
    if form is not None:
        return _STOCK_CEX.get((key, form.lower()))
    return _CRYPTO_CEX.get(key)


def resolve_cex_symbol(
    asset: str,
    instrument_type: InstrumentType | CexBookSide = "spot",
    *,
    form: str | None = None,
    venue: str | None = None,
) -> str | None:
    """Return the CEX wire symbol for ``asset``/``instrument_type``/``form``.

    Pass ``venue`` when the book can diverge across CEX venues (e.g. Bybit
    ``AMDSTOCKUSDT`` vs Binance ``AMDUSDT``). Unknown venues fall back to the
    shared map entry.
    """
    key = asset.upper()
    form_l = form.lower() if form is not None else None
    book: str | None = None
    if instrument_type in ("spot", "perp"):
        book = instrument_type
    if venue is not None and form_l is not None and book is not None:
        override = _STOCK_CEX_VENUE_OVERRIDES.get(
            (key, form_l, book, venue.lower())
        )
        if override is not None:
            return override
    entry = get_cex_symbol(asset, form=form)
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
    *,
    form: str | None = None,
) -> Decimal:
    """Contract size in canonical 1× units; ``1`` when unknown or unscaled."""
    entry = get_cex_symbol(asset, form=form)
    if entry is None:
        return Decimal(1)
    if instrument_type == "spot":
        return entry.spot_multiplier
    if instrument_type == "perp":
        return entry.perp_multiplier
    return Decimal(1)


def supported_cex_assets(
    instrument_type: InstrumentType | CexBookSide | None = None,
    *,
    form: str | None = None,
) -> list[str]:
    """Sorted logical asset keys supported for the given book (or either).

    When ``form`` is set, only that stock-form map is considered. When ``form``
    is None, crypto/others plus stock **perp** underlyings are returned (the
    default CEX fan-out for equity perps). Tokenized CEX spot forms are
    reached only via form-aware fan-out.
    """
    if form is not None:
        form_l = form.lower()
        out: list[str] = []
        for (asset, f), entry in _STOCK_CEX.items():
            if f != form_l:
                continue
            if instrument_type is None:
                out.append(asset)
            elif instrument_type == "spot" and entry.spot is not None:
                out.append(asset)
            elif instrument_type == "perp" and entry.perp is not None:
                out.append(asset)
        return sorted(set(out))

    combined: dict[str, CexSymbol] = dict(_CRYPTO_CEX)
    for (asset, f), entry in _STOCK_CEX.items():
        if f == "perp":
            combined[asset] = entry
    if instrument_type is None:
        return sorted(combined)
    out2: list[str] = []
    for asset, entry in combined.items():
        if instrument_type == "spot" and entry.spot is not None:
            out2.append(asset)
        elif instrument_type == "perp" and entry.perp is not None:
            out2.append(asset)
    return sorted(out2)
