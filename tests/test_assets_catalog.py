"""Asset catalog coverage (WHI-826 / WHI-798 §6–§7 / WHI-881 underlying-first)."""

from __future__ import annotations

import spread_compare.adapters  # noqa: F401 — ensure registration
from spread_compare.adapters import get as get_adapter
from spread_compare.adapters.amm_pancakeswap import PancakeSwapBscAdapter
from spread_compare.adapters.prop_kyberswap import TesseraBscAdapter
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
from spread_compare.cex_symbols import resolve_cex_symbol
from spread_compare.perp_symbols import (
    UnsupportedPerpSymbolError,
    resolve_apex_base,
    resolve_hl_coin,
    resolve_lighter_symbol,
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

    # AMZN xstock: mint exists, prop NO_ROUTES → absent (WHI-890 §6.2 / WHI-892).
    amzn = get_asset("AMZN")
    assert amzn is not None and amzn.forms is not None
    xstock = next(f for f in amzn.forms if f.id == "xstock")
    assert xstock.coverage == "absent"
    assert xstock.representations == {}
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


def test_catalog_bsc_stock_venues_no_phantoms() -> None:
    """WHI-891 AC: any catalogued Pancake/Tessera stock row is adapter-supported.

    Iterates *all* forms (not only coverage=live): an unverified form can still
    carry a representation and be requested via ``forms=`` on GET /quotes
    (venues_for_form ignores coverage). Pre-PR TSLA/bstock was the phantom
    shape — ``pancakeswap_bsc`` listed without a resolvable token path.

    Checks both ``supported_assets`` membership and form→token resolution so a
    catalog representation on a non-mapped form of a supported underlying
    (e.g. TSLA/xstock → pancakeswap_bsc) cannot pass silently.
    """
    bsc_venues = frozenset({"pancakeswap_bsc", "tessera_bsc"})
    for asset in list_assets():
        if asset.category != "stock" or asset.forms is None:
            continue
        for form in asset.forms:
            for venue in form.representations:
                if venue not in bsc_venues:
                    continue
                adapter = get_adapter(venue)
                supported = {a.upper() for a in adapter.supported_assets()}
                assert asset.id.upper() in supported, (
                    f"{asset.id}/{form.id} catalogs {venue} but adapter "
                    f"supported_assets()={sorted(supported)}"
                )
                if isinstance(adapter, PancakeSwapBscAdapter):
                    token = adapter._base_token(asset.id, form=form.id)
                    assert token.address
                elif isinstance(adapter, TesseraBscAdapter):
                    token = adapter._token_for_form(asset.id, form=form.id)
                    assert token is not None


def test_catalog_stock_venues_adapter_resolvable() -> None:
    """WHI-892: every catalogued (underlying, form, venue) must resolve.

    Symbol/token map resolution only (cold adapters may return a narrow
    ``supported_assets`` before startup meta load — e.g. Lighter/ApeX). A
    phantom is a catalog label the static maps cannot turn into a wire id.
    """
    cex = frozenset({"binance", "bybit"})
    for asset in list_assets():
        if asset.category != "stock" or asset.forms is None:
            continue
        for form in asset.forms:
            for venue, label in form.representations.items():
                key = f"{asset.id}/{form.id}/{venue} label={label!r}"
                if venue in cex:
                    book = "perp" if form.id == "perp" else "spot"
                    sym = resolve_cex_symbol(
                        asset.id, book, form=form.id, venue=venue
                    )
                    assert sym, f"CEX unresolvable: {key}"
                elif venue == "hyperliquid":
                    try:
                        coin = resolve_hl_coin(asset.id)
                    except UnsupportedPerpSymbolError as exc:
                        raise AssertionError(f"HL unresolvable: {key}") from exc
                    assert coin.venue_symbol
                elif venue == "lighter":
                    assert resolve_lighter_symbol(asset.id).venue_symbol, key
                elif venue == "apex":
                    assert resolve_apex_base(asset.id).venue_symbol, key
                elif venue == "pancakeswap_bsc":
                    adapter = get_adapter(venue)
                    assert isinstance(adapter, PancakeSwapBscAdapter)
                    token = adapter._base_token(asset.id, form=form.id)
                    assert token.address, key
                elif venue == "tessera_bsc":
                    adapter = get_adapter(venue)
                    assert isinstance(adapter, TesseraBscAdapter)
                    token = adapter._token_for_form(asset.id, form=form.id)
                    assert token is not None and token.address, key
                else:
                    raise AssertionError(
                        f"catalog lists venue {venue!r} with no resolvability "
                        f"check (would be a silent phantom): {key}"
                    )


def test_xstock_forms_absent_empty_venues() -> None:
    """WHI-892: probed-and-routeless xstock is absent, not silent empty unverified."""
    for asset in list_assets():
        if asset.category != "stock" or asset.forms is None:
            continue
        xstock = get_form(asset.id, "xstock")
        if xstock is None:
            continue
        assert xstock.coverage == "absent", asset.id
        assert xstock.representations == {}, asset.id


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
