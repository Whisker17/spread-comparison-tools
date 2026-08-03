"""CEX symbol map with instrument dimension + multipliers (WHI-826)."""

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


def test_tokenized_spot_only() -> None:
    assert resolve_cex_symbol("QQQB", "spot") == "QQQBUSDT"
    assert resolve_cex_symbol("QQQB", "perp") is None
    assert "QQQB" in supported_cex_assets("spot")
    assert "QQQB" not in supported_cex_assets("perp")


def test_equity_perp_only() -> None:
    assert resolve_cex_symbol("TSLA", "spot") is None
    assert resolve_cex_symbol("TSLA", "perp") == "TSLAUSDT"
    assert "TSLA" not in supported_cex_assets("spot")
    assert "TSLA" in supported_cex_assets("perp")


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
