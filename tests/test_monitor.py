"""Real-time engine monitoring (WHI-819)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from spread_compare.local_book import BookHealth
from spread_compare.mids import MidService
from spread_compare.models import Quote
from spread_compare.monitor import (
    EngineMonitor,
    EngineSnapshot,
    StreamHealthView,
    SweepHealthView,
    WebhookAlerter,
    collect_engine_snapshot,
    evaluate_alerts,
)
from spread_compare.poller import PullQuotePoller
from spread_compare.quote_store import QuoteStore, QuoteStoreKey
from spread_compare.settings import (
    MonitorSettings,
    clear_settings_cache,
    load_monitor_settings,
)
from spread_compare.upstream_events import RollingEventCounter
from spread_compare.ws_feeds import WsFeedManager
from spread_compare.ws_registry import WsBookRegistry


def _monitor_settings(**overrides: Any) -> MonitorSettings:
    base = load_monitor_settings().model_dump()
    base.update(overrides)
    return MonitorSettings.model_validate(base)


def test_load_monitor_settings_defaults() -> None:
    clear_settings_cache()
    cfg = load_monitor_settings()
    assert cfg.enabled is True
    assert cfg.probe_asset == "BTC"
    assert cfg.ws_disconnected_alert_sec == 30.0
    assert cfg.sweep_stale_multiplier == 2.5
    assert cfg.rate_limit_count_threshold == 10


def test_monitor_settings_reject_bad_multiplier() -> None:
    with pytest.raises(ValidationError):
        _monitor_settings(sweep_stale_multiplier=0.5)


def test_health_includes_engine_and_stays_200_when_degraded() -> None:
    """AC: health exposes engine signals; still 200 when degraded."""
    from spread_compare.api.app import create_app

    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "engine" in body
        engine = body["engine"]
        assert engine is not None
        assert "streams" in engine
        assert "sweeps" in engine
        assert "mid_age_sec" in engine or engine["mid_age_sec"] is None
        assert "data_ok" in engine
        assert isinstance(engine["alerts"], list)


def test_health_stays_200_while_books_unsynced_alert_open() -> None:
    """AC: GET /health is 200 even when engine.alerts includes books_unsynced."""
    from spread_compare.api.app import create_app
    from spread_compare.monitor import _OpenAlert

    app = create_app()
    with TestClient(app) as client:
        mon = getattr(app.state, "engine_monitor", None)
        if mon is not None:
            snap = mon.snapshot(force=True)
            snap.alerts = [
                _OpenAlert(
                    code="books_unsynced",
                    severity="critical",
                    target="bybit_spot",
                    message="never synced since connect: 0/13",
                    value=0.0,
                    threshold=13.0,
                )
            ]
            snap.data_ok = False
            snap.data_failures = ["stream 'bybit_spot' healthy books 0/13 < min 1"]
            mon.last_snapshot = snap
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        codes = {a["code"] for a in body["engine"]["alerts"]}
        assert "books_unsynced" in codes


def test_ws_disconnected_raises_alert() -> None:
    """AC: killing one venue's WebSocket raises ws_disconnected within SLO."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_disconnected_alert_sec=30.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
    )
    manager = WsFeedManager()
    # Dropped 45s ago (same path as _on_stream_closed / never-connected spawn).
    manager.mark_stream_connected("binance_spot", connected=False)
    manager._stream_disconnected_since["binance_spot"] = 100.0  # noqa: SLF001
    now = 145.0
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=WsBookRegistry(),
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    alerts = evaluate_alerts(snap, cfg)
    codes = {a.code for a in alerts}
    assert "ws_disconnected" in codes
    disc = next(a for a in alerts if a.code == "ws_disconnected")
    assert disc.target == "binance_spot"
    assert disc.severity == "critical"
    assert disc.value == pytest.approx(45.0)
    assert disc.threshold == 30.0


