"""Asset catalog coverage (WHI-826 / WHI-798 §6–§7 / WHI-881 underlying-first)."""

from __future__ import annotations

from spread_compare.assets import (
    ASSETS,
    CRYPTO_BLUE_CHIPS,
    LEGACY_ASSET_IDS,
    STOCK_ASSETS,
    STOCK_PERP_UNDERLYINGS,
    TRADEABLE_USD_STABLES,
    USD_STABLES,
    form_class_of,
    get_asset,
    get_form,
    is_stock_asset,
    is_usd_stable,
    legacy_asset_migration,
    list_assets,
    list_simulate_pair_assets,
    list_tradeable_usd_stables,
    live_forms,
    resolve_forms_filter,
    venues_for_form,
)


def test_phase1_catalog_three_categories() -> None:
    rows = list_assets()
    by_cat: dict[str, list[str]] = {}
    for a in rows:
        by_cat.setdefault(a.category, []).append(a.id)
    assert by_cat["crypto_blue_chip"] == ["BTC", "ETH", "SOL"]
    assert by_cat["stock"] == ["NVDA", "TSLA", "AAPL", "MSFT", "QQQ", "SPCX"]
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
    assert len(rows) == 17
    assert set(ASSETS) == {a.id for a in rows}
    assert STOCK_ASSETS == frozenset(by_cat["stock"])


def test_crypto_blue_chips_not_absorb_new_rows() -> None:
    """Mid routing depends on CRYPTO_BLUE_CHIPS staying blue-chip-only."""
    assert CRYPTO_BLUE_CHIPS == frozenset({"BTC", "ETH", "SOL"})
    assert "DOGE" not in CRYPTO_BLUE_CHIPS
    assert "TSLA" not in CRYPTO_BLUE_CHIPS
    assert "QQQ" not in CRYPTO_BLUE_CHIPS


def test_stock_forms_nested_not_flat_representations() -> None:
    nvda = get_asset("NVDA")
    assert nvda is not None
    assert nvda.category == "stock"
    assert nvda.representations is None
    assert nvda.forms is not None
    form_ids = {f.id for f in nvda.forms}
    assert {"perp", "bstock", "ondo"} <= form_ids
    bstock = get_form("NVDA", "bstock")
    assert bstock is not None
    assert bstock.representations["binance"] == "NVDABUSDT"
    assert bstock.representations["pancakeswap_bsc"] == "NVDAB"
    assert bstock.representations["tessera_bsc"] == "NVDAB"
    ondo = get_form("NVDA", "ondo")
    assert ondo is not None
    assert ondo.representations["tessera_bsc"] == "NVDAon"
    perp = get_form("TSLA", "perp")
    assert perp is not None
    assert perp.representations["hyperliquid"] == "xyz:TSLA"
    assert perp.representations["apex"] == "TSLA-USDT"


def test_live_forms_and_filter() -> None:
    live = {f.id for f in live_forms("NVDA")}
    assert "perp" in live
    assert "bstock" in live
    assert "ondo" in live
    # Unverified forms excluded from default expansion.
    assert "xstock_cex" not in live
    assert resolve_forms_filter("NVDA", None) == ["perp", "bstock", "ondo"]
    assert resolve_forms_filter("NVDA", ["ondo"]) == ["ondo"]
    assert resolve_forms_filter("BTC", None) == [None]
    assert venues_for_form("NVDA", "bstock") == frozenset(
        {"binance", "pancakeswap_bsc", "tessera_bsc"}
    )


def test_legacy_asset_ids() -> None:
    assert LEGACY_ASSET_IDS["NVDAB"] == ("NVDA", "bstock")
    assert LEGACY_ASSET_IDS["NVDAON"] == ("NVDA", "ondo")
    assert LEGACY_ASSET_IDS["QQQB"] == ("QQQ", "bstock")
    assert LEGACY_ASSET_IDS["SPCXB"] == ("SPCX", "bstock")
    assert legacy_asset_migration("nvdab") == ("NVDA", "bstock")
    assert get_asset("NVDAB") is None
    assert not is_stock_asset("NVDAB")


def test_form_class_of() -> None:
    assert form_class_of("perp") == "perp"
    assert form_class_of("bstock") == "tokenized"
    assert form_class_of("ondo") == "tokenized"


def test_stock_perp_underlyings_mid_seed() -> None:
    for asset in ("TSLA", "NVDA", "AAPL", "MSFT"):
        assert asset in STOCK_PERP_UNDERLYINGS


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
