"""Asset catalog coverage (WHI-826 / WHI-798 §6–§7)."""

from __future__ import annotations

from spread_compare.assets import (
    ASSETS,
    CRYPTO_BLUE_CHIPS,
    EQUITY_PERP_ASSETS,
    TOKENIZED_CEX_SPOT,
    TOKENIZED_UNDERLYING,
    get_asset,
    list_assets,
)


def test_phase1_catalog_four_categories() -> None:
    rows = list_assets()
    by_cat: dict[str, list[str]] = {}
    for a in rows:
        by_cat.setdefault(a.category, []).append(a.id)
    assert by_cat["crypto_blue_chip"] == ["BTC", "ETH", "SOL"]
    assert by_cat["tokenized_stock"] == ["QQQB", "SPCXB", "NVDAB", "NVDAON"]
    assert by_cat["equity_perp"] == ["TSLA", "NVDA", "AAPL", "MSFT"]
    assert by_cat["other"] == [
        "DOGE",
        "WIF",
        "XRP",
        "SUI",
        "LINK",
        "AVAX",
        "ADA",
        "BNB",
    ]
    assert len(rows) == 19
    assert set(ASSETS) == {a.id for a in rows}


def test_crypto_blue_chips_not_absorb_new_rows() -> None:
    """Mid routing depends on CRYPTO_BLUE_CHIPS staying blue-chip-only."""
    assert CRYPTO_BLUE_CHIPS == frozenset({"BTC", "ETH", "SOL"})
    assert "DOGE" not in CRYPTO_BLUE_CHIPS
    assert "TSLA" not in CRYPTO_BLUE_CHIPS
    assert "QQQB" not in CRYPTO_BLUE_CHIPS


def test_representation_labels() -> None:
    qqqb = get_asset("qqqb")
    assert qqqb is not None
    assert qqqb.representations["binance"] == "QQQBUSDT"
    assert qqqb.representations["pancakeswap_bsc"] == "QQQB"
    tsla = get_asset("TSLA")
    assert tsla is not None
    assert tsla.representations["hyperliquid"] == "xyz:TSLA"
    assert tsla.representations["apex"] == "TSLA-USDT"


def test_mid_routing_seeds_cover_catalog_stocks() -> None:
    for asset in ("QQQB", "SPCXB", "NVDAB"):
        assert asset in TOKENIZED_CEX_SPOT
    assert TOKENIZED_UNDERLYING["NVDAON"] == "NVDA"
    for asset in ("TSLA", "NVDA", "AAPL", "MSFT"):
        assert asset in EQUITY_PERP_ASSETS
