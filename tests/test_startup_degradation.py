"""Survive adapter startup failures (WHI-840).

Seams under test:
- registry.startup_all (transient vs fatal split, _INITIALIZED)
- registry retry loop (recover / backoff, no tight loop)
- registry set_disabled_venues (list_venues / get)
- FastAPI lifespan + /health degradation payload
- quote_with_timeout not_initialized guard
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spread_compare.adapters.base import (
    AdapterConfigError,
    AdapterFetchError,
    AdapterTimeoutError,
)
from spread_compare.adapters.registry import (
    _INITIALIZED,
    _REGISTRY,
    aclose_all,
    clear_disabled_venues,
    expected_adapter_count,
    get,
    initialized_count,
    is_available,
    is_degradable_startup_error,
    is_degraded,
    list_venues,
    retry_uninitialized,
    run_startup_retry_loop,
    set_disabled_venues,
    startup_all,
    unavailable_venues,
)
from spread_compare.aggregator import QuoteAggregator, quote_with_timeout
from spread_compare.api.app import create_app
from spread_compare.settings import (
    AggregatorSettings,
    VenueSettings,
    clear_settings_cache,
    load_venue_settings,
)
from tests.adapter_fakes import DEFAULT_TEST_MID, FixedMid, StubAdapter


def test_degradable_startup_error_classification() -> None:
    assert is_degradable_startup_error(AdapterFetchError("upstream"))
    assert is_degradable_startup_error(AdapterTimeoutError("slow"))
    assert not is_degradable_startup_error(AdapterConfigError("bad label"))
    assert not is_degradable_startup_error(RuntimeError("missing ETH_RPC_URL"))
    assert not is_degradable_startup_error(ValueError("bad"))


@pytest.mark.asyncio
async def test_startup_all_degrades_transient_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AdapterFetchError at startup degrades that venue; others still initialize."""

    class BoomAdapter(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            raise AdapterFetchError("orderBookDetails timeout")

    class OkAdapter(StubAdapter):
        venue: str = "binance"

        async def startup(self) -> None:
            self._started = True

    boom = BoomAdapter()
    ok = OkAdapter()
    monkeypatch.setitem(_REGISTRY, "lighter", boom)
    monkeypatch.setitem(_REGISTRY, "binance", ok)
    _INITIALIZED.discard("lighter")
    _INITIALIZED.discard("binance")

    with caplog.at_level(logging.INFO, logger="spread_compare.adapters.registry"):
        report = await startup_all(slugs=["lighter", "binance"])

    assert "lighter" in report.degraded
    assert isinstance(report.degraded["lighter"], AdapterFetchError)
    assert "binance" in report.succeeded
    assert "lighter" not in _INITIALIZED
    assert "binance" in _INITIALIZED
    assert is_degraded()
    assert "lighter" in unavailable_venues()
    assert any("adapter startup summary" in r.message for r in caplog.records)

    await aclose_all()


@pytest.mark.asyncio
async def test_startup_all_fatal_still_refuses_boot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RuntimeError (e.g. missing ETH_RPC_URL) still fails the process."""

    class FatalAdapter(StubAdapter):
        venue: str = "uniswap_eth"

        async def startup(self) -> None:
            raise RuntimeError(
                "missing required env var ETH_RPC_URL (set it in .env — see .env.example)"
            )

    boom = FatalAdapter()
    monkeypatch.setitem(_REGISTRY, "uniswap_eth", boom)
    _INITIALIZED.discard("uniswap_eth")

    with pytest.raises(ExceptionGroup) as exc_info:
        await startup_all(slugs=["uniswap_eth"])

    assert any(
        isinstance(e, RuntimeError) and "ETH_RPC_URL" in str(e)
        for e in exc_info.value.exceptions
    )
    assert "uniswap_eth" not in _INITIALIZED

    await aclose_all()


@pytest.mark.asyncio
async def test_startup_all_adapter_config_error_is_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Jupiter wrong-label style config errors must not silently degrade."""

    class ConfigBoom(StubAdapter):
        venue: str = "humidifi"

        async def startup(self) -> None:
            raise AdapterConfigError("humidifi: Jupiter label validation failed")

    monkeypatch.setitem(_REGISTRY, "humidifi", ConfigBoom())
    _INITIALIZED.discard("humidifi")

    with pytest.raises(ExceptionGroup) as exc_info:
        await startup_all(slugs=["humidifi"])

    assert any(isinstance(e, AdapterConfigError) for e in exc_info.value.exceptions)
    assert "humidifi" not in _INITIALIZED
    await aclose_all()


@pytest.mark.asyncio
async def test_not_initialized_quote_error_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed venue yields not_initialized — never unsupported_asset."""

    class BoomAdapter(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            raise AdapterFetchError("down")

        async def get_quote(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("get_quote must not be called when not initialized")

    monkeypatch.setitem(_REGISTRY, "lighter", BoomAdapter())
    _INITIALIZED.discard("lighter")
    await startup_all(slugs=["lighter"])
    assert not is_available("lighter")

    quote = await quote_with_timeout(
        get("lighter"),
        asset="BTC",
        side="buy",
        notional_usd=Decimal("10000"),
        mid=DEFAULT_TEST_MID,
        instrument_type="perp",
        timeout=1.0,
    )
    assert quote.status == "error"
    assert quote.error_code == "not_initialized"
    assert quote.error_code != "unsupported_asset"

    await aclose_all()


@pytest.mark.asyncio
async def test_disabled_venue_absent_from_list_and_get() -> None:
    assert "binance" in list_venues()
    set_disabled_venues(["binance"])
    try:
        assert "binance" not in list_venues()
        with pytest.raises(KeyError, match="disabled"):
            get("binance")
    finally:
        clear_disabled_venues()
    assert "binance" in list_venues()


def test_disabled_venue_absent_from_get_venues_and_not_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    class TrackAdapter(StubAdapter):
        venue: str = "binance"

        async def startup(self) -> None:
            started.append(self.venue)
            self._started = True

    monkeypatch.setitem(_REGISTRY, "binance", TrackAdapter())
    # Force venue settings to disable binance for this app lifespan.
    clear_settings_cache()
    monkeypatch.setattr(
        "spread_compare.api.app.load_venue_settings",
        lambda: VenueSettings(
            disabled=["binance"],
            startup_retry_interval_sec=0,  # no background retry in this test
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        ),
    )

    try:
        with TestClient(create_app()) as client:
            venues = client.get("/venues").json()
            slugs = {row["slug"] for row in venues}
            assert "binance" not in slugs
            # Health should not expect a disabled venue.
            health = client.get("/health").json()
            assert "binance" not in health["unavailable_venues"]
            assert health["adapters_expected"] == expected_adapter_count()

        # TrackAdapter.startup must never have run (disabled before startup_all).
        assert "binance" not in started
    finally:
        clear_disabled_venues()
        clear_settings_cache()


def test_health_reports_degradation_with_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BoomAdapter(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            raise AdapterFetchError("orderBookDetails unavailable")

    monkeypatch.setitem(_REGISTRY, "lighter", BoomAdapter())
    clear_settings_cache()
    monkeypatch.setattr(
        "spread_compare.api.app.load_venue_settings",
        lambda: VenueSettings(
            disabled=[],
            startup_retry_interval_sec=0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        ),
    )

    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert body["degraded"] is True
        assert "lighter" in body["unavailable_venues"]
        assert body["adapters_initialized"] < body["adapters_expected"]
        # WHI-823: failed venue never counted as healthy.
        assert body["adapters_initialized"] == initialized_count()
        assert "lighter" not in _INITIALIZED

    clear_settings_cache()


def test_app_refuses_boot_on_fatal_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FatalAdapter(StubAdapter):
        venue: str = "uniswap_eth"

        async def startup(self) -> None:
            raise RuntimeError(
                "missing required env var ETH_RPC_URL (set it in .env — see .env.example)"
            )

    monkeypatch.setitem(_REGISTRY, "uniswap_eth", FatalAdapter())
    clear_settings_cache()
    monkeypatch.setattr(
        "spread_compare.api.app.load_venue_settings",
        lambda: VenueSettings(
            disabled=[],
            startup_retry_interval_sec=0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        ),
    )

    with pytest.raises(ExceptionGroup) as exc_info:
        with TestClient(create_app()):
            pass

    assert any("ETH_RPC_URL" in str(e) for e in exc_info.value.exceptions)
    clear_settings_cache()


@pytest.mark.asyncio
async def test_background_retry_recovers_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A venue that fails once then recovers rejoins without process restart."""
    attempts = {"n": 0}

    class FlakyAdapter(StubAdapter):
        venue: str = "apex"

        async def startup(self) -> None:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise AdapterFetchError("apex symbols down")
            self._started = True

    monkeypatch.setitem(_REGISTRY, "apex", FlakyAdapter())
    _INITIALIZED.discard("apex")

    report = await startup_all(slugs=["apex"])
    assert "apex" in report.degraded
    assert "apex" not in _INITIALIZED

    # Manual retries (same path as the background loop).
    assert await retry_uninitialized() == []
    recovered = await retry_uninitialized()
    assert recovered == ["apex"]
    assert "apex" in _INITIALIZED
    assert is_available("apex")

    await aclose_all()


@pytest.mark.asyncio
async def test_retry_loop_backoff_not_tight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permanently failing venue sleeps with growing interval — no tight loop."""
    sleeps: list[float] = []
    stop = asyncio.Event()
    attempts = {"n": 0}

    class AlwaysDown(StubAdapter):
        venue: str = "apex"

        async def startup(self) -> None:
            attempts["n"] += 1
            raise AdapterFetchError("still down")

    monkeypatch.setitem(_REGISTRY, "apex", AlwaysDown())
    _INITIALIZED.discard("apex")
    await startup_all(slugs=["apex"])

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            stop.set()

    await run_startup_retry_loop(
        interval_sec=10.0,
        backoff_multiplier=2.0,
        max_interval_sec=100.0,
        stop_event=stop,
        sleep=fake_sleep,
    )

    assert sleeps == [10.0, 20.0, 40.0]
    assert attempts["n"] >= 3  # initial startup + retries
    # Never zero / near-zero sleep (no tight loop).
    assert all(s >= 10.0 for s in sleeps)

    await aclose_all()


@pytest.mark.asyncio
async def test_retry_loop_disabled_when_interval_zero() -> None:
    stop = asyncio.Event()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    await run_startup_retry_loop(
        interval_sec=0,
        backoff_multiplier=2.0,
        max_interval_sec=300.0,
        stop_event=stop,
        sleep=fake_sleep,
    )
    assert sleeps == []


def test_load_venue_settings_defaults() -> None:
    """Retry/backoff defaults under the offline suite (mock re-enabled in conftest).

    Production ``disabled: [mock]`` is covered by
    ``test_committed_venues_yaml_disables_mock`` / ``test_get_venues_omits_mock_…``.
    """
    clear_settings_cache()
    settings = load_venue_settings()
    assert settings.disabled == []
    assert settings.startup_retry_interval_sec == 60.0
    assert settings.startup_retry_backoff_multiplier == 2.0
    assert settings.startup_retry_max_interval_sec == 300.0


def test_venue_settings_rejects_max_below_interval() -> None:
    with pytest.raises(Exception, match="startup_retry_max_interval_sec"):
        VenueSettings(
            disabled=[],
            startup_retry_interval_sec=60.0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=30.0,
        )


@pytest.mark.asyncio
async def test_quotes_include_other_venues_when_one_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /quotes path: degraded lighter still leaves mock/binance rows."""

    class BoomAdapter(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            raise AdapterFetchError("down")

    monkeypatch.setitem(_REGISTRY, "lighter", BoomAdapter())
    clear_settings_cache()
    monkeypatch.setattr(
        "spread_compare.api.app.load_venue_settings",
        lambda: VenueSettings(
            disabled=[],
            startup_retry_interval_sec=0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        ),
    )

    # Mid resolution: inject fixed mid on the app after lifespan.
    with TestClient(create_app()) as client:
        assert client.get("/health").json()["degraded"] is True
        # Patch aggregator mid service for offline quotes.
        app = client.app
        fixed = FixedMid()
        app.state.mid_service = fixed  # type: ignore[attr-defined]
        app.state.aggregator = QuoteAggregator(  # type: ignore[attr-defined]
            fixed,
            aggregator_settings=AggregatorSettings(
                venue_timeout_sec=3.0,
                venue_timeout_by_class={},
                response_cache_ttl_sec=0,
            ),
        )

        resp = client.get(
            "/quotes",
            params={
                "asset": "BTC",
                "notional": "10000",
                "venues": "mock,lighter",
            },
        )
        assert resp.status_code == 200
        pairs = {p["venue"]: p for p in resp.json()["pairs"]}
        assert "mock" in pairs
        assert "lighter" in pairs
        # lighter legs are not_initialized, not unsupported_asset.
        buy = pairs["lighter"]["buy"]
        assert buy is not None
        assert buy["status"] == "error"
        assert buy["error_code"] == "not_initialized"

    clear_settings_cache()


def test_is_available_before_startup_completed() -> None:
    """Unit tests that never call startup_all still get quotes (no false guard)."""
    import spread_compare.adapters.registry as reg

    reg._STARTUP_COMPLETED = False
    _INITIALIZED.discard("mock")
    assert is_available("mock") is True


def test_unknown_disabled_slug_fails_fast() -> None:
    with pytest.raises(ValueError, match="unknown venue slug"):
        set_disabled_venues(["binanace"])
    with pytest.raises(Exception, match="unknown venue slug"):
        VenueSettings(
            disabled=["bybitt"],
            startup_retry_interval_sec=0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        )


@pytest.mark.asyncio
async def test_simulate_failed_venue_is_not_initialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate must not collapse failed startup into not_supported (WHI-840)."""
    from spread_compare.simulator import TradeSimulator

    class BoomAdapter(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            raise AdapterFetchError("down")

        def supported_assets(
            self, *, instrument_type: object | None = None
        ) -> list[str]:
            return []  # empty warm-up cache shape

    monkeypatch.setitem(_REGISTRY, "lighter", BoomAdapter())
    _INITIALIZED.discard("lighter")
    await startup_all(slugs=["lighter"])
    assert not is_available("lighter")

    sim = TradeSimulator(
        FixedMid(),
        aggregator_settings=AggregatorSettings(
            venue_timeout_sec=3.0,
            venue_timeout_by_class={},
            response_cache_ttl_sec=0,
        ),
    )
    package = await sim.simulate(
        "USDC",
        "BTC",
        Decimal("10000"),
        venues=["lighter"],
    )
    assert len(package.rows) == 1
    row = package.rows[0]
    assert row.error_code == "not_initialized"
    assert row.error_code != "not_supported"
    assert row.status == "error"

    await aclose_all()


# --- WHI-858: missing optional HTTP transport extra must degrade, not refuse boot ---


def test_http_client_import_error_becomes_adapter_fetch_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SOCKS/missing-extra ImportError at client construction is transport, not config."""

    def boom(**kwargs: object) -> object:
        raise ImportError(
            "Using SOCKS proxy, but the 'socksio' package is not installed. "
            "Make sure to install httpx using `pip install httpx[socks]`."
        )

    monkeypatch.setattr("spread_compare.adapters.base.httpx.AsyncClient", boom)

    class NamedAdapter(StubAdapter):
        venue: str = "binance"

    adapter = NamedAdapter()
    with pytest.raises(AdapterFetchError) as exc_info:
        _ = adapter.http

    msg = str(exc_info.value)
    assert "binance" in msg
    assert "socksio" in msg.lower() or "socks" in msg.lower()
    # Must chain the original ImportError for operators reading the traceback.
    assert isinstance(exc_info.value.__cause__, ImportError)


@pytest.mark.asyncio
async def test_startup_all_degrades_on_http_client_import_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter that builds its HTTP client at startup degrades; peer venues still boot."""

    def boom(**kwargs: object) -> object:
        raise ImportError(
            "Using SOCKS proxy, but the 'socksio' package is not installed."
        )

    monkeypatch.setattr("spread_compare.adapters.base.httpx.AsyncClient", boom)

    class NeedsHttp(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            _ = self.http  # construction failure must become AdapterFetchError
            self._started = True

    class OkAdapter(StubAdapter):
        venue: str = "binance"

        async def startup(self) -> None:
            self._started = True

    monkeypatch.setitem(_REGISTRY, "lighter", NeedsHttp())
    monkeypatch.setitem(_REGISTRY, "binance", OkAdapter())
    _INITIALIZED.discard("lighter")
    _INITIALIZED.discard("binance")

    with caplog.at_level(logging.ERROR, logger="spread_compare.adapters.registry"):
        report = await startup_all(slugs=["lighter", "binance"])

    assert "lighter" in report.degraded
    assert isinstance(report.degraded["lighter"], AdapterFetchError)
    assert "binance" in report.succeeded
    assert "lighter" not in _INITIALIZED
    assert "binance" in _INITIALIZED
    assert is_degraded()
    assert "lighter" in unavailable_venues()
    # Log line names the venue and the actionable cause (not only ExceptionGroup).
    lighter_logs = [
        r
        for r in caplog.records
        if "lighter" in r.getMessage() and "startup failed" in r.getMessage()
    ]
    assert lighter_logs
    assert any(
        "socksio" in r.getMessage().lower() or "socks" in r.getMessage().lower()
        for r in lighter_logs
    )

    await aclose_all()


def test_health_reports_degradation_on_http_client_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /health lists the venue in unavailable_venues when HTTP client cannot construct."""

    def boom(**kwargs: object) -> object:
        raise ImportError(
            "Using SOCKS proxy, but the 'socksio' package is not installed."
        )

    monkeypatch.setattr("spread_compare.adapters.base.httpx.AsyncClient", boom)

    class NeedsHttp(StubAdapter):
        venue: str = "lighter"

        async def startup(self) -> None:
            _ = self.http
            self._started = True

    monkeypatch.setitem(_REGISTRY, "lighter", NeedsHttp())
    clear_settings_cache()
    monkeypatch.setattr(
        "spread_compare.api.app.load_venue_settings",
        lambda: VenueSettings(
            disabled=[],
            startup_retry_interval_sec=0,
            startup_retry_backoff_multiplier=2.0,
            startup_retry_max_interval_sec=300.0,
        ),
    )

    with TestClient(create_app()) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["status"] == "ok"
        assert body["degraded"] is True
        assert "lighter" in body["unavailable_venues"]

    clear_settings_cache()
