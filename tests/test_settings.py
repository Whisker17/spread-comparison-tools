"""Typed config loading (WHI-807)."""

from spread_compare.settings import (
    clear_settings_cache,
    load_aggregator_settings,
    load_api_settings,
    load_mid_settings,
)


def test_load_mid_settings_defaults() -> None:
    clear_settings_cache()
    mid = load_mid_settings()
    assert mid.force_pyth is False
    assert mid.stale_threshold_sec == 5
    assert mid.cache_max_age_sec == 30
    assert mid.http_timeout_sec == 5.0
    assert "BTC" in mid.pyth_feed_ids


def test_load_aggregator_settings_defaults() -> None:
    clear_settings_cache()
    agg = load_aggregator_settings()
    assert agg.venue_timeout_sec == 3.0
    assert agg.response_cache_ttl_sec == 2.0


def test_load_api_settings_cors_defaults() -> None:
    clear_settings_cache()
    api = load_api_settings()
    assert "http://localhost:3000" in api.cors_origins
    assert "http://127.0.0.1:3000" in api.cors_origins