def test_sweep_stale_raises_alert() -> None:
    """AC: stopping the sweep raises sweep_stale within stated SLO."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        sweep_stale_multiplier=2.5,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
    )
    # jupiter interval 15s → threshold 37.5s; age 100s is stale.
    snap = EngineSnapshot(
        now_mono=1000.0,
        uptime_sec=500.0,
        in_startup_grace=False,
        mid_age_sec=1.0,
        mid_probe_asset="BTC",
        sweeps=[
            SweepHealthView(
                group="jupiter",
                interval_sec=15.0,
                age_sec=100.0,
                sweep_count=3,
                stale=True,
            )
        ],
        streams=[],
        rate_limits={"jupiter": 0, "kyber": 0, "rpc": 0},
        fresh_store_quotes=1,
        healthy_books=0,
        data_ok=True,
    )
    alerts = evaluate_alerts(snap, cfg)
    assert any(a.code == "sweep_stale" and a.target == "jupiter" for a in alerts)


def test_book_desync_and_failed_resync_are_distinct() -> None:
    """AC: forced book desync / repeated-resync raises a distinct alert."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_resync_count_threshold=5,
        ws_failed_resync_threshold=2,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
    )
    snap = EngineSnapshot(
        now_mono=100.0,
        uptime_sec=100.0,
        in_startup_grace=False,
        mid_age_sec=1.0,
        mid_probe_asset="BTC",
        sweeps=[],
        streams=[
            StreamHealthView(
                stream_id="bybit_linear",
                connected=True,
                books_total=2,
                books_healthy=2,
                max_book_age_sec=0.5,
                resync_ok_window=4,
                resync_fail_window=2,
            )
        ],
        rate_limits={"jupiter": 0, "kyber": 0, "rpc": 0},
        fresh_store_quotes=1,
        healthy_books=2,
        data_ok=True,
    )
    alerts = evaluate_alerts(snap, cfg)
    codes = {a.code for a in alerts}
    assert "book_desync" in codes  # 4+2 = 6 >= 5
    assert "book_resync_failed" in codes  # 2 >= 2
    desync = next(a for a in alerts if a.code == "book_desync")
    failed = next(a for a in alerts if a.code == "book_resync_failed")
    assert desync.target == "bybit_linear"
    assert failed.target == "bybit_linear"
    assert desync.code != failed.code


def test_data_probe_fails_when_only_stale_rows() -> None:
    """AC: process up but serving only stale rows fails GET /health/data."""
    from spread_compare.models import FeeBreakdown

    cfg = _monitor_settings(
        startup_grace_sec=0.0,
        mid_max_age_sec=5.0,
        probe_min_fresh_store_quotes=1,
        probe_min_healthy_books=0,  # isolate store path
        probe_max_quote_age_sec=10.0,
        probe_asset="BTC",
    )
    store = QuoteStore(clock=lambda: 1000.0)
    # Old observation — past probe_max_quote_age_sec.
    key = QuoteStoreKey(
        venue="humidifi",
        asset="BTC",
        instrument_type="spot",
        notional_usd=Decimal("1000"),
        side="buy",
    )
    now = datetime.now(tz=UTC)
    quote = Quote(
        venue="humidifi",
        asset="BTC",
        instrument_type="spot",
        side="buy",
        notional_usd=Decimal("1000"),
        status="ok",
        mid=Decimal("100"),
        mid_source="binance_usdm_index",
        mid_timestamp=now,
        effective_price=Decimal("100.1"),
        spread_bps=Decimal("10"),
        total_cost_bps=Decimal("15"),
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            explicit_fee_bps=Decimal("5"),
            gas_bps=Decimal("0"),
        ),
        qty_base=Decimal("10"),
        qty_method="base_from_mid",
        timestamp=now,
        snapshot_id="snap-1",
    )
    store.put(key, quote, group="jupiter", success=True)
    # Force observed_mono to be stale by rewriting entry.
    entry = store.get(key)
    assert entry is not None
    entry.observed_mono = 1000.0 - 60.0  # 60s old > 10s

    from spread_compare.settings import load_poller_settings, load_ws_settings

    # Offline conftest disables poller; re-enable so store freshness is gated.
    poller_cfg = load_poller_settings().model_copy(update={"enabled": True})
    snap = collect_engine_snapshot(
        settings=cfg,
        quote_store=store,
        registry=WsBookRegistry(),
        rate_limits=RollingEventCounter(clock=lambda: 1000.0),
        poller_settings=poller_cfg,
        ws_settings=load_ws_settings().model_copy(update={"enabled": False}),
        started_mono=0.0,
        clock=lambda: 1000.0,
        mid_service=None,
    )
    assert snap.data_ok is False
    assert any("fresh store quotes" in f for f in snap.data_failures)
    assert any(a.code == "data_stale" for a in snap.alerts)


