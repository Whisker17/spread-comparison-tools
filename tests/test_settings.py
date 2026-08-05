"""Typed config loading (WHI-807 / WHI-836)."""

from spread_compare.settings import (
    AggregatorSettings,
    clear_settings_cache,
    load_aggregator_settings,
    load_api_settings,
    load_jupiter_settings,
    load_mid_settings,
    load_monitor_settings,
    load_rpc_settings,
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
    assert agg.response_cache_ttl_sec == 35.0  # WHI-844: above FE 30s poll
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
    # WHI-849: multi-port localhost FE origins are committed, not only in *.local.yaml.
    assert "http://localhost:3001" in api.cors_origins
    assert "http://localhost:3002" in api.cors_origins
    assert api.simulate_min_interval_sec == 2.0


def test_load_monitor_settings_defaults() -> None:
    clear_settings_cache()
    mon = load_monitor_settings()
    assert mon.enabled is True
    assert mon.probe_asset == "BTC"
    assert mon.sweep_stale_multiplier > 1
    assert mon.ws_disconnected_alert_sec > 0
    assert mon.rate_limit_count_threshold >= 1
    assert mon.ws_books_sync_grace_sec > 0
    assert mon.probe_min_healthy_books_per_stream >= 1


def test_load_venue_settings_defaults() -> None:
    clear_settings_cache()
    venues = load_venue_settings()
    # Offline suite patches disabled: [] so mock works (conftest). Committed
    # production default is asserted in test_committed_venues_yaml_disables_mock.
    assert venues.disabled == []
    assert venues.startup_retry_interval_sec == 60.0
    assert venues.startup_retry_backoff_multiplier == 2.0
    assert venues.startup_retry_max_interval_sec == 300.0


def test_committed_venues_yaml_disables_mock() -> None:
    """WHI-849: production config/venues.yaml disables the fixture mock adapter."""
    from spread_compare.settings import VenueSettings
    from tests._config import load_committed_config

    settings = VenueSettings.model_validate(load_committed_config("venues"))
    assert settings.disabled == ["mock"]


def test_load_impact_settings_defaults() -> None:
    clear_settings_cache()
    from spread_compare.settings import load_impact_settings

    impact = load_impact_settings()
    assert impact.max_price_impact_bps == 500


def test_load_rpc_settings_defaults() -> None:
    clear_settings_cache()
    rpc = load_rpc_settings()
    assert rpc.default_rps == 5
    assert rpc.window_sec == 1.0
    assert rpc.max_attempts == 3
    assert rpc.backoff_start_sec == 0.5
    assert rpc.backoff_max_sec == 8.0
    assert rpc.retry_after_floor_sec == 0.05
    assert rpc.gas_price_cache_ttl_sec == 15.0
    base = rpc.budget_for("BASE_RPC_URL")
    assert base.rps == 5
    assert base.max_attempts == 3
    # Unknown env falls back to defaults (no chains entry).
    other = rpc.budget_for("UNKNOWN_RPC_URL")
    assert other.rps == rpc.default_rps


def test_rpc_settings_rejects_unknown_chain_key() -> None:
    import pytest
    from pydantic import ValidationError

    from spread_compare.settings import RpcSettings

    with pytest.raises(ValidationError, match="unknown rpc env"):
        RpcSettings(
            default_rps=5,
            window_sec=1.0,
            max_attempts=3,
            backoff_start_sec=0.5,
            backoff_max_sec=8.0,
            retry_after_floor_sec=0.05,
            gas_price_cache_ttl_sec=15.0,
            chains={"BSE_RPC_URL": {"rps": 1}},
        )
