"""WsFeedManager wiring: chunked subscribe, resync, throttle (WHI-855).

These tests sit at the manager seam — sequence rules live in test_ws_protocols;
this file proves the feed *wiring* that WHI-847's pure protocol tests missed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from spread_compare.local_book import BookHealth
from spread_compare.settings import WsSettings, clear_settings_cache, load_ws_settings
from spread_compare.ws_feeds import WsFeedManager, chunked
from spread_compare.ws_protocols import LighterSync
from spread_compare.ws_registry import WsBookRegistry


def _ws_settings(**overrides: Any) -> WsSettings:
    clear_settings_cache()
    base = load_ws_settings().model_copy(update={"enabled": True, **overrides})
    return base


# --- pure helpers -----------------------------------------------------------


def test_chunked_splits_at_size() -> None:
    assert chunked(list(range(13)), 10) == [list(range(10)), [10, 11, 12]]
    assert chunked(["a", "b"], 10) == [["a", "b"]]
    assert chunked([], 10) == []
    assert chunked(list(range(5)), 1) == [[0], [1], [2], [3], [4]]


def test_chunked_rejects_zero_size() -> None:
    with pytest.raises(ValueError, match="chunk size"):
        chunked([1, 2], 0)


# --- Bybit chunked subscribe + ack ------------------------------------------


class _FakeSock:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.is_connected = True
        self.stream_id = "fake"
        self._started = False

    def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self.is_connected = False

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_bybit_spot_subscribe_chunks_at_ten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bybit spot caps args at 10; 13 topics must be sent as 10 + 3."""
    settings = _ws_settings()
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    symbols = [f"S{i}USDT" for i in range(13)]
    manager._symbols["bybit_spot"] = symbols

    fake = _FakeSock()
    captured: dict[str, Any] = {}

    def fake_spawn(self: WsFeedManager, url: str, **kwargs: Any) -> _FakeSock:
        captured["on_open"] = kwargs["on_open"]
        captured["on_message"] = kwargs["on_message"]
        holder = kwargs.get("sock_holder")
        if holder is not None:
            holder.append(fake)
        self._sockets.append(fake)  # type: ignore[arg-type]
        self._stream_socks[kwargs["stream_id"]] = fake  # type: ignore[assignment]
        return fake  # type: ignore[return-value]

    monkeypatch.setattr(WsFeedManager, "_spawn_socket", fake_spawn)
    await manager._start_bybit_spot()
    assert captured["on_open"] is not None
    await captured["on_open"]()

    assert len(fake.sent) == 2
    assert fake.sent[0]["op"] == "subscribe"
    assert len(fake.sent[0]["args"]) == 10
    assert len(fake.sent[1]["args"]) == 3
    # Every topic is orderbook.1000.<symbol>
    all_args = fake.sent[0]["args"] + fake.sent[1]["args"]
    assert all_args[0] == "orderbook.1000.S0USDT"
    assert len(all_args) == 13


@pytest.mark.asyncio
async def test_bybit_subscribe_failure_surfaces_stream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _ws_settings()
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    manager._symbols["bybit_spot"] = ["BTCUSDT", "ETHUSDT"]

    fake = _FakeSock()
    captured: dict[str, Any] = {}

    def fake_spawn(self: WsFeedManager, url: str, **kwargs: Any) -> _FakeSock:
        captured["on_open"] = kwargs["on_open"]
        captured["on_message"] = kwargs["on_message"]
        holder = kwargs.get("sock_holder")
        if holder is not None:
            holder.append(fake)
        self._sockets.append(fake)  # type: ignore[arg-type]
        self._stream_socks[kwargs["stream_id"]] = fake  # type: ignore[assignment]
        return fake  # type: ignore[return-value]

    monkeypatch.setattr(WsFeedManager, "_spawn_socket", fake_spawn)
    await manager._start_bybit_spot()
    # on_open records the batch symbols so a failed ack only targets that batch.
    await captured["on_open"]()
    # Mark BTC healthy (simulates a prior successful chunk) then fail the batch.
    btc = manager.registry.get("bybit", "BTCUSDT", "spot")
    assert btc is not None
    btc.set_health(BookHealth.HEALTHY)
    await captured["on_message"](
        {"success": False, "ret_msg": "args size >10", "op": "subscribe"}
    )
    assert manager.stream_error("bybit_spot") == "args size >10"
    # Already-HEALTHY book must survive a failed batch that still lists it.
    assert btc.health is BookHealth.HEALTHY
    eth = manager.registry.get("bybit", "ETHUSDT", "spot")
    assert eth is not None
    # CONNECTING (never synced) books in the failed batch go DISCONNECTED.
    assert eth.health is BookHealth.DISCONNECTED
    assert eth.is_servable(max_age_sec=60.0) is False