@pytest.mark.asyncio
async def test_health_data_endpoint_returns_503_when_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP-level: /health stays 200; /health/data is 503 on stale."""
    from spread_compare.api.app import create_app

    # Force zero grace and strict mid so cold app fails data probe.
    clear_settings_cache()
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "")

    # Patch monitor settings loader to use grace=0 and no WS book requirement
    # that would flake offline; keep mid required so probe fails.
    strict = _monitor_settings(
        startup_grace_sec=0.0,
        probe_min_healthy_books=0,
        probe_min_fresh_store_quotes=1,
        mid_max_age_sec=1.0,
    )

    original = EngineMonitor.snapshot

    def forced_stale(self: EngineMonitor, *, force: bool = True) -> Any:
        snap = original(self, force=force)
        # Re-evaluate with strict settings / no grace.
        snap.in_startup_grace = False
        snap.mid_age_sec = 999.0
        snap.fresh_store_quotes = 0
        snap.data_failures = ["mid age 999.0s > 1.0s for BTC"]
        snap.data_ok = False
        snap.alerts = evaluate_alerts(snap, strict)
        return snap

    monkeypatch.setattr(EngineMonitor, "snapshot", forced_stale)

    with TestClient(create_app()) as client:
        live = client.get("/health")
        assert live.status_code == 200
        assert live.json()["status"] == "ok"

        data = client.get("/health/data")
        assert data.status_code == 503
        body = data.json()
        assert body["data_ok"] is False
        assert body["data_failures"]


def test_sustained_rate_limits_raise_alert() -> None:
    """AC: sustained Jupiter/Kyber/RPC 429s raise rate_limited alert."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        rate_limit_window_sec=60.0,
        rate_limit_count_threshold=10,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
    )
    clock = {"t": 0.0}
    counter = RollingEventCounter(clock=lambda: clock["t"])
    for i in range(12):
        clock["t"] = float(i)
        counter.record("jupiter")
        counter.record("kyber")
        counter.record("rpc")
    clock["t"] = 30.0
    counts = counter.counts({"jupiter", "kyber", "rpc"}, window_sec=60.0)
    assert counts["jupiter"] == 12

    snap = EngineSnapshot(
        now_mono=30.0,
        uptime_sec=30.0,
        in_startup_grace=False,
        mid_age_sec=1.0,
        mid_probe_asset="BTC",
        sweeps=[],
        streams=[],
        rate_limits=counts,
        fresh_store_quotes=1,
        healthy_books=0,
        data_ok=True,
    )
    alerts = evaluate_alerts(snap, cfg)
    targets = {a.target for a in alerts if a.code == "rate_limited"}
    assert targets == {"jupiter", "kyber", "rpc"}


