"""CEX symbol map with instrument dimension + multipliers (WHI-826 / WHI-881)."""

from __future__ import annotations

from decimal import Decimal

from spread_compare.cex_symbols import (
    CexSymbol,
    get_cex_symbol,
    resolve_cex_multiplier,
    resolve_cex_symbol,
    supported_cex_assets,
)


def test_blue_chip_same_both_sides() -> None:
    assert resolve_cex_symbol("BTC", "spot") == "BTCUSDT"
    assert resolve_cex_symbol("BTC", "perp") == "BTCUSDT"
    assert resolve_cex_multiplier("BTC", "perp") == Decimal(1)


def test_tokenized_bstock_form_spot_only() -> None:
    assert resolve_cex_symbol("QQQ", "spot", form="bstock") == "QQQBUSDT"
    assert resolve_cex_symbol("QQQ", "perp", form="bstock") is None
    assert resolve_cex_symbol("NVDA", "spot", form="bstock") == "NVDABUSDT"
    assert "QQQ" in supported_cex_assets("spot", form="bstock")
    assert "QQQ" not in supported_cex_assets("perp", form="bstock")
    # Bare token ids no longer resolve.
    assert resolve_cex_symbol("QQQB", "spot") is None


def test_equity_perp_form() -> None:
    assert resolve_cex_symbol("TSLA", "spot", form="perp") is None
    assert resolve_cex_symbol("TSLA", "perp", form="perp") == "TSLAUSDT"
    # Bare stock without form never aliases to perp (WHI-881).
    assert resolve_cex_symbol("TSLA", "perp") is None
    assert resolve_cex_symbol("TSLA", "spot") is None
    assert "TSLA" not in supported_cex_assets("spot")
    assert "TSLA" in supported_cex_assets("perp")
    assert "TSLA" in supported_cex_assets("perp", form="perp")


def test_pepe_spot_vs_perp_multiplier() -> None:
    entry = get_cex_symbol("PEPE")
    assert isinstance(entry, CexSymbol)
    assert entry.spot == "PEPEUSDT"
    assert entry.perp == "1000PEPEUSDT"
    assert resolve_cex_multiplier("PEPE", "spot") == Decimal(1)
    assert resolve_cex_multiplier("PEPE", "perp") == Decimal(1000)


def test_others_present() -> None:
    for asset in ("DOGE", "WIF", "XRP", "SUI", "LINK", "AVAX", "ADA", "BNB"):
        assert resolve_cex_symbol(asset, "spot") == f"{asset}USDT"
        assert resolve_cex_symbol(asset, "perp") == f"{asset}USDT"


def test_unknown_returns_none() -> None:
    assert resolve_cex_symbol("NOTACOIN", "spot") is None
    assert resolve_cex_multiplier("NOTACOIN", "perp") == Decimal(1)


def test_whi884_p0_equity_perps_and_bstocks() -> None:
    for asset in ("CRCL", "GOOGL", "PLTR", "META", "AMZN", "SPY", "MSTR"):
        assert resolve_cex_symbol(asset, "perp", form="perp") == f"{asset}USDT"
        assert asset in supported_cex_assets("perp", form="perp")
    assert resolve_cex_symbol("CRCL", "spot", form="bstock") == "CRCLBUSDT"
    assert resolve_cex_symbol("SPY", "spot", form="bstock") == "SPYBUSDT"
    assert resolve_cex_symbol("GOOGL", "spot", form="xstock_cex") == "GOOGLXUSDT"
    assert "CRCL" in supported_cex_assets("spot", form="bstock")
    assert "GOOGL" in supported_cex_assets("spot", form="xstock_cex")


def test_amd_bybit_venue_override() -> None:
    """Bybit linear is AMDSTOCKUSDT; Binance TradFi stays AMDUSDT (WHI-883)."""
    assert resolve_cex_symbol("AMD", "perp", form="perp") == "AMDUSDT"
    assert (
        resolve_cex_symbol("AMD", "perp", form="perp", venue="binance") == "AMDUSDT"
    )
    assert (
        resolve_cex_symbol("AMD", "perp", form="perp", venue="bybit")
        == "AMDSTOCKUSDT"
    )
    assert resolve_cex_symbol("AMD", "spot", form="bstock") == "AMDBUSDT"
