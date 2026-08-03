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


# WHI-798 §3.3 representation map (Phase 1 blue chips).
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
            "humidifi": "WETH",
            "tessera_solana": "WETH",
            "bisonfi": "WETH",
            "tessera_base": "WETH",
            "uniswap_eth": "WETH",
            "aerodrome_base": "WETH",
            "pancakeswap_bsc": "ETH",
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

ASSETS: Final[dict[str, AssetInfo]] = {a.id: a for a in _BLUE_CHIP_ROWS}

# Crypto blue chips use the §3.2 mid priority chain.
CRYPTO_BLUE_CHIPS: Final[frozenset[str]] = frozenset(ASSETS)

# Tokenized stocks with a CEX spot book use that book's TOB as mid (WHI-799 §3.3).
# Minimal seed for mid routing; full stocks catalog lands with WHI-810.
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

# Equity perps / others without a crypto index use mark median (WHI-799 §3.3).
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
    """All catalogued logical assets (stable id order)."""
    return list(_BLUE_CHIP_ROWS)


def get_asset(asset_id: str) -> AssetInfo | None:
    """Lookup by logical id (case-insensitive)."""
    return ASSETS.get(asset_id.upper())