@pytest.mark.asyncio
async def test_webhook_alerter_delivers_payload() -> None:
    """AC: alert channel fires end-to-end (mock webhook receives payload)."""
    from httpx import AsyncClient, MockTransport, Request, Response

    received: list[dict[str, Any]] = []

    def handler(request: Request) -> Response:
        import json

        received.append(json.loads(request.content.decode()))
        return Response(status_code=204)

    transport = MockTransport(handler)
    client = AsyncClient(transport=transport)
    cfg = _monitor_settings(alert_cooldown_sec=0)
    alerter = WebhookAlerter(
        webhook_url="https://hooks.example.test/alert",
        settings=cfg,
        client=client,
        clock=lambda: 0.0,
    )
    from spread_compare.monitor import _OpenAlert

    payloads = await alerter.process(
        [
            _OpenAlert(
                code="ws_disconnected",
                severity="critical",
                target="binance_spot",
                message="stream down",
                value=40.0,
                threshold=30.0,
            )
        ]
    )
    assert len(payloads) == 1
    assert len(received) == 1
    assert received[0]["status"] == "firing"
    assert received[0]["code"] == "ws_disconnected"
    assert "content" in received[0]
    await alerter.aclose()


@pytest.mark.asyncio
async def test_webhook_alerter_resolves_when_cleared() -> None:
    from httpx import AsyncClient, MockTransport, Request, Response

    received: list[dict[str, Any]] = []

    def handler(request: Request) -> Response:
        import json

        received.append(json.loads(request.content.decode()))
        return Response(status_code=204)

    client = AsyncClient(transport=MockTransport(handler))
    t = {"now": 0.0}
    alerter = WebhookAlerter(
        webhook_url="https://hooks.example.test/alert",
        settings=_monitor_settings(alert_cooldown_sec=0),
        client=client,
        clock=lambda: t["now"],
    )
    from spread_compare.monitor import _OpenAlert

    alert = _OpenAlert(
        code="sweep_stale",
        severity="critical",
        target="jupiter",
        message="sweep lagging",
    )
    await alerter.process([alert])
    t["now"] = 1.0
    await alerter.process([])
    statuses = [p["status"] for p in received]
    assert statuses == ["firing", "resolved"]
    await alerter.aclose()


