"""WS config + mid max-age for WS quotes (WHI-847)."""

from spread_compare.settings import clear_settings_cache, load_mid_settings, load_ws_settings


def test_load_ws_settings() -> None:
    clear_settings_cache()
    # conftest forces enabled=False for offline suite
    ws = load_ws_settings()
    assert ws.enabled is False
    assert ws.max_book_age_sec == 5.0
    assert ws.reconnect_min_sec == 1.0
    assert ws.reconnect_max_sec == 30.0
    assert ws.fast_mid_poll_interval_sec == 1.0
    assert ws.streams.binance_spot is True


def test_mid_max_age_for_ws_quote() -> None:
    clear_settings_cache()
    mid = load_mid_settings()
    assert mid.max_age_for_ws_quote_sec == 2.0