# --- ApeX chunk + ping ------------------------------------------------------


@pytest.mark.asyncio
async def test_apex_subscribe_chunks_one_arg_and_answers_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _ws_settings()
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    manager._symbols["apex"] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    fake = _FakeSock()
    captured: dict[str, Any] = {}

    def fake_spawn(self: WsFeedManager, url: str, **kwargs: Any) -> _FakeSock:
        captured["on_open"] = kwargs["on_open"]
        captured["on_message"] = kwargs["on_message"]
        holder = kwargs.get("sock_holder")
        if holder is not None:
            holder.append(fake)
        self._sockets.append(fake)  # type: ignore[arg-type]
        self._stream_socks[kwargs["stream_id"]] = fake  # type: ignore[assignment]
        return fake  # type: ignore[return-value]

    monkeypatch.setattr(WsFeedManager, "_spawn_socket", fake_spawn)
    await manager._start_apex()
    await captured["on_open"]()
    # chunk=1 → one subscribe op per symbol
    assert len(fake.sent) == 3
    assert all(len(m["args"]) == 1 for m in fake.sent)
    assert fake.sent[0]["args"] == ["orderBook200.H.BTCUSDT"]

    fake.sent.clear()
    await captured["on_message"]({"op": "ping"})
    assert fake.sent == [{"op": "pong"}]


# --- Hyperliquid transport ping disabled ------------------------------------


@pytest.mark.asyncio
async def test_hyperliquid_disables_transport_ping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _ws_settings()
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    manager._symbols["hyperliquid"] = ["BTC"]

    captured: dict[str, Any] = {}

    def fake_spawn(self: WsFeedManager, url: str, **kwargs: Any) -> _FakeSock:
        captured.update(kwargs)
        fake = _FakeSock()
        holder = kwargs.get("sock_holder")
        if holder is not None:
            holder.append(fake)
        self._sockets.append(fake)  # type: ignore[arg-type]
        self._stream_socks[kwargs["stream_id"]] = fake  # type: ignore[assignment]
        return fake  # type: ignore[return-value]

    monkeypatch.setattr(WsFeedManager, "_spawn_socket", fake_spawn)
    await manager._start_hyperliquid()
    assert captured["ping_interval"] is None
    assert captured["app_ping_interval_sec"] == 20.0
    assert captured["app_ping_payload"] == {"method": "ping"}


# --- Binance spot resync throttle -------------------------------------------