def test_collect_snapshot_includes_stream_and_sweep_ages() -> None:
    """AC: health surface exposes per-venue stream state, ages, sweep, mid."""
    cfg = _monitor_settings(startup_grace_sec=0, probe_min_healthy_books=0)
    reg = WsBookRegistry()
    book = reg.put_fixture_book(
        "binance",
        "BTCUSDT",
        "spot",
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
    )
    book.set_health(BookHealth.HEALTHY)

    import time

    manager = WsFeedManager(registry=reg)
    manager.note_resync("binance_spot", ok=True)
    manager.note_resync("binance_spot", ok=False)
    manager.mark_stream_connected("binance_spot", connected=False)
    # Backdate disconnect so age is measurable.
    manager._stream_disconnected_since["binance_spot"] = time.monotonic() - 40.0

    from spread_compare.settings import load_mid_settings

    mid = MidService(load_mid_settings())
    mid.seed_cache(
        "BTC",
        mid=Decimal("50000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )

    # Poller with a completed sweep.
    poller = PullQuotePoller(mid, settings=None)
    poller.last_sweep_completed_mono["jupiter"] = 0.0
    poller.sweep_counts["jupiter"] = 1

    clock_now = 50.0
    from spread_compare.settings import load_poller_settings, load_ws_settings

    # Offline conftest disables WS/poller process-wide; re-enable for this unit test.
    ws_cfg = load_ws_settings().model_copy(update={"enabled": True})
    poller_cfg = load_poller_settings().model_copy(update={"enabled": True})
    assert reg.book_count() == 1
    snap = collect_engine_snapshot(
        settings=cfg,
        poller=poller,
        mid_service=mid,
        ws_manager=manager,
        registry=reg,
        rate_limits=RollingEventCounter(clock=lambda: clock_now),
        ws_settings=ws_cfg,
        poller_settings=poller_cfg,
        started_mono=0.0,
        clock=lambda: clock_now,
    )
    assert snap.mid_age_sec is not None
    stream_ids = [s.stream_id for s in snap.streams]
    assert "binance_spot" in stream_ids, stream_ids
    jup = next(s for s in snap.sweeps if s.group == "jupiter")
    assert jup.age_sec == pytest.approx(50.0)
    assert jup.stale is True  # 50 > 15*2.5


def test_ws_manager_resync_counts_window() -> None:
    manager = WsFeedManager()
    for _ in range(3):
        manager.note_resync("lighter", ok=True)
    manager.note_resync("lighter", ok=False)
    ok, fail = manager.resync_counts("lighter", window_sec=60.0)
    assert ok == 3
    assert fail == 1


def test_cold_fail_stream_marks_disconnected_age() -> None:
    """A stream that never connects still ages toward ws_disconnected (WHI-819)."""
    manager = WsFeedManager()
    # Simulate _spawn_socket start path without opening a real socket.
    manager.mark_stream_connected("apex", connected=False)
    age = manager.stream_disconnected_age_sec("apex")
    assert age is not None
    assert age >= 0.0
    assert "apex" in manager.known_stream_ids()


def test_record_rate_limit_sources_hit_process_counter() -> None:
    """Adapter wiring: record_rate_limit increments the process counter."""
    from spread_compare.upstream_events import (
        default_rate_limit_counter,
        record_rate_limit,
        reset_rate_limit_counter,
    )

    reset_rate_limit_counter()
    record_rate_limit("jupiter")
    record_rate_limit("kyber")
    record_rate_limit("rpc")
    counter = default_rate_limit_counter()
    assert counter.count("jupiter", window_sec=60.0) == 1
    assert counter.count("kyber", window_sec=60.0) == 1
    assert counter.count("rpc", window_sec=60.0) == 1


def test_adapter_modules_wire_record_rate_limit_on_429() -> None:
    """Guard the three 429 call sites so a removed import fails tests."""
    import inspect

    from spread_compare.adapters import _amm_common, prop_jupiter, prop_kyberswap

    for mod, source in (
        (prop_jupiter, "jupiter"),
        (prop_kyberswap, "kyber"),
        (_amm_common, "rpc"),
    ):
        text = inspect.getsource(mod)
        assert "record_rate_limit" in text, mod.__name__
        assert f'record_rate_limit("{source}")' in text, mod.__name__


def test_mid_age_is_probe_asset_only() -> None:
    """Missing probe mid is not masked by a fresher mid for another asset."""
    from spread_compare.settings import load_mid_settings

    cfg = _monitor_settings(
        startup_grace_sec=0,
        probe_asset="BTC",
        mid_max_age_sec=5.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
    )
    mid = MidService(load_mid_settings())
    mid.seed_cache(
        "SOL",
        mid=Decimal("100"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    snap = collect_engine_snapshot(
        settings=cfg,
        mid_service=mid,
        registry=WsBookRegistry(),
        rate_limits=RollingEventCounter(clock=lambda: 10.0),
        started_mono=0.0,
        clock=lambda: 10.0,
        ws_settings=load_ws_settings_enabled(False),
        poller_settings=load_poller_settings_enabled(False),
    )
    assert snap.mid_age_sec is None
    assert any(a.code == "mid_stale" for a in snap.alerts)


def load_ws_settings_enabled(enabled: bool) -> Any:
    from spread_compare.settings import load_ws_settings

    return load_ws_settings().model_copy(update={"enabled": enabled})


def load_poller_settings_enabled(enabled: bool) -> Any:
    from spread_compare.settings import load_poller_settings

    return load_poller_settings().model_copy(update={"enabled": enabled})


# --- WHI-856: connected but books never sync ---------------------------------


class _FakeConnectedSock:
    """Minimal stand-in for ReconnectingWebSocket in monitor unit tests."""

    def __init__(self, stream_id: str, *, connected: bool = True) -> None:
        self.stream_id = stream_id
        self.is_connected = connected


def _connected_dead_stream_manager(
    stream_id: str = "bybit_spot",
    *,
    expected: int = 13,
    connected_since: float = 0.0,
    peak_healthy: int = 0,
    stream_error: str | None = None,
) -> WsFeedManager:
    """Reproduce the pre-deploy shape: connected=true, books 0/N, no age."""
    manager = WsFeedManager(registry=WsBookRegistry())
    # Configure expected subscribe set without opening a real socket.
    if stream_id == "lighter":
        manager._lighter_markets = {str(i): f"M{i}" for i in range(expected)}  # noqa: SLF001
    else:
        manager._symbols[stream_id] = [f"S{i}USDT" for i in range(expected)]  # noqa: SLF001
    # Real stream_connected() reads the socket list — no production test branch.
    manager._sockets.append(_FakeConnectedSock(stream_id))  # type: ignore[arg-type]  # noqa: SLF001
    manager.mark_stream_connected(stream_id, connected=True)
    manager._stream_connected_since[stream_id] = connected_since  # noqa: SLF001
    manager._stream_peak_healthy[stream_id] = peak_healthy  # noqa: SLF001
    if stream_error is not None:
        manager._set_stream_error(stream_id, stream_error)  # noqa: SLF001
    return manager


def test_load_monitor_settings_books_sync_grace() -> None:
    clear_settings_cache()
    cfg = load_monitor_settings()
    assert cfg.ws_books_sync_grace_sec == 60.0
    assert cfg.probe_min_healthy_books_per_stream == 1
    assert cfg.books_sync_grace_sec("apex") == 60.0
    assert cfg.books_sync_grace_sec("binance_spot") == 60.0


def test_monitor_settings_per_stream_grace_override() -> None:
    cfg = _monitor_settings(
        ws_books_sync_grace_sec=60.0,
        ws_books_sync_grace_sec_by_stream={"apex": 120.0},
    )
    assert cfg.books_sync_grace_sec("apex") == 120.0
    assert cfg.books_sync_grace_sec("bybit_spot") == 60.0


def test_monitor_settings_reject_unknown_stream_grace_key() -> None:
    with pytest.raises(ValidationError, match="unknown stream id"):
        _monitor_settings(ws_books_sync_grace_sec_by_stream={"apx": 120.0})


def test_connected_zero_books_past_grace_raises_books_unsynced() -> None:
    """AC: connected=true with zero synced books past grace pages (the escaped case)."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=30.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,  # isolate alert path
    )
    # Connected for 90s with expected 13, healthy 0 — never synced.
    manager = _connected_dead_stream_manager(
        "bybit_spot", expected=13, connected_since=10.0, peak_healthy=0
    )
    now = 100.0
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=manager.registry,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    bybit = next(s for s in snap.streams if s.stream_id == "bybit_spot")
    assert bybit.connected is True
    assert bybit.healthy is False
    assert bybit.books_expected == 13
    assert bybit.books_healthy == 0
    assert bybit.connected_age_sec == pytest.approx(90.0)
    assert bybit.peak_healthy_since_connect == 0

    alerts = evaluate_alerts(snap, cfg)
    unsynced = [a for a in alerts if a.code == "books_unsynced"]
    assert len(unsynced) == 1
    alert = unsynced[0]
    assert alert.target == "bybit_spot"
    assert alert.severity == "critical"
    assert "never synced since connect" in alert.message
    assert "0/13" in alert.message


def test_partial_books_shortfall_is_warning_not_critical() -> None:
    """Thin markets on a large set must not critical-page as zero-book failure."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=10.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,
    )
    reg = WsBookRegistry()
    book = reg.put_fixture_book(
        "apex",
        "BTCUSDT",
        "perp",
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
    )
    book.set_health(BookHealth.HEALTHY)
    manager = WsFeedManager(registry=reg)
    manager._symbols["apex"] = [f"S{i}USDT" for i in range(10)]  # noqa: SLF001
    manager._sockets.append(_FakeConnectedSock("apex"))  # type: ignore[arg-type]  # noqa: SLF001
    manager.mark_stream_connected("apex", connected=True)
    manager._stream_connected_since["apex"] = 0.0  # noqa: SLF001
    manager._stream_peak_healthy["apex"] = 1  # noqa: SLF001
    now = 50.0
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=reg,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    apex = next(s for s in snap.streams if s.stream_id == "apex")
    assert apex.books_healthy == 1
    assert apex.books_expected == 10
    assert apex.healthy is True  # partial coverage still serves
    alerts = evaluate_alerts(snap, cfg)
    partial = next(a for a in alerts if a.code == "books_unsynced")
    assert partial.severity == "warning"
    assert "partially synced" in partial.message


def test_books_unsynced_distinguishes_degraded_from_never_synced() -> None:
    """AC: alert text differs for never-synced vs was-healthy-now-degraded."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=10.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,
    )
    manager = _connected_dead_stream_manager(
        "apex", expected=5, connected_since=0.0, peak_healthy=4
    )
    now = 50.0
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=manager.registry,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    alerts = evaluate_alerts(snap, cfg)
    alert = next(a for a in alerts if a.code == "books_unsynced")
    assert "was healthy, now degraded" in alert.message
    assert "never synced" not in alert.message
    assert "peak healthy this session was 4" in alert.message


def test_books_unsynced_suppressed_inside_connect_grace() -> None:
    """Fresh connect with zero books is legitimate — no page until grace elapses."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=60.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,
    )
    manager = _connected_dead_stream_manager(
        "bybit_spot", expected=13, connected_since=90.0, peak_healthy=0
    )
    now = 100.0  # connected_age = 10s < 60s grace
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=manager.registry,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    assert not any(a.code == "books_unsynced" for a in evaluate_alerts(snap, cfg))


def test_data_probe_fails_when_one_stream_entirely_unsynced() -> None:
    """AC: per-stream floor — one dead stream fails probe even if another is healthy."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=30.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,  # process floor off; per-stream is the fix
        probe_min_healthy_books_per_stream=1,
        mid_max_age_sec=999.0,
    )
    reg = WsBookRegistry()
    # Healthy binance stream masks process-wide floors.
    healthy = reg.put_fixture_book(
        "binance",
        "BTCUSDT",
        "spot",
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
    )
    healthy.set_health(BookHealth.HEALTHY)

    manager = WsFeedManager(registry=reg)
    manager._symbols["binance_spot"] = ["BTCUSDT"]  # noqa: SLF001
    manager._symbols["bybit_spot"] = [f"S{i}USDT" for i in range(13)]  # noqa: SLF001
    manager._sockets.append(_FakeConnectedSock("binance_spot"))  # type: ignore[arg-type]  # noqa: SLF001
    manager._sockets.append(_FakeConnectedSock("bybit_spot"))  # type: ignore[arg-type]  # noqa: SLF001
    manager.mark_stream_connected("binance_spot", connected=True)
    manager.mark_stream_connected("bybit_spot", connected=True)
    # Both past grace; bybit has zero healthy books.
    manager._stream_connected_since["binance_spot"] = 0.0  # noqa: SLF001
    manager._stream_connected_since["bybit_spot"] = 0.0  # noqa: SLF001
    manager._stream_peak_healthy["binance_spot"] = 1  # noqa: SLF001

    from spread_compare.settings import load_mid_settings

    mid = MidService(load_mid_settings())
    mid.seed_cache(
        "BTC",
        mid=Decimal("50000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )

    now = 100.0
    snap = collect_engine_snapshot(
        settings=cfg,
        mid_service=mid,
        ws_manager=manager,
        registry=reg,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    assert snap.healthy_books >= 1  # process-wide would pass
    assert snap.data_ok is False
    assert any("bybit_spot" in f and "healthy books" in f for f in snap.data_failures)
    assert any(a.code == "data_stale" for a in snap.alerts)
    assert any(a.code == "books_unsynced" and a.target == "bybit_spot" for a in snap.alerts)


def test_subscribe_failed_marks_stream_unhealthy_immediately() -> None:
    """AC: rejected/partial subscribe surfaces as subscribe_failed (not silent connected)."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=999.0,  # still inside books grace
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,  # stream_error probe is independent
        mid_max_age_sec=999.0,
    )
    manager = _connected_dead_stream_manager(
        "bybit_spot",
        expected=2,
        connected_since=99.0,  # connected_age ~1s — inside books grace
        stream_error="args size >10",
    )
    now = 100.0
    snap = collect_engine_snapshot(
        settings=cfg,
        mid_service=None,
        ws_manager=manager,
        registry=manager.registry,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    bybit = next(s for s in snap.streams if s.stream_id == "bybit_spot")
    assert bybit.connected is True
    assert bybit.healthy is False
    assert bybit.stream_error == "args size >10"

    alerts = evaluate_alerts(snap, cfg)
    assert any(a.code == "subscribe_failed" and a.target == "bybit_spot" for a in alerts)
    # Immediate — does not wait for books-sync grace.
    assert not any(a.code == "books_unsynced" for a in alerts)
    # Data probe fails on stream_error even with min_healthy_books_per_stream=0.
    assert any("subscribe/stream error" in f for f in snap.data_failures)


def test_stream_error_clears_when_books_fully_recover() -> None:
    """Latched stream_error must not 503 forever after a full healthy set returns."""
    cfg = _monitor_settings(
        startup_grace_sec=0,
        ws_books_sync_grace_sec=30.0,
        probe_min_fresh_store_quotes=0,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=1,
        mid_max_age_sec=999.0,
    )
    reg = WsBookRegistry()
    book = reg.put_fixture_book(
        "bybit",
        "BTCUSDT",
        "spot",
        [(Decimal("100"), Decimal("1"))],
        [(Decimal("101"), Decimal("1"))],
    )
    book.set_health(BookHealth.HEALTHY)
    manager = WsFeedManager(registry=reg)
    manager._symbols["bybit_spot"] = ["BTCUSDT"]  # noqa: SLF001
    manager._sockets.append(_FakeConnectedSock("bybit_spot"))  # type: ignore[arg-type]  # noqa: SLF001
    manager.mark_stream_connected("bybit_spot", connected=True)
    manager._stream_connected_since["bybit_spot"] = 0.0  # noqa: SLF001
    manager._set_stream_error("bybit_spot", "transient gap")  # noqa: SLF001

    from spread_compare.settings import load_mid_settings

    mid = MidService(load_mid_settings())
    mid.seed_cache(
        "BTC",
        mid=Decimal("50000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    now = 100.0
    snap = collect_engine_snapshot(
        settings=cfg,
        mid_service=mid,
        ws_manager=manager,
        registry=reg,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    bybit = next(s for s in snap.streams if s.stream_id == "bybit_spot")
    assert bybit.books_healthy == 1
    assert bybit.books_expected == 1
    assert bybit.stream_error is None
    assert bybit.healthy is True
    assert manager.stream_error("bybit_spot") is None
    assert not any("subscribe/stream error" in f for f in snap.data_failures)
    assert not any(a.code == "subscribe_failed" for a in snap.alerts)


def test_health_surface_exposes_books_expected_and_healthy() -> None:
    """AC: books_healthy / books_expected on the health stream view."""
    cfg = _monitor_settings(
        startup_grace_sec=999,
        probe_min_healthy_books=0,
        probe_min_healthy_books_per_stream=0,
        probe_min_fresh_store_quotes=0,
    )
    manager = _connected_dead_stream_manager(
        "apex", expected=137, connected_since=0.0, peak_healthy=0
    )
    now = 10.0
    snap = collect_engine_snapshot(
        settings=cfg,
        ws_manager=manager,
        registry=manager.registry,
        rate_limits=RollingEventCounter(clock=lambda: now),
        started_mono=0.0,
        clock=lambda: now,
        ws_settings=load_ws_settings_enabled(True),
        poller_settings=load_poller_settings_enabled(False),
    )
    apex = next(s for s in snap.streams if s.stream_id == "apex")
    view = apex.model_dump()
    assert view["books_expected"] == 137
    assert view["books_healthy"] == 0
    assert "connected_age_sec" in view
    assert "peak_healthy_since_connect" in view
    assert "stream_error" in view
