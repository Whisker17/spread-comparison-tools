"""WS config + mid max-age for WS quotes (WHI-847 / WHI-855)."""

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
    # WHI-855 feed-repair tunables (must load from committed yaml, not Field defaults)
    assert ws.bybit_spot_subscribe_chunk == 10
    assert ws.bybit_linear_subscribe_chunk == 20
    assert ws.apex_subscribe_chunk == 1
    assert ws.binance_spot_min_resync_interval_sec == 2.0
    assert ws.binance_spot_resync_weight == 50
    assert ws.binance_spot_resync_weight_budget_per_min == 1500
    assert ws.default_transport_ping_interval_sec == 20.0
    assert ws.lighter_resync_snapshot_timeout_sec == 15.0
    assert ws.hyperliquid_app_ping_interval_sec == 20.0
    assert ws.hyperliquid_transport_ping is False


def test_mid_max_age_for_ws_quote() -> None:
    clear_settings_cache()
    mid = load_mid_settings()
    assert mid.max_age_for_ws_quote_sec == 2.0
