"""Typed config loading (WHI-807 / WHI-836)."""

from spread_compare.settings import (
    AggregatorSettings,
    clear_settings_cache,
    load_aggregator_settings,
    load_api_settings,
    load_jupiter_settings,
    load_mid_settings,
    load_venue_settings,
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
    assert agg.response_cache_ttl_sec == 20.0
    assert agg.venue_timeout_by_class["prop_amm"] == 12.0  # WHI-838 five-tier headroom
    assert agg.venue_timeout_by_class["amm_dex"] == 6.0
    assert agg.timeout_for("cex") == 3.0
    assert agg.timeout_for("prop_amm") == 12.0
    assert agg.timeout_for("amm_dex") == 6.0
    assert agg.timeout_for("perp_dex") == 3.0


def test_load_jupiter_settings_defaults() -> None:
    clear_settings_cache()
    jup = load_jupiter_settings()
    assert jup.keyless_capacity == 5
    assert jup.keyed_capacity == 10
    assert jup.window_sec == 1.0
    assert jup.adapt_from_headers is True


def test_jupiter_keyless_cannot_exceed_keyed() -> None:
    import pytest
    from pydantic import ValidationError

    from spread_compare.settings import JupiterSettings

    with pytest.raises(ValidationError, match="keyless_capacity"):
        JupiterSettings(
            keyless_capacity=20,
            keyed_capacity=10,
            window_sec=1.0,
            adapt_from_headers=True,
        )


def test_aggregator_timeout_for_fallback() -> None:
    agg = AggregatorSettings(
        venue_timeout_sec=2.5,
        venue_timeout_by_class={"prop_amm": 9.0},
        response_cache_ttl_sec=0,
    )
    assert agg.timeout_for("prop_amm") == 9.0
    assert agg.timeout_for("cex") == 2.5


def test_load_api_settings_cors_defaults() -> None:
    clear_settings_cache()
    api = load_api_settings()
    assert "http://localhost:3000" in api.cors_origins
    assert "http://127.0.0.1:3000" in api.cors_origins
    assert api.simulate_min_interval_sec == 2.0


def test_load_venue_settings_defaults() -> None:
    clear_settings_cache()
    venues = load_venue_settings()
    assert venues.disabled == []
    assert venues.startup_retry_interval_sec == 60.0
    assert venues.startup_retry_backoff_multiplier == 2.0
    assert venues.startup_retry_max_interval_sec == 300.0
