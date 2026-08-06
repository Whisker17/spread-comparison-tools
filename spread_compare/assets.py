"""Logical asset catalog + per-venue representation labels (WHI-798 §3.3 / v3).

Static product metadata for ``GET /assets``. Adapters still own mint/address
resolution; this table is the frontend-facing label map and form taxonomy.

WHI-881 / WHI-880: stock underlyings are one logical asset with nested forms;
crypto blue chips and others stay single-form (``form=null``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal

AssetCategory = Literal["crypto_blue_chip", "stock", "other"]
FormId = Literal["perp", "bstock", "ondo", "xstock", "xstock_cex"]
FormClass = Literal["perp", "tokenized"]
FormCoverage = Literal["live", "unverified", "absent"]

# Closed vocabulary (WHI-798 §4.6). New issuer families extend this tuple only.
FORM_IDS: Final[tuple[FormId, ...]] = (
    "perp",
    "bstock",
    "ondo",
    "xstock",
    "xstock_cex",
)

_TOKENIZED_FORMS: Final[frozenset[FormId]] = frozenset(
    {"bstock", "ondo", "xstock", "xstock_cex"}
)


def form_class_of(form_id: FormId | str) -> FormClass:
    """Map form id → form_class for §5.2 best grouping (WHI-798 §4.6)."""
    if form_id == "perp":
        return "perp"
    if form_id in _TOKENIZED_FORMS:
        return "tokenized"
    raise ValueError(f"unknown form id: {form_id!r}")


@dataclass(frozen=True, slots=True)
class AssetForm:
    """One tradeable form of a stock underlying (WHI-798 §4.6 / WHI-799 §6.7)."""

    id: FormId
    form_class: FormClass
    # Venue slug → display representation label (not necessarily wire symbol).
    representations: dict[str, str]
    coverage: FormCoverage = "live"


@dataclass(frozen=True, slots=True)
class AssetInfo:
    """One logical asset the product can quote.

    Stocks carry nested ``forms`` and ``representations is None``.
    Non-stocks keep flat ``representations`` and ``forms is None``.
    """

    id: str
    category: AssetCategory
    representations: dict[str, str] | None
    forms: tuple[AssetForm, ...] | None = None


def _form(
    form_id: FormId,
    representations: dict[str, str],
    *,
    coverage: FormCoverage = "live",
) -> AssetForm:
    return AssetForm(
        id=form_id,
        form_class=form_class_of(form_id),
        representations=representations,
        coverage=coverage,
    )


# WHI-798 §3.3 / §6.1 representation map (Phase 1 blue chips).
_BLUE_CHIP_ROWS: Final[tuple[AssetInfo, ...]] = (
    AssetInfo(
        id="BTC",
        category="crypto_blue_chip",
        representations={
            "binance": "BTCUSDT",
            "bybit": "BTCUSDT",
            "hyperliquid": "BTC",
            "lighter": "BTC",
            "apex": "BTC-USDT",
            "humidifi": "cbBTC",
            "tessera_solana": "cbBTC",
            "bisonfi": "cbBTC",
            "tessera_base": "cbBTC",
            "tessera_bsc": "BTCB",
            "uniswap_eth": "WBTC",
            "aerodrome_base": "cbBTC",
            "pancakeswap_bsc": "BTCB",
        },
    ),
    AssetInfo(
        id="ETH",
        category="crypto_blue_chip",
        representations={
            "binance": "ETHUSDT",
            "bybit": "ETHUSDT",
            "hyperliquid": "ETH",
            "lighter": "ETH",
            "apex": "ETH-USDT",
            # Solana prop: Wormhole-bridged WETH (WHI-798 §3.3), not bare WETH.
            "humidifi": "Wormhole WETH",
            "tessera_solana": "Wormhole WETH",
            "bisonfi": "Wormhole WETH",
            "tessera_base": "WETH",
            "uniswap_eth": "WETH",
            "aerodrome_base": "WETH",
            # BSC bridged ETH — never bare logical "ETH" (WHI-809 / WHI-798 §3.3).
            "pancakeswap_bsc": "BSC ETH",
            # tessera_bsc: no ETH main market in WHI-797 v2 matrix — omit (same as SOL).
        },
    ),
    AssetInfo(
        id="SOL",
        category="crypto_blue_chip",
        representations={
            "binance": "SOLUSDT",
            "bybit": "SOLUSDT",
            "hyperliquid": "SOL",
            "lighter": "SOL",
            "apex": "SOL-USDT",
            "humidifi": "wSOL",
            "tessera_solana": "wSOL",
            "bisonfi": "wSOL",
            # EVM AMMs have no native SOL main market (WHI-798 §3.1).
        },
    ),
)

# WHI-798 §6.2.1 Phase-1 underlyings (underlying-first; forms as dimension).
_STOCK_ROWS: Final[tuple[AssetInfo, ...]] = (
    AssetInfo(
        id="NVDA",
        category="stock",
        representations=None,
        forms=(
            _form(
                "perp",
                {
                    "binance": "NVDAUSDT",
                    "bybit": "NVDAUSDT",
                    "hyperliquid": "xyz:NVDA",
                    "lighter": "NVDA",
                    "apex": "NVDA-USDT",
                },
            ),
            _form(
                "bstock",
                {
                    "binance": "NVDABUSDT",
                    "pancakeswap_bsc": "NVDAB",
                    "tessera_bsc": "NVDAB",
                },
            ),
            _form(
                "ondo",
                {
                    "pancakeswap_bsc": "NVDAon",
                    "tessera_bsc": "NVDAon",
                },
            ),
            _form(
                "xstock_cex",
                {"bybit": "NVDAXUSDT"},
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
        ),
    ),
    AssetInfo(
        id="TSLA",
        category="stock",
        representations=None,
        forms=(
            _form(
                "perp",
                {
                    "binance": "TSLAUSDT",
                    "bybit": "TSLAUSDT",
                    "hyperliquid": "xyz:TSLA",
                    "lighter": "TSLA",
                    "apex": "TSLA-USDT",
                },
            ),
            _form(
                "bstock",
                {
                    "binance": "TSLABUSDT",
                    "pancakeswap_bsc": "TSLAB",
                },
                coverage="unverified",
            ),
            _form(
                "xstock_cex",
                {"bybit": "TSLAXUSDT"},
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
            _form("ondo", {}, coverage="unverified"),
        ),
    ),
    AssetInfo(
        id="AAPL",
        category="stock",
        representations=None,
        forms=(
            _form(
                "perp",
                {
                    "binance": "AAPLUSDT",
                    "bybit": "AAPLUSDT",
                    "hyperliquid": "xyz:AAPL",
                    "lighter": "AAPL",
                    "apex": "AAPL-USDT",
                },
            ),
            _form(
                "bstock",
                {"binance": "AAPLBUSDT"},
                coverage="unverified",
            ),
            _form(
                "xstock_cex",
                {"bybit": "AAPLXUSDT"},
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
            _form("ondo", {}, coverage="unverified"),
        ),
    ),
    AssetInfo(
        id="MSFT",
        category="stock",
        representations=None,
        forms=(
            _form(
                "perp",
                {
                    "binance": "MSFTUSDT",
                    "bybit": "MSFTUSDT",
                    "hyperliquid": "xyz:MSFT",
                    "lighter": "MSFT",
                    "apex": "MSFT-USDT",
                },
            ),
            _form(
                "bstock",
                {"binance": "MSFTBUSDT"},
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
        ),
    ),
    AssetInfo(
        id="QQQ",
        category="stock",
        representations=None,
        forms=(
            _form(
                "bstock",
                {
                    "binance": "QQQBUSDT",
                    "pancakeswap_bsc": "QQQB",
                    "tessera_bsc": "QQQB",
                },
            ),
            _form(
                "perp",
                {
                    "binance": "QQQUSDT",
                    "bybit": "QQQUSDT",
                    "lighter": "QQQ",
                    "apex": "QQQ-USDT",
                },
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
        ),
    ),
    AssetInfo(
        id="SPCX",
        category="stock",
        representations=None,
        forms=(
            _form(
                "bstock",
                {
                    "binance": "SPCXBUSDT",
                    "pancakeswap_bsc": "SPCXB",
                    "tessera_bsc": "SPCXB",
                },
            ),
            _form(
                "xstock_cex",
                {"bybit": "SPCXXUSDT"},
                coverage="unverified",
            ),
            _form("xstock", {}, coverage="unverified"),
        ),
    ),
)

# WHI-798 §6.3 / §7.3 Others P0 (CEX + three perp DEXes).
_OTHER_ROWS: Final[tuple[AssetInfo, ...]] = (
    AssetInfo(
        id="DOGE",
        category="other",
        representations={
            "binance": "DOGEUSDT",
            "bybit": "DOGEUSDT",
            "hyperliquid": "DOGE",
            "lighter": "DOGE",
            "apex": "DOGE-USDT",
        },
    ),
    AssetInfo(
        id="WIF",
        category="other",
        representations={
            "binance": "WIFUSDT",
            "bybit": "WIFUSDT",
            "hyperliquid": "WIF",
            "lighter": "WIF",
            "apex": "WIF-USDT",
        },
    ),
    AssetInfo(
        id="XRP",
        category="other",
        representations={
            "binance": "XRPUSDT",
            "bybit": "XRPUSDT",
            "hyperliquid": "XRP",
            "lighter": "XRP",
            "apex": "XRP-USDT",
        },
    ),
    AssetInfo(
        id="SUI",
        category="other",
        representations={
            "binance": "SUIUSDT",
            "bybit": "SUIUSDT",
            "hyperliquid": "SUI",
            "lighter": "SUI",
            "apex": "SUI-USDT",
        },
    ),
    AssetInfo(
        id="LINK",
        category="other",
        representations={
            "binance": "LINKUSDT",
            "bybit": "LINKUSDT",
            "hyperliquid": "LINK",
            "lighter": "LINK",
            "apex": "LINK-USDT",
        },
    ),
    AssetInfo(
        id="AVAX",
        category="other",
        representations={
            "binance": "AVAXUSDT",
            "bybit": "AVAXUSDT",
            "hyperliquid": "AVAX",
            "lighter": "AVAX",
            "apex": "AVAX-USDT",
        },
    ),
    AssetInfo(
        id="ADA",
        category="other",
        representations={
            "binance": "ADAUSDT",
            "bybit": "ADAUSDT",
            "hyperliquid": "ADA",
            "lighter": "ADA",
            "apex": "ADA-USDT",
        },
    ),
    AssetInfo(
        id="BNB",
        category="other",
        representations={
            "binance": "BNBUSDT",
            "bybit": "BNBUSDT",
            "hyperliquid": "BNB",
            "lighter": "BNB",
            "apex": "BNB-USDT",
        },
    ),
)

_ALL_ROWS: Final[tuple[AssetInfo, ...]] = (
    _BLUE_CHIP_ROWS + _STOCK_ROWS + _OTHER_ROWS
)

ASSETS: Final[dict[str, AssetInfo]] = {a.id: a for a in _ALL_ROWS}

# USD-pegged quote legs treated as fungible for /simulate pair matching (WHI-814).
# Not catalog rows: venues pick USDC vs USDT themselves (WHI-798 §7.1).
# Includes "USD" for mid/peg recognition only — it is not a tradeable token.
USD_STABLES: Final[frozenset[str]] = frozenset({"USDC", "USDT", "USD"})

# Tradeable USD stablecoin symbols a client may offer as a /simulate pair leg
# (WHI-833). Subset of USD_STABLES; excludes "USD" (peg token, not pickable).
# Ordered for stable API presentation (picker order).
TRADEABLE_USD_STABLES: Final[tuple[str, ...]] = ("USDC", "USDT")

# Crypto blue chips use the §3.2 mid priority chain — must NOT absorb stocks/others.
CRYPTO_BLUE_CHIPS: Final[frozenset[str]] = frozenset(a.id for a in _BLUE_CHIP_ROWS)

# Stock underlyings (category=stock). Used by mid routing and form invariants.
STOCK_ASSETS: Final[frozenset[str]] = frozenset(a.id for a in _STOCK_ROWS)

# Underlyings with a live (or catalogued) equity perp form — P0/P1 mid chain.
# Includes underlyings whose perp form is live today; mid sampling may also use
# unverified perp venue symbols when present in the form map.
STOCK_PERP_UNDERLYINGS: Final[frozenset[str]] = frozenset(
    {
        "TSLA",
        "AAPL",
        "NVDA",
        "MSFT",
        "AMZN",
        "GOOGL",
        "META",
        "COIN",
        "HOOD",
        "MSTR",
    }
)

# Legacy per-token catalog ids → (underlying, form). Breaking rename (WHI-799 §6.7.3).
# API rejects these as top-level assets with a structured 422 migration hint.
LEGACY_ASSET_IDS: Final[dict[str, tuple[str, FormId]]] = {
    "NVDAB": ("NVDA", "bstock"),
    "NVDAON": ("NVDA", "ondo"),
    "QQQB": ("QQQ", "bstock"),
    "SPCXB": ("SPCX", "bstock"),
}

# Sentinel string for form=null in cache / store / stream keys (WHI-799 §6.2).
FORM_KEY_SENTINEL: Final[str] = "-"


def list_assets() -> list[AssetInfo]:
    """All catalogued logical assets (stable catalog order)."""
    return list(_ALL_ROWS)


def get_asset(asset_id: str) -> AssetInfo | None:
    """Lookup by logical id (case-insensitive)."""
    return ASSETS.get(asset_id.upper())


def is_stock_asset(asset_id: str) -> bool:
    """True when the catalog row is a stock underlying (form dimension applies)."""
    info = get_asset(asset_id)
    return info is not None and info.category == "stock"


def is_usd_stable(asset_id: str) -> bool:
    """True when the symbol is a recognized USD stablecoin (case-insensitive)."""
    return asset_id.upper() in USD_STABLES


def list_tradeable_usd_stables() -> list[str]:
    """Ordered tradeable USD stable symbols for simulate pair pickers (WHI-833)."""
    return list(TRADEABLE_USD_STABLES)


def list_simulate_pair_assets() -> list[str]:
    """Catalogued non-stable legs valid opposite a tradeable stable (WHI-833).

    Catalog rows are never USD stables today; filter defensively so a future
    catalog mistake cannot advertise an invalid pair. Uses ``list_assets`` for
    catalog order and ``is_usd_stable`` for the peg predicate (single SSOTs).
    """
    return [a.id for a in list_assets() if not is_usd_stable(a.id)]


def get_form(asset_id: str, form_id: str) -> AssetForm | None:
    """Return a form row for a stock underlying, or None."""
    info = get_asset(asset_id)
    if info is None or info.forms is None:
        return None
    key = form_id.lower()
    for form in info.forms:
        if form.id == key:
            return form
    return None


def live_forms(asset_id: str) -> list[AssetForm]:
    """Live forms for a stock (coverage=live). Empty for non-stocks / unknown."""
    info = get_asset(asset_id)
    if info is None or info.forms is None:
        return []
    return [f for f in info.forms if f.coverage == "live"]


def resolve_forms_filter(
    asset_id: str, forms: Sequence[str] | None
) -> list[str | None]:
    """Expand a ``forms=`` filter into fan-out form ids (None for non-stock).

    For stocks: default = all live forms; explicit list is validated against
    catalog form ids (any coverage). For non-stocks: always ``[None]``.
    """
    info = get_asset(asset_id)
    if info is None or info.category != "stock" or info.forms is None:
        return [None]
    if not forms:
        return [f.id for f in info.forms if f.coverage == "live"]
    known = {f.id for f in info.forms}
    out: list[str] = []
    for raw in forms:
        fid = raw.strip().lower()
        if fid not in known:
            raise ValueError(f"unknown form {raw!r} for asset {asset_id.upper()}")
        if fid not in out:
            out.append(fid)
    return out  # type: ignore[return-value]


def form_key(form: str | None) -> str:
    """String form for cache/store/stream keys (null → sentinel)."""
    return form if form else FORM_KEY_SENTINEL


def legacy_asset_migration(asset_id: str) -> tuple[str, FormId] | None:
    """If ``asset_id`` is a retired token id, return ``(underlying, form)``."""
    return LEGACY_ASSET_IDS.get(asset_id.upper())


def venues_for_form(asset_id: str, form_id: str | None) -> frozenset[str]:
    """Venues that have a representation label for this form (or flat map)."""
    info = get_asset(asset_id)
    if info is None:
        return frozenset()
    if form_id is None:
        if info.representations is None:
            return frozenset()
        return frozenset(info.representations)
    form = get_form(asset_id, form_id)
    if form is None:
        return frozenset()
    return frozenset(form.representations)


def representation_label(
    asset_id: str, venue: str, *, form: str | None = None
) -> str | None:
    """Display label for (asset, venue[, form]), or None if absent."""
    info = get_asset(asset_id)
    if info is None:
        return None
    if form is None:
        if info.representations is None:
            return None
        return info.representations.get(venue)
    form_row = get_form(asset_id, form)
    if form_row is None:
        return None
    return form_row.representations.get(venue)
