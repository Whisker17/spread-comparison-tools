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
    assert by_cat["stock"] == [
        "NVDA",
        "TSLA",
        "AAPL",
        "MSFT",
        "QQQ",
        "SPCX",
        "CRCL",
        "GOOGL",
        "AMD",
        "PLTR",
        "META",
        "AMZN",
        "SPY",
        "MSTR",
    ]
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
    # 3 blue chips + 14 stocks + 8 others
    assert len(rows) == 25
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
    for asset in ("TSLA", "NVDA", "AAPL", "MSFT", "CRCL", "GOOGL", "AMD", "SPY"):
        assert asset in STOCK_PERP_UNDERLYINGS


def test_whi884_p0_live_forms() -> None:
    """WHI-884 P0 underlyings expose verified venues as coverage=live."""
    # CRCL: 5 exact perps + BN bstock; *X catalogued but not live fan-out.
    crcl_live = {f.id: f for f in live_forms("CRCL")}
    assert set(crcl_live) == {"perp", "bstock"}
    assert crcl_live["perp"].representations["hyperliquid"] == "xyz:CRCL"
    assert crcl_live["bstock"].representations == {"binance": "CRCLBUSDT"}
    crcl_x = get_form("CRCL", "xstock_cex")
    assert crcl_x is not None and crcl_x.coverage == "unverified"

    # AMD Bybit wire is AMDSTOCKUSDT (not AMDUSDT).
    amd_perp = get_form("AMD", "perp")
    assert amd_perp is not None and amd_perp.coverage == "live"
    assert amd_perp.representations["bybit"] == "AMDSTOCKUSDT"
    assert amd_perp.representations["binance"] == "AMDUSDT"

    # SPY / QQQ: no HL exact in live map.
    spy_perp = get_form("SPY", "perp")
    assert spy_perp is not None and spy_perp.coverage == "live"
    assert "hyperliquid" not in spy_perp.representations
    qqq_perp = get_form("QQQ", "perp")
    assert qqq_perp is not None and qqq_perp.coverage == "live"
    assert "hyperliquid" not in qqq_perp.representations
    # QQQ still keeps live bstock (Phase-1).
    assert "bstock" in {f.id for f in live_forms("QQQ")}

    # AMZN xstock: mint exists, prop NO_ROUTES → unverified (still catalogued).
    amzn = get_asset("AMZN")
    assert amzn is not None and amzn.forms is not None
    xstock = next(f for f in amzn.forms if f.id == "xstock")
    assert xstock.coverage == "unverified"
    assert "xstock" not in {f.id for f in live_forms("AMZN")}
    # GOOGL/META/AMZN *X are live fan-out; CRCL *X is not (survey §5.2).
    assert "xstock_cex" in {f.id for f in live_forms("GOOGL")}
    assert "xstock_cex" not in {f.id for f in live_forms("CRCL")}

    # AMD/PLTR bstock catalogued but not live fan-out (survey §5.2 / WHI-890).
    amd_bstock = get_form("AMD", "bstock")
    assert amd_bstock is not None and amd_bstock.coverage == "unverified"
    pltr_bstock = get_form("PLTR", "bstock")
    assert pltr_bstock is not None and pltr_bstock.coverage == "unverified"
    assert "bstock" not in {f.id for f in live_forms("AMD")}
    assert "bstock" not in {f.id for f in live_forms("PLTR")}


def test_whi891_pancake_phase_a_bstock_live() -> None:
    """WHI-891: Phase-A Pancake bStocks are live; Tessera only on the quartet."""
    phase_a = {
        "SPY": "SPYB",
        "AAPL": "AAPLB",
        "TSLA": "TSLAB",
        "MSFT": "MSFTB",
        "GOOGL": "GOOGLB",
        "META": "METAB",
        "AMZN": "AMZNB",
    }
    for underlying, ticker in phase_a.items():
        bstock = get_form(underlying, "bstock")
        assert bstock is not None, underlying
        assert bstock.coverage == "live", underlying
        assert bstock.representations["pancakeswap_bsc"] == ticker
        # Tessera stayed absent_no_route for these (WHI-890 §5.2 / §8 Phase B).
        assert "tessera_bsc" not in bstock.representations
        assert "pancakeswap_bsc" in venues_for_form(underlying, "bstock")
        assert "tessera_bsc" not in venues_for_form(underlying, "bstock")

    # Existing green Tessera quartet unchanged.
    for underlying, ticker in (
        ("NVDA", "NVDAB"),
        ("QQQ", "QQQB"),
        ("SPCX", "SPCXB"),
    ):
        bstock = get_form(underlying, "bstock")
        assert bstock is not None
        assert bstock.representations["pancakeswap_bsc"] == ticker
        assert bstock.representations["tessera_bsc"] == ticker

    # Thin / zero-pool bStocks stay without Pancake (WHI-890 §4.2–§4.3).
    for underlying in ("CRCL", "AMD", "PLTR", "MSTR"):
        bstock = get_form(underlying, "bstock")
        assert bstock is not None
        assert "pancakeswap_bsc" not in bstock.representations
        if underlying in ("AMD", "PLTR"):
            assert bstock.coverage == "unverified"


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
