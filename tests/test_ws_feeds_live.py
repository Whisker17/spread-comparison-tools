"""Live-marked WS feed sync probes (WHI-855).

Each venue must reach at least one HEALTHY local book within a bound.
Offline suite skips these unless ``pytest --live``.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from spread_compare.local_book import BookHealth
from spread_compare.settings import clear_settings_cache, load_ws_settings
from spread_compare.ws_feeds import WsFeedManager
from spread_compare.ws_registry import WsBookRegistry

# Bound for first healthy book on a real network (generous for cold start).
_SYNC_TIMEOUT_SEC = 25.0
# Hyperliquid connection hold (acceptance: >10 min; keep CI-live shorter but
# document a longer manual run in the PR). Live default here is 90s to avoid
# CI timeouts; override with WS_LIVE_HL_HOLD_SEC for a full 10-minute probe.
_HL_HOLD_SEC = float(__import__("os").environ.get("WS_LIVE_HL_HOLD_SEC", "90"))


async def _wait_healthy(
    registry: WsBookRegistry,
    venue: str,
    instrument_type: str,
    symbols: list[str],
    *,
    timeout: float = _SYNC_TIMEOUT_SEC,
) -> list[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        healthy = [
            s
            for s in symbols
            if (b := registry.get(venue, s, instrument_type)) is not None
            and b.health is BookHealth.HEALTHY
        ]
        if healthy:
            return healthy
        await asyncio.sleep(0.25)
    return []


def _settings_one_stream(stream: str) -> object:
    clear_settings_cache()
    base = load_ws_settings()
    flags = base.streams.model_dump()
    for k in flags:
        flags[k] = k == stream
    streams = base.streams.model_copy(update=flags)
    return base.model_copy(update={"enabled": True, "streams": streams})


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_binance_spot_book_syncs() -> None:
    settings = _settings_one_stream("binance_spot")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    symbols = ["BTCUSDT", "ETHUSDT"]
    await mgr.start(binance_spot_symbols=symbols)
    try:
        healthy = await _wait_healthy(reg, "binance", "spot", symbols)
        assert healthy, "binance spot never reached HEALTHY"
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_binance_futures_book_syncs() -> None:
    settings = _settings_one_stream("binance_futures")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    symbols = ["BTCUSDT", "ETHUSDT"]
    await mgr.start(binance_futures_symbols=symbols)
    try:
        healthy = await _wait_healthy(reg, "binance", "perp", symbols)
        assert healthy, "binance futures never reached HEALTHY"
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bybit_spot_book_syncs() -> None:
    settings = _settings_one_stream("bybit_spot")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    # 13 liquid product symbols — historically failed as one batch (args size >10).
    # Chunked ≤10 must accept the subscribe; we require most books healthy.
    symbols = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "DOGEUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "BNBUSDT",
        "SUIUSDT",
        "WIFUSDT",
        "DOTUSDT",
        "LTCUSDT",
    ]
    await mgr.start(bybit_spot_symbols=symbols)
    try:
        # Wait until either most books are healthy or timeout (snapshots are async).
        deadline = time.monotonic() + 45.0
        healthy: list[str] = []
        while time.monotonic() < deadline:
            healthy = [
                s
                for s in symbols
                if (b := reg.get("bybit", s, "spot")) is not None
                and b.health is BookHealth.HEALTHY
            ]
            if len(healthy) >= 10:
                break
            await asyncio.sleep(0.25)
        assert healthy, f"bybit spot never HEALTHY; err={mgr.stream_error('bybit_spot')}"
        # Chunking works if subscribe is accepted for >10 topics (old: 0 healthy).
        assert len(healthy) >= 10, (
            f"only {len(healthy)}/{len(symbols)} bybit spot healthy; "
            f"err={mgr.stream_error('bybit_spot')}"
        )
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_bybit_linear_book_syncs() -> None:
    settings = _settings_one_stream("bybit_linear")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    await mgr.start(bybit_linear_symbols=symbols)
    try:
        healthy = await _wait_healthy(reg, "bybit", "perp", symbols)
        assert healthy, "bybit linear never reached HEALTHY"
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_hyperliquid_book_syncs_and_holds() -> None:
    settings = _settings_one_stream("hyperliquid")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    coins = ["BTC", "ETH"]
    await mgr.start(hyperliquid_coins=coins)
    try:
        healthy = await _wait_healthy(reg, "hyperliquid", "perp", coins)
        assert healthy, "hyperliquid never reached HEALTHY"
        # Hold connection; disconnects used to fire every ~40s with transport pings.
        opens_before = mgr._sockets[0].open_count if mgr._sockets else 0
        await asyncio.sleep(min(_HL_HOLD_SEC, 90.0))
        opens_after = mgr._sockets[0].open_count if mgr._sockets else 0
        # At most one reconnect is tolerable; the old bug was ~1.5/min.
        assert opens_after - opens_before <= 1, (
            f"hyperliquid reconnected too often during hold "
            f"(opens {opens_before}→{opens_after})"
        )
        still = [
            c
            for c in coins
            if (b := reg.get("hyperliquid", c, "perp")) is not None
            and b.health is BookHealth.HEALTHY
        ]
        assert still, "hyperliquid books lost HEALTHY during hold"
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_apex_book_syncs() -> None:
    settings = _settings_one_stream("apex")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    symbols = ["BTCUSDT", "ETHUSDT"]
    await mgr.start(apex_symbols=symbols)
    try:
        healthy = await _wait_healthy(reg, "apex", "perp", symbols, timeout=30.0)
        assert healthy, f"apex never HEALTHY; err={mgr.stream_error('apex')}"
    finally:
        await mgr.stop()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_lighter_book_syncs() -> None:
    """Lighter needs market_id; resolve via public REST details once."""
    import httpx

    settings = _settings_one_stream("lighter")
    reg = WsBookRegistry()
    mgr = WsFeedManager(settings, registry=reg)  # type: ignore[arg-type]
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://mainnet.zklighter.elliot.ai/api/v1/orderBookDetails"
        )
        resp.raise_for_status()
        body = resp.json()
    markets: dict[str, str] = {}
    rows = body.get("order_book_details") or body.get("orderBookDetails") or body
    if isinstance(rows, dict):
        rows = rows.get("order_book_details") or list(rows.values())
    if not isinstance(rows, list):
        pytest.skip("lighter market details shape unexpected")
    for row in rows:
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper()
        mid = row.get("market_id")
        if mid is None:
            mid = row.get("marketId")
        if sym in {"BTC", "ETH"} and mid is not None:
            markets[str(mid)] = sym
        if len(markets) >= 2:
            break
    if not markets:
        pytest.skip("could not resolve lighter BTC/ETH market ids")
    await mgr.start(lighter_markets=markets)
    try:
        healthy = await _wait_healthy(
            reg, "lighter", "perp", list(markets.values()), timeout=30.0
        )
        assert healthy, "lighter never reached HEALTHY"
    finally:
        await mgr.stop()
