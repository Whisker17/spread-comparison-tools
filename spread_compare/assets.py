"""Logical asset catalog + per-venue representation labels (WHI-798 §3.3).

Static product metadata for ``GET /assets``. Adapters still own mint/address
resolution; this table is the frontend-facing label map only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

AssetCategory = Literal["crypto_blue_chip", "tokenized_stock", "equity_perp", "other"]


@dataclass(frozen=True, slots=True)
class AssetInfo:
    """One logical asset the product can quote."""

    id: str
    category: AssetCategory
    # Venue slug → display representation label (not necessarily the wire symbol).
    representations: dict[str, str]


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

# WHI-798 §6.2 P0-A bStocks three-way (Binance spot × Pancake × Tessera BSC).
_TOKENIZED_STOCK_ROWS: Final[tuple[AssetInfo, ...]] = (
    AssetInfo(
        id="QQQB",
        category="tokenized_stock",
        representations={
            "binance": "QQQBUSDT",
            "pancakeswap_bsc": "QQQB",
            "tessera_bsc": "QQQB",
        },
    ),
    AssetInfo(
        id="SPCXB",
        category="tokenized_stock",
        representations={
            "binance": "SPCXBUSDT",
            "pancakeswap_bsc": "SPCXB",
            "tessera_bsc": "SPCXB",
        },
    ),
    AssetInfo(
        id="NVDAB",
        category="tokenized_stock",
        representations={
            "binance": "NVDABUSDT",
            "pancakeswap_bsc": "NVDAB",
            "tessera_bsc": "NVDAB",
        },
    ),
    AssetInfo(
        id="NVDAON",
        category="tokenized_stock",
        representations={
            # No Binance spot for Ondo form; Tessera + Pancake for BSC comparison.
            "pancakeswap_bsc": "NVDAon",
            "tessera_bsc": "NVDAon",
        },
    ),
)

# WHI-798 §6.2 P0-B equity perps (exact ticker on five venues).
_EQUITY_PERP_ROWS: Final[tuple[AssetInfo, ...]] = (
    AssetInfo(
        id="TSLA",
        category="equity_perp",
        representations={
            "binance": "TSLAUSDT",
            "bybit": "TSLAUSDT",
            "hyperliquid": "xyz:TSLA",
            "lighter": "TSLA",
            "apex": "TSLA-USDT",
        },
    ),
    AssetInfo(
        id="NVDA",
        category="equity_perp",
        representations={
            "binance": "NVDAUSDT",
            "bybit": "NVDAUSDT",
            "hyperliquid": "xyz:NVDA",
            "lighter": "NVDA",
            "apex": "NVDA-USDT",
        },
    ),
    AssetInfo(
        id="AAPL",
        category="equity_perp",
        representations={
            "binance": "AAPLUSDT",
            "bybit": "AAPLUSDT",
            "hyperliquid": "xyz:AAPL",
            "lighter": "AAPL",
            "apex": "AAPL-USDT",
        },
    ),
    AssetInfo(
        id="MSFT",
        category="equity_perp",
        representations={
            "binance": "MSFTUSDT",
            "bybit": "MSFTUSDT",
            "hyperliquid": "xyz:MSFT",
            "lighter": "MSFT",
            "apex": "MSFT-USDT",
        },
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
    _BLUE_CHIP_ROWS
    + _TOKENIZED_STOCK_ROWS
    + _EQUITY_PERP_ROWS
    + _OTHER_ROWS
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

# Tokenized stocks with a CEX spot book use that book's TOB as mid (WHI-799 §3.3).
TOKENIZED_CEX_SPOT: Final[dict[str, str]] = {
    # asset -> preferred mid source venue for spot TOB
    "QQQB": "binance",
    "SPCXB": "binance",
    "NVDAB": "binance",
    "TSLAB": "binance",
    "TSLAX": "bybit",
    "NVDAX": "bybit",
}

# Tokenized without CEX spot → map to equity underlying for equity_ref mid (WHI-799 §3.3).
TOKENIZED_UNDERLYING: Final[dict[str, str]] = {
    "NVDAON": "NVDA",
    "TSLAON": "TSLA",
    "AAPLON": "AAPL",
    "GOOGLON": "GOOGL",
    "MUON": "MU",
}

# Equity perps / stocks without a crypto index use mark median (WHI-799 §3.3).
EQUITY_PERP_ASSETS: Final[frozenset[str]] = frozenset(
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


def list_assets() -> list[AssetInfo]:
    """All catalogued logical assets (stable catalog order)."""
    return list(_ALL_ROWS)


def get_asset(asset_id: str) -> AssetInfo | None:
    """Lookup by logical id (case-insensitive)."""
    return ASSETS.get(asset_id.upper())


def is_usd_stable(asset_id: str) -> bool:
    """True when the symbol is a recognized USD stablecoin (case-insensitive)."""
    return asset_id.upper() in USD_STABLES


def list_tradeable_usd_stables() -> list[str]:
    """Ordered tradeable USD stable symbols for simulate pair pickers (WHI-833)."""
    return list(TRADEABLE_USD_STABLES)


def list_simulate_pair_assets() -> list[str]:
    """Catalogued non-stable legs valid opposite a tradeable stable (WHI-833).

    Catalog rows are never USD stables today; filter defensively so a future
    catalog mistake cannot advertise an invalid pair.
    """
    return [a.id for a in _ALL_ROWS if a.id not in USD_STABLES]
