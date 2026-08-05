"""WS connect failure must not block app boot (WHI-847 / WHI-840)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from spread_compare.mids import MidService
from spread_compare.settings import clear_settings_cache, load_mid_settings, load_ws_settings
from spread_compare.ws_bootstrap import start_ws_ingest, stop_ws_ingest
from spread_compare.ws_feeds import WsFeedManager


@pytest.mark.asyncio
async def test_ws_start_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_cache()
    settings = load_ws_settings().model_copy(update={"enabled": True})
    mid = MidService(load_mid_settings())

    async def boom(self: WsFeedManager, **_kwargs: object) -> None:
        raise RuntimeError("simulated connect failure")

    monkeypatch.setattr(WsFeedManager, "start", boom)
    manager, poller = await start_ws_ingest(mid, settings=settings)
    # Outer start failure → no manager; must not raise / block boot.
    assert manager is None
    await stop_ws_ingest(manager, poller)
    await mid.aclose()


@pytest.mark.asyncio
async def test_ws_stream_start_failure_degrades_stream_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_cache()
    settings = load_ws_settings().model_copy(update={"enabled": True})
    manager = WsFeedManager(settings)

    async def fail_spot(self: WsFeedManager) -> None:
        raise ConnectionError("spot down")

    async def ok_fut(self: WsFeedManager) -> None:
        # Register a fake socket count path
        self._sockets.append(AsyncMock(is_connected=True, stream_id="binance_futures"))

    monkeypatch.setattr(WsFeedManager, "_start_binance_spot", fail_spot)
    monkeypatch.setattr(WsFeedManager, "_start_binance_futures", ok_fut)
    # Disable other streams via empty symbol lists
    await manager.start(
        binance_spot_symbols=["BTCUSDT"],
        binance_futures_symbols=["BTCUSDT"],
    )
    # Spot failed; futures path ran — manager still started
    assert manager.socket_count >= 1
    await manager.stop()
