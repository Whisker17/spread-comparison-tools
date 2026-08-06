"""WS bootstrap subscription set is product-scoped (WHI-855).

Reconnect must not re-subscribe the full venue universe (300+ HL coins etc.).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from spread_compare.perp_symbols import (
    HL_PHASE1_ASSETS,
    PERP_DEX_SERVED_ASSETS,
    UnsupportedPerpSymbolError,
    resolve_hl_coin,
)
from spread_compare.ws_bootstrap import (
    _apex_cross_symbols,
    _cex_symbols,
    _hl_coins,
    _lighter_markets,
)


def test_hl_coins_are_exact_product_markets_not_full_meta() -> None:
    # No adapter needed — pure product map. SPY/QQQ have no exact HL market.
    coins = _hl_coins()
    expected = {resolve_hl_coin(a).venue_symbol for a in HL_PHASE1_ASSETS}
    assert set(coins) == expected
    assert "SPY" not in HL_PHASE1_ASSETS
    assert "QQQ" not in HL_PHASE1_ASSETS
    assert "SPY" in PERP_DEX_SERVED_ASSETS
    assert "QQQ" in PERP_DEX_SERVED_ASSETS
    assert "xyz:SPY" not in coins
    assert "SPY" not in coins
    assert "xyz:QQQ" not in coins
    assert "QQQ" not in coins
    assert "xyz:CRCL" in coins
    assert "xyz:AMD" in coins
    # Bound well below the 300+ full-meta count that shipped broken.
    assert len(coins) <= len(HL_PHASE1_ASSETS)
    assert len(coins) < 50
    # Structural: bare SPY/QQQ must not resolve to a fake main-book coin.
    for bare in ("SPY", "QQQ"):
        with pytest.raises(UnsupportedPerpSymbolError):
            resolve_hl_coin(bare)


def test_cex_ws_includes_p0_books_and_amd_bybit_wire() -> None:
    bn_fut = _cex_symbols("perp", venue="binance")
    by_lin = _cex_symbols("perp", venue="bybit")
    assert "CRCLUSDT" in bn_fut
    assert "AMDUSDT" in bn_fut
    assert "AMDSTOCKUSDT" in by_lin
    assert "AMDUSDT" not in by_lin
    bn_spot = _cex_symbols("spot", venue="binance", tokenized_forms=("bstock",))
    assert "CRCLBUSDT" in bn_spot
    assert "SPYBUSDT" in bn_spot
    # WHI-891: TSLA/AAPL/MSFT bstock flip to live (BN *BUSDT exchangeInfo
    # TRADING verified 2026-08-06). GOOGL/META/AMZN/SPY were already live.
    assert "TSLABUSDT" in bn_spot
    assert "AAPLBUSDT" in bn_spot
    assert "MSFTBUSDT" in bn_spot
    assert "GOOGLBUSDT" in bn_spot
    assert "METABUSDT" in bn_spot
    assert "AMZNBUSDT" in bn_spot
    # AMD/PLTR bstock is catalog-only (unverified) — not WS-subscribed.
    assert "AMDBUSDT" not in bn_spot
    assert "PLTRBUSDT" not in bn_spot
    by_spot = _cex_symbols(
        "spot", venue="bybit", tokenized_forms=("xstock_cex",)
    )
    # CRCL *X is unverified (survey §5.2); GOOGL/META/AMZN *X are live.
    assert "CRCLXUSDT" not in by_spot
    assert "GOOGLXUSDT" in by_spot
    # bStocks never on Bybit spot subscribe.
    assert "CRCLBUSDT" not in by_spot


def test_lighter_markets_filter_to_phase1(monkeypatch: pytest.MonkeyPatch) -> None:
    import spread_compare.ws_bootstrap as boot

    # Adapter table holds hundreds of markets; bootstrap must keep phase-1 only.
    fake_markets = {
        "BTC": SimpleNamespace(market_id=0),
        "ETH": SimpleNamespace(market_id=1),
        "OBSCURECOIN": SimpleNamespace(market_id=99),
        "ZZZ": SimpleNamespace(market_id=100),
    }
    adapter = MagicMock()
    adapter._markets_by_symbol = fake_markets

    monkeypatch.setattr(
        boot, "_safe_adapter", lambda slug: adapter if slug == "lighter" else None
    )
    markets = _lighter_markets()
    assert markets == {"0": "BTC", "1": "ETH"}
    assert "99" not in markets
    assert "100" not in markets


def test_apex_symbols_filter_to_phase1(monkeypatch: pytest.MonkeyPatch) -> None:
    import spread_compare.ws_bootstrap as boot

    fake = {
        "BTC": SimpleNamespace(cross_symbol_name="BTCUSDT"),
        "ETH": SimpleNamespace(cross_symbol_name="ETHUSDT"),
        "RAREPERP": SimpleNamespace(cross_symbol_name="RAREPERPUSDT"),
    }
    adapter = MagicMock()
    adapter._symbols_by_base = fake

    monkeypatch.setattr(
        boot, "_safe_adapter", lambda slug: adapter if slug == "apex" else None
    )
    symbols = _apex_cross_symbols()
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols
    assert "RAREPERPUSDT" not in symbols
    assert len(symbols) <= len(PERP_DEX_SERVED_ASSETS)
