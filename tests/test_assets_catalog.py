"""Asset catalog coverage (WHI-826 / WHI-798 §6–§7)."""

from __future__ import annotations

from spread_compare.assets import (
    ASSETS,
    CRYPTO_BLUE_CHIPS,
    EQUITY_PERP_ASSETS,
    TOKENIZED_CEX_SPOT,
    TOKENIZED_UNDERLYING,
    TRADEABLE_USD_STABLES,
    USD_STABLES,
    get_asset,
    is_usd_stable,
    list_assets,
    list_simulate_pair_assets,
    list_tradeable_usd_stables,
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


def test_tradeable_stables_subset_of_peg_set() -> None:
    """Peg recognition keeps USD; tradeable list is USDC/USDT only (WHI-833)."""
    assert USD_STABLES == frozenset({"USDC", "USDT", "USD"})
    assert TRADEABLE_USD_STABLES == ("USDC", "USDT")
    assert set(TRADEABLE_USD_STABLES) < USD_STABLES
    assert "USD" not in TRADEABLE_USD_STABLES
    assert list_tradeable_usd_stables() == ["USDC", "USDT"]
    assert is_usd_stable("USD")
    assert is_usd_stable("usdc")
    assert not is_usd_stable("BTC")
    # Stables are not catalog rows; pair assets == full catalog ids.
    for stable in USD_STABLES:
        assert get_asset(stable) is None
    assert list_simulate_pair_assets() == [a.id for a in list_assets()]