@pytest.mark.asyncio
async def test_binance_spot_resync_throttled_per_symbol_and_weight() -> None:
    """Injected desync storm cannot exceed per-symbol interval + weight budget."""
    # weight=50, budget=100 → at most 2 successful resyncs in a 60s window
    settings = _ws_settings(
        binance_spot_min_resync_interval_sec=1.0,
        binance_spot_resync_weight=50,
        binance_spot_resync_weight_budget_per_min=100,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"lastUpdateId": 1, "bids": [["100", "1"]], "asks": [["101", "1"]]},
        )
    )
    client = httpx.AsyncClient(transport=transport)
    manager = WsFeedManager(settings, registry=WsBookRegistry(), client=client)
    book = manager.registry.get_or_create("binance", "BTCUSDT", "spot")
    from spread_compare.ws_protocols import BinanceSpotSync

    manager._spot_syncs["BTCUSDT"] = BinanceSpotSync(book)

    # First two calls consume the budget (2 * 50 = 100).
    await manager._resync_binance_spot("BTCUSDT")
    # Force interval elapsed for second call by backdating last mono.
    manager._binance_spot_last_resync_mono["BTCUSDT"] = 0.0
    await manager._resync_binance_spot("BTCUSDT")
    ok_before, _ = manager.resync_counts("binance_spot", window_sec=60.0)
    assert ok_before == 2

    # Third call must be throttled (weight budget exhausted).
    manager._binance_spot_last_resync_mono["BTCUSDT"] = 0.0
    await manager._resync_binance_spot("BTCUSDT")
    ok_after, fail_after = manager.resync_counts("binance_spot", window_sec=60.0)
    assert ok_after == 2
    assert fail_after == 0
    # Book stays RESYNCING (unservable) — not a stale servable price.
    assert book.health is BookHealth.RESYNCING
    assert book.is_servable(max_age_sec=60.0) is False
    await client.aclose()


@pytest.mark.asyncio
async def test_binance_spot_resync_interval_blocks_same_symbol() -> None:
    settings = _ws_settings(
        binance_spot_min_resync_interval_sec=60.0,
        binance_spot_resync_weight=1,
        binance_spot_resync_weight_budget_per_min=10_000,
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(
            200,
            json={"lastUpdateId": calls["n"], "bids": [["1", "1"]], "asks": [["2", "1"]]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = WsFeedManager(settings, registry=WsBookRegistry(), client=client)
    book = manager.registry.get_or_create("binance", "ETHUSDT", "spot")
    from spread_compare.ws_protocols import BinanceSpotSync

    manager._spot_syncs["ETHUSDT"] = BinanceSpotSync(book)
    await manager._resync_binance_spot("ETHUSDT")
    await manager._resync_binance_spot("ETHUSDT")  # immediate retry → throttled
    assert calls["n"] == 1
    await client.aclose()


# --- Lighter resync via resubscribe -----------------------------------------


@pytest.mark.asyncio
async def test_lighter_resync_resubscribes_without_synthetic_nonce() -> None:
    """Gap recovery re-subscribes; does not inject nonce=0 from REST."""
    settings = _ws_settings(lighter_min_resync_interval_sec=0.01)
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    book = manager.registry.get_or_create("lighter", "BTC", "perp")
    sync = LighterSync(book)
    # Establish a real nonce chain first.
    sync.on_snapshot(bids=[["100", "1"]], asks=[["101", "1"]], nonce=50)
    assert book.last_seq == 50
    # Inject gap → needs_resync
    result = sync.on_update(
        bids=[["100", "2"]], asks=[], begin_nonce=99, nonce=100
    )
    assert result.needs_resync is True
    assert book.health is BookHealth.RESYNCING

    fake = _FakeSock()
    manager._stream_socks["lighter"] = fake  # type: ignore[assignment]
    manager._lighter_last_resync_mono.clear()

    await manager._resync_lighter("0", sync)

    assert fake.sent == [{"type": "subscribe", "channel": "order_book/0"}]
    # note_resync(ok) is deferred until the server's snapshot lands.
    ok_n, fail_n = manager.resync_counts("lighter", window_sec=60.0)
    assert ok_n == 0 and fail_n == 0
    # Sequence state must NOT have been wiped to nonce=0 by a REST path.
    # Book stays RESYNCING until the server's real snapshot arrives.
    assert book.health is BookHealth.RESYNCING
    assert book.last_seq == 50  # unchanged — no synthetic nonce inject
    # Simulate server snapshot path via on_message (real nonce) → healthy + note ok
    # Drive through the public snapshot path the feed uses after resubscribe.
    sync.on_snapshot(bids=[["100", "1"]], asks=[["101", "1"]], nonce=120)
    # Manually complete pending the way on_message does after snapshot:
    if "0" in manager._lighter_resync_pending:
        manager._lighter_resync_pending.discard("0")
        manager.note_resync("lighter", ok=True)
    assert book.health is BookHealth.HEALTHY
    assert book.last_seq == 120
    ok_n2, _ = manager.resync_counts("lighter", window_sec=60.0)
    assert ok_n2 == 1
    # Subsequent delta chains from 120
    ok = sync.on_update(bids=[], asks=[], begin_nonce=120, nonce=121)
    assert ok.accepted is True
    assert book.is_servable(max_age_sec=60.0) is True


@pytest.mark.asyncio
async def test_lighter_resync_throttled() -> None:
    settings = _ws_settings(lighter_min_resync_interval_sec=60.0)
    manager = WsFeedManager(settings, registry=WsBookRegistry())
    book = manager.registry.get_or_create("lighter", "ETH", "perp")
    sync = LighterSync(book)
    fake = _FakeSock()
    manager._stream_socks["lighter"] = fake  # type: ignore[assignment]
    manager._lighter_last_resync_mono["1"] = asyncio.get_event_loop().time()
    # Also set via time.monotonic path — force a recent stamp
    import time

    manager._lighter_last_resync_mono["1"] = time.monotonic()
    await manager._resync_lighter("1", sync)
    assert fake.sent == []  # throttled — no resubscribe


# --- Resync direct coverage (bybit / futures / apex) ------------------------


@pytest.mark.asyncio
async def test_resync_bybit_applies_snapshot() -> None:
    settings = _ws_settings()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "result": {
                        "u": 42,
                        "seq": 7,
                        "b": [["100", "1"]],
                        "a": [["101", "1"]],
                    }
                },
            )
        )
    )
    manager = WsFeedManager(settings, registry=WsBookRegistry(), client=client)
    book = manager.registry.get_or_create("bybit", "BTCUSDT", "spot")
    from spread_compare.ws_protocols import BybitSync

    sync = BybitSync(book)
    await manager._resync_bybit("spot", "BTCUSDT", sync)
    assert book.health is BookHealth.HEALTHY
    assert book.last_update_id == 42
    await client.aclose()


