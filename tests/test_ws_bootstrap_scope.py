"""WS bootstrap subscription set is product-scoped (WHI-855).

Reconnect must not re-subscribe the full venue universe (300+ HL coins etc.).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from spread_compare.perp_symbols import HL_PHASE1_ASSETS, resolve_hl_coin
from spread_compare.ws_bootstrap import (
    _apex_cross_symbols,
    _hl_coins,
    _lighter_markets,
)


def test_hl_coins_are_phase1_only_not_full_meta() -> None:
    # No adapter needed — pure phase-1 map.
    coins = _hl_coins()
    expected = {resolve_hl_coin(a).venue_symbol for a in HL_PHASE1_ASSETS}
    assert set(coins) == expected
    # Bound well below the 300+ full-meta count that shipped broken.
    assert len(coins) <= len(HL_PHASE1_ASSETS)
    assert len(coins) < 50


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
    assert len(symbols) <= len(HL_PHASE1_ASSETS)