@pytest.mark.asyncio
async def test_resync_binance_futures_applies_snapshot() -> None:
    settings = _ws_settings()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "lastUpdateId": 9,
                    "bids": [["100", "1"]],
                    "asks": [["101", "1"]],
                },
            )
        )
    )
    manager = WsFeedManager(settings, registry=WsBookRegistry(), client=client)
    book = manager.registry.get_or_create("binance", "BTCUSDT", "perp")
    from spread_compare.ws_protocols import BinanceFuturesSync

    manager._fut_syncs["BTCUSDT"] = BinanceFuturesSync(book)
    await manager._resync_binance_futures("BTCUSDT")
    assert book.last_update_id == 9
    await client.aclose()


@pytest.mark.asyncio
async def test_resync_apex_applies_snapshot() -> None:
    settings = _ws_settings()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "data": {
                        "u": 3,
                        "b": [["100", "1"]],
                        "a": [["101", "1"]],
                    }
                },
            )
        )
    )
    manager = WsFeedManager(settings, registry=WsBookRegistry(), client=client)
    book = manager.registry.get_or_create("apex", "BTCUSDT", "perp")
    from spread_compare.ws_protocols import ApexSync

    sync = ApexSync(book)
    await manager._resync_apex("BTCUSDT", sync)
    assert book.health is BookHealth.HEALTHY
    assert book.last_update_id == 3
    await client.aclose()
