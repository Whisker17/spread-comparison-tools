"""Venue WebSocket feed workers that maintain :class:`WsBookRegistry` (WHI-847 / WHI-855).

Each stream opens **one** connection and multiplexes symbol subscriptions.
Connect failure degrades that stream only (REST fallback remains available).

WHI-855 repairs:
- Chunked subscribe (Bybit spot ≤10 args; ApeX chunk=1)
- Subscribe-ack failures surface as stream errors (not silent zero-book streams)
- Hyperliquid application-level ping + disabled transport ping
- ApeX answers server ``{"op":"ping"}`` with ``{"op":"pong"}``
- Lighter gap recovery via channel resubscribe (never REST + synthetic nonce=0)
- Binance spot REST resync throttled per symbol + weight budget
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Sequence
from types import EllipsisType
from typing import Any
from urllib.parse import urlencode

import httpx

from spread_compare.local_book import BookHealth
from spread_compare.ratelimit import RateLimitWaitExceeded, RollingWindowRateLimiter
from spread_compare.settings import WsSettings, load_ws_settings
from spread_compare.ws_connection import ReconnectingWebSocket
from spread_compare.ws_protocols import (
    ApexSync,
    ApplyResult,
    BinanceFuturesSync,
    BinanceSpotSync,
    BybitSync,
    HyperliquidSync,
    LighterSync,
)
from spread_compare.ws_registry import WsBookRegistry, default_ws_registry

logger = logging.getLogger(__name__)

_BINANCE_SPOT_WS = "wss://stream.binance.com:9443/stream"
_BINANCE_FAPI_WS = "wss://fstream.binance.com/stream"
_BINANCE_SPOT_REST = "https://api.binance.com"
_BINANCE_FAPI_REST = "https://fapi.binance.com"
_BYBIT_SPOT_WS = "wss://stream.bybit.com/v5/public/spot"
_BYBIT_LINEAR_WS = "wss://stream.bybit.com/v5/public/linear"
_BYBIT_REST = "https://api.bybit.com"
_HL_WS = "wss://api.hyperliquid.xyz/ws"
_LIGHTER_WS = "wss://mainnet.zklighter.elliot.ai/stream"
_APEX_WS_BASE = "wss://quote.omni.apex.exchange/realtime_public"
_APEX_REST = "https://omni.apex.exchange"


def chunked[T](items: Sequence[T], size: int) -> list[list[T]]:
    """Split ``items`` into contiguous chunks of at most ``size`` (size ≥ 1)."""
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    if not items:
        return []
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


class WsFeedManager:
    """Owns all orderbook WS streams for the process."""

    def __init__(
        self,
        settings: WsSettings | None = None,
        *,
        registry: WsBookRegistry | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings if settings is not None else load_ws_settings()
        self._registry = registry if registry is not None else default_ws_registry()
        self._registry.set_max_book_age_sec(self._settings.max_book_age_sec)
        self._client = client
        self._owns_client = client is None
        self._sockets: list[ReconnectingWebSocket] = []
        self._stream_socks: dict[str, ReconnectingWebSocket] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._spot_syncs: dict[str, BinanceSpotSync] = {}
        self._fut_syncs: dict[str, BinanceFuturesSync] = {}
        self._bybit_syncs: dict[str, BybitSync] = {}
        self._hl_syncs: dict[str, HyperliquidSync] = {}
        self._lighter_syncs: dict[str, LighterSync] = {}
        self._apex_syncs: dict[str, ApexSync] = {}
        self._lighter_last_resync_mono: dict[str, float] = {}
        # market_id → mono when resubscribe was sent (pending server snapshot)
        self._lighter_resync_pending_mono: dict[str, float] = {}
        self._binance_spot_last_resync_mono: dict[str, float] = {}
        # Weight budget for depth?limit=1000 (shared ratelimit.py SSOT — WHI-855).
        weight = self._settings.binance_spot_resync_weight
        budget = self._settings.binance_spot_resync_weight_budget_per_min
        max_calls = max(1, budget // weight)
        self._binance_spot_weight_limiter = RollingWindowRateLimiter(
            max_requests=max_calls, window_s=60.0
        )
        # market_id → symbol for Lighter
        self._lighter_markets: dict[str, str] = {}
        self._symbols: dict[str, list[str]] = {}
        # stream_id → last subscribe / stream error (WHI-855 surface failures)
        self._stream_errors: dict[str, str] = {}
        # WHI-819: rolling resync outcomes per stream_id (monotonic timestamps).
        # Locked: asyncio tasks write; /health may read from the threadpool.
        self._diag_lock = threading.Lock()
        self._resync_ok_mono: dict[str, list[float]] = {}
        self._resync_fail_mono: dict[str, list[float]] = {}
        self._stream_disconnected_since: dict[str, float] = {}

    @property
    def registry(self) -> WsBookRegistry:
        return self._registry

    @property
    def settings(self) -> WsSettings:
        return self._settings

    @property
    def connection_count(self) -> int:
        return sum(1 for s in self._sockets if s.is_connected)

    @property
    def socket_count(self) -> int:
        """Configured sockets (one per stream), independent of asset count."""
        return len(self._sockets)

    def stream_error(self, stream_id: str) -> str | None:
        """Last subscribe/stream error for ``stream_id``, if any."""
        return self._stream_errors.get(stream_id)

    def note_resync(self, stream_id: str, *, ok: bool) -> None:
        """Record a REST resync attempt for monitor book-desync alerts (WHI-819)."""
        now = time.monotonic()
        with self._diag_lock:
            bucket = self._resync_ok_mono if ok else self._resync_fail_mono
            bucket.setdefault(stream_id, []).append(now)

    def resync_counts(
        self, stream_id: str, *, window_sec: float, now: float | None = None
    ) -> tuple[int, int]:
        """Return ``(ok_count, fail_count)`` for ``stream_id`` inside ``window_sec``."""
        ts = time.monotonic() if now is None else now
        cutoff = ts - window_sec

        def _count(raw: list[float]) -> int:
            # Prune in place so counters stay bounded.
            kept = [t for t in raw if t >= cutoff]
            raw[:] = kept
            return len(kept)

        with self._diag_lock:
            ok = _count(self._resync_ok_mono.setdefault(stream_id, []))
            fail = _count(self._resync_fail_mono.setdefault(stream_id, []))
            return ok, fail

    def mark_stream_connected(self, stream_id: str, *, connected: bool) -> None:
        """Track how long a stream has been disconnected (WHI-819)."""
        with self._diag_lock:
            if connected:
                self._stream_disconnected_since.pop(stream_id, None)
            else:
                self._stream_disconnected_since.setdefault(stream_id, time.monotonic())

    def stream_disconnected_age_sec(
        self, stream_id: str, *, now: float | None = None
    ) -> float | None:
        with self._diag_lock:
            since = self._stream_disconnected_since.get(stream_id)
        if since is None:
            return None
        ts = time.monotonic() if now is None else now
        return max(0.0, ts - since)

    def known_stream_ids(self) -> list[str]:
        """Configured sockets plus any stream that has a disconnect timestamp."""
        with self._diag_lock:
            disc = set(self._stream_disconnected_since)
        ids = {s.stream_id for s in self._sockets}
        ids.update(disc)
        return sorted(ids)

    def stream_connected(self, stream_id: str) -> bool:
        for sock in self._sockets:
            if sock.stream_id == stream_id:
                return sock.is_connected
        return self._registry.connection_count(stream_id) > 0

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    def _set_stream_error(self, stream_id: str, message: str) -> None:
        self._stream_errors[stream_id] = message
        logger.error("ws stream %s error: %s", stream_id, message)

    def _clear_stream_error(self, stream_id: str) -> None:
        self._stream_errors.pop(stream_id, None)

    def _fail_subscribe_books(
        self,
        stream_id: str,
        *,
        venue: str,
        instrument_type: str,
        symbols: Sequence[str],
        message: str,
    ) -> None:
        """Surface a subscribe failure without wiping already-HEALTHY books.

        Venue acks do not echo which topics failed, so we cannot map an ack to a
        specific chunk. Mark every non-HEALTHY book DISCONNECTED and keep the
        error on the stream; already-synced books keep serving.
        """
        self._set_stream_error(stream_id, message)
        for sym in symbols:
            book = self._registry.get(venue, sym, instrument_type)
            if book is None:
                continue
            if book.health is BookHealth.HEALTHY:
                continue
            book.set_health(BookHealth.DISCONNECTED, error=message)

    async def start(
        self,
        *,
        binance_spot_symbols: Sequence[str] = (),
        binance_futures_symbols: Sequence[str] = (),
        bybit_spot_symbols: Sequence[str] = (),
        bybit_linear_symbols: Sequence[str] = (),
        hyperliquid_coins: Sequence[str] = (),
        lighter_markets: dict[str, str] | None = None,
        apex_symbols: Sequence[str] = (),
    ) -> None:
        """Start enabled streams. Failures log and skip; never raise to block boot."""
        if self._started:
            return
        self._started = True
        if not self._settings.enabled:
            logger.info("ws feeds disabled via config")
            return

        streams = self._settings.streams
        self._symbols = {
            "binance_spot": [s.upper() for s in binance_spot_symbols],
            "binance_futures": [s.upper() for s in binance_futures_symbols],
            "bybit_spot": [s.upper() for s in bybit_spot_symbols],
            "bybit_linear": [s.upper() for s in bybit_linear_symbols],
            "hyperliquid": list(hyperliquid_coins),
            "apex": [s.upper() for s in apex_symbols],
        }
        self._lighter_markets = dict(lighter_markets or {})

        starters: list[tuple[str, Callable[[], Awaitable[None]]]] = []
        if streams.binance_spot and self._symbols["binance_spot"]:
            starters.append(("binance_spot", self._start_binance_spot))
        if streams.binance_futures and self._symbols["binance_futures"]:
            starters.append(("binance_futures", self._start_binance_futures))
        if streams.bybit_spot and self._symbols["bybit_spot"]:
            starters.append(("bybit_spot", self._start_bybit_spot))
        if streams.bybit_linear and self._symbols["bybit_linear"]:
            starters.append(("bybit_linear", self._start_bybit_linear))
        if streams.hyperliquid and self._symbols["hyperliquid"]:
            starters.append(("hyperliquid", self._start_hyperliquid))
        if streams.lighter and self._lighter_markets:
            starters.append(("lighter", self._start_lighter))
        if streams.apex and self._symbols["apex"]:
            starters.append(("apex", self._start_apex))

        for name, starter in starters:
            try:
                await starter()
            except Exception:  # noqa: BLE001 — degrade stream only
                logger.exception("ws stream %s failed to start; REST fallback remains", name)

    async def stop(self) -> None:
        for sock in self._sockets:
            await sock.stop()
            self._registry.mark_connection(sock.stream_id, open=False)
        self._sockets.clear()
        self._stream_socks.clear()
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
        self._started = False

    def _on_stream_closed(
        self,
        stream_id: str,
        venue: str,
        instrument_type: str,
        symbols: Sequence[str],
    ) -> None:
        """Mark connection closed and books disconnected so REST fallback engages."""
        self._registry.mark_connection(stream_id, open=False)
        self.mark_stream_connected(stream_id, connected=False)
        for sym in symbols:
            book = self._registry.get(venue, sym, instrument_type)
            if book is not None and book.health is BookHealth.HEALTHY:
                book.set_health(
                    BookHealth.DISCONNECTED, error=f"{stream_id} socket closed"
                )

    def _spawn_socket(
        self,
        url: str,
        *,
        stream_id: str,
        on_message: Callable[
            [dict[str, Any] | list[Any] | str], Awaitable[None]
        ],
        on_open: Callable[[], Awaitable[None]] | None,
        venue: str,
        instrument_type: str,
        symbols: Sequence[str],
        sock_holder: list[ReconnectingWebSocket] | None = None,
        # Ellipsis = use config default; explicit None disables transport pings (HL).
        ping_interval: float | None | EllipsisType = ...,
        app_ping_interval_sec: float | None = None,
        app_ping_payload: dict[str, Any] | None = None,
    ) -> ReconnectingWebSocket:
        """Build one multiplexed socket; on drop → REST fallback for those books."""
        syms = list(symbols)
        transport_ping: float | None
        if ping_interval is ...:
            transport_ping = self._settings.default_transport_ping_interval_sec
        else:
            transport_ping = ping_interval

        async def on_close() -> None:
            self._on_stream_closed(stream_id, venue, instrument_type, syms)

        async def wrapped_open() -> None:
            self.mark_stream_connected(stream_id, connected=True)
            if on_open is not None:
                await on_open()

        # Start in the disconnected bucket so a stream that never connects still
        # ages toward ws_disconnected (WHI-819 — cold-fail must page).
        self.mark_stream_connected(stream_id, connected=False)
        sock = ReconnectingWebSocket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=wrapped_open,
            on_close=on_close,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
            ping_interval=transport_ping,
            app_ping_interval_sec=app_ping_interval_sec,
            app_ping_payload=app_ping_payload,
        )
        if sock_holder is not None:
            sock_holder.append(sock)
        self._sockets.append(sock)
        self._stream_socks[stream_id] = sock
        sock.start()
        return sock

    # ----- Binance spot -------------------------------------------------

    async def _start_binance_spot(self) -> None:
        symbols = self._symbols["binance_spot"]
        for sym in symbols:
            book = self._registry.get_or_create("binance", sym, "spot")
            book.set_health(BookHealth.CONNECTING)
            self._spot_syncs[sym] = BinanceSpotSync(book)

        streams = "/".join(f"{s.lower()}@depth@100ms" for s in symbols)
        url = f"{_BINANCE_SPOT_WS}?streams={streams}"
        stream_id = "binance_spot"

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            # block=True: wait for weight slots so first snapshots always land
            # (non-blocking storm throttle would leave books with no last_update_id
            # stuck RESYNCING forever — on_diff won't re-request without a snapshot).
            for sym in symbols:
                await self._resync_binance_spot(sym, block=True)

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            data = payload.get("data", payload)
            if not isinstance(data, dict) or "u" not in data:
                return
            sym = str(data.get("s") or "").upper()
            sync = self._spot_syncs.get(sym)
            if sync is None:
                return
            result = sync.on_diff(data)
            if result.needs_resync:
                await self._resync_binance_spot(sym, block=False)

        self._spawn_socket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="binance",
            instrument_type="spot",
            symbols=symbols,
        )

    async def _resync_binance_spot(self, symbol: str, *, block: bool = False) -> None:
        sync = self._spot_syncs.get(symbol)
        if sync is None:
            return
        now = time.monotonic()
        min_iv = self._settings.binance_spot_min_resync_interval_sec
        last = self._binance_spot_last_resync_mono.get(symbol, 0.0)
        if now - last < min_iv:
            if sync.book.health is not BookHealth.RESYNCING:
                sync.book.set_health(BookHealth.RESYNCING, error="binance spot resync throttled")
            logger.info("binance spot resync interval-throttled %s", symbol)
            return
        if not block and self._binance_spot_weight_limiter.expected_wait_s() > 0:
            # Storm path: stay RESYNCING / unservable rather than hammer depth.
            if sync.book.health is not BookHealth.RESYNCING:
                sync.book.set_health(BookHealth.RESYNCING, error="binance spot resync throttled")
            logger.info("binance spot resync weight-throttled %s", symbol)
            return
        try:
            # block=True waits for a weight slot (startup snapshots); else fail-fast.
            await self._binance_spot_weight_limiter.acquire(
                max_wait_s=None if block else 0.0
            )
        except RateLimitWaitExceeded:
            if sync.book.health is not BookHealth.RESYNCING:
                sync.book.set_health(BookHealth.RESYNCING, error="binance spot resync throttled")
            logger.info("binance spot resync weight-budget throttled %s", symbol)
            return
        self._binance_spot_last_resync_mono[symbol] = time.monotonic()
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            resp = await self._http().get(
                f"{_BINANCE_SPOT_REST}/api/v3/depth",
                params={"symbol": symbol, "limit": "1000"},
            )
            resp.raise_for_status()
            data = resp.json()
            sync.apply_snapshot(
                last_update_id=int(data["lastUpdateId"]),
                bids=data["bids"],
                asks=data["asks"],
            )
            if sync.book.health is BookHealth.SYNCING and sync.book.last_update_id is not None:
                # Snapshot applied; wait for first valid diff to mark HEALTHY.
                sync.book.set_health(BookHealth.SYNCING)
            self.note_resync("binance_spot", ok=True)
            logger.info("binance spot resync ok %s lastUpdateId=%s", symbol, data["lastUpdateId"])
        except Exception as exc:  # noqa: BLE001
            self.note_resync("binance_spot", ok=False)
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("binance spot resync failed %s: %s", symbol, exc)

    # ----- Binance futures ----------------------------------------------

    async def _start_binance_futures(self) -> None:
        symbols = self._symbols["binance_futures"]
        for sym in symbols:
            book = self._registry.get_or_create("binance", sym, "perp")
            book.set_health(BookHealth.CONNECTING)
            self._fut_syncs[sym] = BinanceFuturesSync(book)

        streams = "/".join(f"{s.lower()}@depth@100ms" for s in symbols)
        url = f"{_BINANCE_FAPI_WS}?streams={streams}"
        stream_id = "binance_futures"

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            for sym in symbols:
                await self._resync_binance_futures(sym)

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            data = payload.get("data", payload)
            if not isinstance(data, dict) or "u" not in data:
                return
            sym = str(data.get("s") or "").upper()
            sync = self._fut_syncs.get(sym)
            if sync is None:
                return
            result = sync.on_diff(data)
            if result.needs_resync:
                await self._resync_binance_futures(sym)

        self._spawn_socket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="binance",
            instrument_type="perp",
            symbols=symbols,
        )

    async def _resync_binance_futures(self, symbol: str) -> None:
        sync = self._fut_syncs.get(symbol)
        if sync is None:
            return
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            resp = await self._http().get(
                f"{_BINANCE_FAPI_REST}/fapi/v1/depth",
                params={"symbol": symbol, "limit": "1000"},
            )
            resp.raise_for_status()
            data = resp.json()
            sync.apply_snapshot(
                last_update_id=int(data["lastUpdateId"]),
                bids=data["bids"],
                asks=data["asks"],
            )
            self.note_resync("binance_futures", ok=True)
            logger.info(
                "binance futures resync ok %s lastUpdateId=%s", symbol, data["lastUpdateId"]
            )
        except Exception as exc:  # noqa: BLE001
            self.note_resync("binance_futures", ok=False)
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("binance futures resync failed %s: %s", symbol, exc)

    # ----- Bybit --------------------------------------------------------

    async def _start_bybit_spot(self) -> None:
        await self._start_bybit("spot", self._symbols["bybit_spot"], _BYBIT_SPOT_WS)

    async def _start_bybit_linear(self) -> None:
        await self._start_bybit("linear", self._symbols["bybit_linear"], _BYBIT_LINEAR_WS)

    async def _start_bybit(
        self, category: str, symbols: Sequence[str], ws_url: str
    ) -> None:
        instrument = "spot" if category == "spot" else "perp"
        for sym in symbols:
            book = self._registry.get_or_create("bybit", sym, instrument)
            book.set_health(BookHealth.CONNECTING)
            self._bybit_syncs[f"{category}:{sym}"] = BybitSync(book)

        stream_id = f"bybit_{category}"
        topics = [f"orderbook.1000.{s}" for s in symbols]
        chunk_size = (
            self._settings.bybit_spot_subscribe_chunk
            if category == "spot"
            else self._settings.bybit_linear_subscribe_chunk
        )
        topic_chunks = chunked(topics, chunk_size)
        sock_holder: list[ReconnectingWebSocket] = []

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            self._clear_stream_error(stream_id)
            # Chunked subscribe — Bybit spot rejects args size > 10 (WHI-855).
            for batch in topic_chunks:
                await sock_holder[0].send_json({"op": "subscribe", "args": batch})

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            # Subscribe ack: {"success": bool, "ret_msg": "...", "op": "subscribe"}
            if payload.get("op") == "subscribe" or "success" in payload:
                ok = payload.get("success")
                if ok is False:
                    ret = str(
                        payload.get("ret_msg") or payload.get("retMsg") or "subscribe failed"
                    )
                    self._fail_subscribe_books(
                        stream_id,
                        venue="bybit",
                        instrument_type=instrument,
                        symbols=symbols,
                        message=ret,
                    )
                    return
                if ok is True:
                    return
            topic = str(payload.get("topic") or "")
            if not topic.startswith("orderbook."):
                return
            # topic = orderbook.1000.BTCUSDT
            parts = topic.split(".")
            if len(parts) < 3:
                return
            sym = parts[-1].upper()
            sync = self._bybit_syncs.get(f"{category}:{sym}")
            if sync is None:
                return
            data = payload.get("data")
            if not isinstance(data, dict):
                return
            msg_type = str(payload.get("type") or "delta")
            result = sync.on_message(msg_type, data)
            if result.needs_resync:
                await self._resync_bybit(category, sym, sync)

        self._spawn_socket(
            ws_url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="bybit",
            instrument_type=instrument,
            symbols=symbols,
            sock_holder=sock_holder,
        )

    async def _resync_bybit(self, category: str, symbol: str, sync: BybitSync) -> None:
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            resp = await self._http().get(
                f"{_BYBIT_REST}/v5/market/orderbook",
                params={"category": category, "symbol": symbol, "limit": "1000"},
            )
            resp.raise_for_status()
            body = resp.json()
            result = body.get("result") or {}
            data = {
                "u": int(result.get("u") or 1),
                "seq": result.get("seq"),
                "b": result.get("b") or [],
                "a": result.get("a") or [],
            }
            sync.on_message("snapshot", data)
            self.note_resync(bybit_stream_id(category), ok=True)
            logger.info("bybit %s resync ok %s", category, symbol)
        except Exception as exc:  # noqa: BLE001
            self.note_resync(bybit_stream_id(category), ok=False)
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("bybit %s resync failed %s: %s", category, symbol, exc)

    # ----- Hyperliquid --------------------------------------------------

    async def _start_hyperliquid(self) -> None:
        coins = self._symbols["hyperliquid"]
        for coin in coins:
            book = self._registry.get_or_create("hyperliquid", coin, "perp")
            book.set_health(BookHealth.CONNECTING)
            self._hl_syncs[coin] = HyperliquidSync(book)

        stream_id = "hyperliquid"
        sock_holder: list[ReconnectingWebSocket] = []
        # HL ignores transport pings → disable unless config explicitly re-enables.
        transport_ping: float | None = (
            self._settings.default_transport_ping_interval_sec
            if self._settings.hyperliquid_transport_ping
            else None
        )
        app_ping_iv = self._settings.hyperliquid_app_ping_interval_sec

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            self._clear_stream_error(stream_id)
            for coin in coins:
                await sock_holder[0].send_json(
                    {
                        "method": "subscribe",
                        "subscription": {
                            "type": "l2Book",
                            "coin": coin,
                            "fast": False,  # 20 levels; fast:true is 5 (WHI-847)
                        },
                    }
                )

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            channel = payload.get("channel")
            # App-level pong replies — ignore.
            if channel == "pong":
                return
            data = payload.get("data")
            if channel == "error" or payload.get("error"):
                err = data if data is not None else payload.get("error") or payload
                self._set_stream_error(stream_id, f"hyperliquid error: {err}")
                return
            if channel != "l2Book" or not isinstance(data, dict):
                return
            coin = str(data.get("coin") or "")
            sync = self._hl_syncs.get(coin)
            if sync is None:
                # HIP-3 bare match
                for key, s in self._hl_syncs.items():
                    if key.endswith(f":{coin}") or key == coin:
                        sync = s
                        break
            if sync is None:
                return
            levels = data.get("levels")
            if not isinstance(levels, list) or len(levels) < 2:
                return
            bids_raw = [[lvl.get("px"), lvl.get("sz")] for lvl in levels[0]]
            asks_raw = [[lvl.get("px"), lvl.get("sz")] for lvl in levels[1]]
            sync.on_snapshot(bids_raw, asks_raw)

        self._spawn_socket(
            _HL_WS,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="hyperliquid",
            instrument_type="perp",
            symbols=coins,
            sock_holder=sock_holder,
            ping_interval=transport_ping,
            app_ping_interval_sec=app_ping_iv,
            app_ping_payload={"method": "ping"},
        )

    # ----- Lighter ------------------------------------------------------

    async def _start_lighter(self) -> None:
        for market_id, symbol in self._lighter_markets.items():
            book = self._registry.get_or_create("lighter", symbol, "perp")
            book.set_health(BookHealth.CONNECTING)
            self._lighter_syncs[str(market_id)] = LighterSync(book)

        stream_id = "lighter"
        sock_holder: list[ReconnectingWebSocket] = []

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            self._clear_stream_error(stream_id)
            for market_id in self._lighter_markets:
                await sock_holder[0].send_json(
                    {"type": "subscribe", "channel": f"order_book/{market_id}"}
                )

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            # Age out lost resubscribes even when the book is quiet (no new gaps).
            self._expire_stale_lighter_resyncs(time.monotonic())
            if payload.get("error") or str(payload.get("type") or "") == "error":
                err = payload.get("error") or payload.get("message") or payload
                self._set_stream_error(stream_id, f"lighter error: {err}")
                return
            channel = str(payload.get("channel") or "")
            if "order_book" not in channel:
                return
            # channel like order_book/0 or order_book:0
            market_id = channel.split("/")[-1].split(":")[-1]
            sync = self._lighter_syncs.get(str(market_id))
            if sync is None:
                return
            data = payload.get("order_book") or payload.get("data") or payload
            if not isinstance(data, dict):
                return
            msg_type = str(payload.get("type") or data.get("type") or "")
            bids = data.get("bids") or data.get("b") or []
            asks = data.get("asks") or data.get("a") or []
            # Normalize [{price,size}] → [[p,s]]
            bids_n = _normalize_lighter_levels(bids)
            asks_n = _normalize_lighter_levels(asks)
            if msg_type in ("subscribed/order_book", "snapshot", ""):
                nonce = int(data.get("nonce") or data.get("end_nonce") or 0)
                if msg_type.startswith("subscribed") or "nonce" in data:
                    if data.get("begin_nonce") is None or msg_type.startswith("subscribed"):
                        sync.on_snapshot(bids=bids_n, asks=asks_n, nonce=nonce)
                        # Complete a pending resubscribe only when a real snapshot lands.
                        mid_key = str(market_id)
                        if mid_key in self._lighter_resync_pending_mono:
                            self._lighter_resync_pending_mono.pop(mid_key, None)
                            self.note_resync("lighter", ok=True)
                        return
            begin_raw = data.get("begin_nonce")
            nonce_raw = data.get("nonce")
            if begin_raw is not None and nonce_raw is not None:
                result = sync.on_update(
                    bids=bids_n,
                    asks=asks_n,
                    begin_nonce=int(begin_raw),
                    nonce=int(nonce_raw),
                    offset=data.get("offset"),
                )
                if result.needs_resync:
                    await self._resync_lighter(str(market_id), sync)

        self._spawn_socket(
            _LIGHTER_WS,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="lighter",
            instrument_type="perp",
            symbols=list(self._lighter_markets.values()),
            sock_holder=sock_holder,
        )

    def _expire_stale_lighter_resyncs(self, now: float) -> None:
        """Age out resubscribes that never produced a snapshot (WHI-855)."""
        timeout = self._settings.lighter_resync_snapshot_timeout_sec
        stale = [
            mid
            for mid, sent_at in self._lighter_resync_pending_mono.items()
            if now - sent_at >= timeout
        ]
        for mid in stale:
            self._lighter_resync_pending_mono.pop(mid, None)
            self.note_resync("lighter", ok=False)
            sync = self._lighter_syncs.get(mid)
            if sync is not None and sync.book.health is BookHealth.RESYNCING:
                # Stay unservable; REST fallback continues via try_local_book.
                sync.book.set_health(
                    BookHealth.RESYNCING,
                    error="lighter resubscribe snapshot timed out",
                )
            logger.warning("lighter resync snapshot timed out market=%s", mid)

    async def _resync_lighter(self, market_id: str, sync: LighterSync) -> None:
        """Recover from a gap by re-subscribing the channel (WHI-855).

        The server's subscribe snapshot carries a real nonce the delta chain can
        continue from. REST-with-synthetic-``nonce=0`` livelocks forever.
        """
        now = time.monotonic()
        self._expire_stale_lighter_resyncs(now)
        # Already waiting on a prior resubscribe — do not re-arm the timeout clock
        # or re-send (that would make the 15s snapshot timeout unreachable).
        if market_id in self._lighter_resync_pending_mono:
            logger.info("lighter resync already pending market=%s", market_id)
            return
        sock = self._stream_socks.get("lighter")
        if sock is None or not sock.is_connected:
            self.note_resync("lighter", ok=False)
            sync.book.set_health(
                BookHealth.DISCONNECTED, error="lighter resync: socket not connected"
            )
            logger.warning("lighter resync aborted market=%s: socket not connected", market_id)
            return
        last = self._lighter_last_resync_mono.get(market_id, 0.0)
        min_iv = self._settings.lighter_min_resync_interval_sec
        if now - last < min_iv:
            logger.info("lighter resync throttled market=%s", market_id)
            return
        self._lighter_last_resync_mono[market_id] = now
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            # Stamp once; subsequent gaps while pending leave this timestamp alone.
            self._lighter_resync_pending_mono[market_id] = now
            await sock.send_json(
                {"type": "subscribe", "channel": f"order_book/{market_id}"}
            )
            # note_resync(ok=True) only when the server's snapshot arrives (on_message).
            logger.info("lighter resync resubscribed market=%s", market_id)
        except Exception as exc:  # noqa: BLE001
            self._lighter_resync_pending_mono.pop(market_id, None)
            self.note_resync("lighter", ok=False)
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("lighter resync failed market=%s: %s", market_id, exc)

    # ----- ApeX ---------------------------------------------------------

    async def _start_apex(self) -> None:
        symbols = self._symbols["apex"]
        for sym in symbols:
            book = self._registry.get_or_create("apex", sym, "perp")
            book.set_health(BookHealth.CONNECTING)
            self._apex_syncs[sym] = ApexSync(book)

        stream_id = "apex"
        ts_ms = int(time.time() * 1000)
        url = f"{_APEX_WS_BASE}?{urlencode({'v': '2', 'timestamp': str(ts_ms)})}"
        sock_holder: list[ReconnectingWebSocket] = []
        chunk_size = self._settings.apex_subscribe_chunk
        topic_chunks = chunked(
            [f"orderBook200.H.{s}" for s in symbols], chunk_size
        )

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            self._clear_stream_error(stream_id)
            # Chunked subscribe — multi-arg batches return "handler not found" (WHI-855).
            for batch in topic_chunks:
                await sock_holder[0].send_json({"op": "subscribe", "args": batch})

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            # Application-level ping from ApeX — must answer or the socket dies.
            op = str(payload.get("op") or "")
            if op == "ping":
                if sock_holder:
                    await sock_holder[0].send_json({"op": "pong"})
                return
            # Subscribe ack / error surfaces
            if op == "subscribe" or "success" in payload or payload.get("error"):
                ok = payload.get("success")
                err = payload.get("error") or payload.get("ret_msg") or payload.get("retMsg")
                if ok is False or err:
                    msg = str(err or "subscribe failed")
                    self._fail_subscribe_books(
                        stream_id,
                        venue="apex",
                        instrument_type="perp",
                        symbols=symbols,
                        message=msg,
                    )
                    return
                if ok is True:
                    return
            topic = str(payload.get("topic") or payload.get("stream") or "")
            if "orderBook" not in topic and "orderbook" not in topic.lower():
                # try channel field
                topic = str(payload.get("channel") or topic)
            book_sym = _apex_symbol_from_topic(topic, symbols)
            if book_sym is None:
                data = payload.get("data")
                if isinstance(data, dict) and data.get("s"):
                    book_sym = str(data["s"]).upper()
            if book_sym is None:
                return
            sync = self._apex_syncs.get(book_sym)
            if sync is None:
                return
            data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            if not isinstance(data, dict):
                return
            msg_type = str(payload.get("type") or data.get("type") or "delta")
            update_id = int(data.get("u") or data.get("lastUpdateId") or 0)
            bids = data.get("b") or data.get("bids") or []
            asks = data.get("a") or data.get("asks") or []
            result: ApplyResult
            if msg_type == "snapshot":
                result = sync.on_snapshot(bids=bids, asks=asks, update_id=update_id)
            else:
                result = sync.on_delta(bids=bids, asks=asks, update_id=update_id)
            if result.needs_resync:
                await self._resync_apex(book_sym, sync)

        self._spawn_socket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            venue="apex",
            instrument_type="perp",
            symbols=symbols,
            sock_holder=sock_holder,
        )

    async def _resync_apex(self, symbol: str, sync: ApexSync) -> None:
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            resp = await self._http().get(
                f"{_APEX_REST}/api/v3/depth",
                params={"symbol": symbol, "limit": "100"},
            )
            resp.raise_for_status()
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) else body
            if not isinstance(data, dict):
                raise ValueError("apex depth missing data")
            update_id = int(data.get("u") or data.get("lastUpdateId") or 1)
            sync.on_snapshot(
                bids=data.get("b") or data.get("bids") or [],
                asks=data.get("a") or data.get("asks") or [],
                update_id=update_id,
            )
            self.note_resync("apex", ok=True)
            logger.info("apex resync ok %s", symbol)
        except Exception as exc:  # noqa: BLE001
            self.note_resync("apex", ok=False)
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("apex resync failed %s: %s", symbol, exc)


def stream_id_for_book(venue: str, instrument_type: str) -> str:
    """Map local-book venue/instrument to multiplex stream_id (WHI-819 monitor)."""
    v = venue.lower()
    it = instrument_type.lower()
    if v == "binance" and it == "spot":
        return "binance_spot"
    if v == "binance" and it == "perp":
        return "binance_futures"
    if v == "bybit" and it == "spot":
        return "bybit_spot"
    if v == "bybit" and it == "perp":
        return "bybit_linear"
    if v == "hyperliquid":
        return "hyperliquid"
    if v == "lighter":
        return "lighter"
    if v == "apex":
        return "apex"
    return f"{v}_{it}"


def bybit_stream_id(category: str) -> str:
    """Bybit WS stream_id for spot vs linear category."""
    return "bybit_spot" if category == "spot" else "bybit_linear"


def _normalize_lighter_levels(raw: object) -> list[list[str]]:
    if not isinstance(raw, list):
        return []
    out: list[list[str]] = []
    for row in raw:
        if isinstance(row, dict):
            px = row.get("price") or row.get("px")
            sz = row.get("size") or row.get("sz") or row.get("remaining_base_amount")
            if px is None or sz is None:
                continue
            out.append([str(px), str(sz)])
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            out.append([str(row[0]), str(row[1])])
    return out


def _apex_symbol_from_topic(topic: str, symbols: Sequence[str]) -> str | None:
    upper = topic.upper()
    for s in symbols:
        if s.upper() in upper:
            return s.upper()
    # orderBook200.H.BTCUSDT
    if "." in topic:
        tail = topic.rsplit(".", 1)[-1].upper()
        if tail in {s.upper() for s in symbols}:
            return tail
    return None


_MANAGER: WsFeedManager | None = None


def default_ws_feed_manager() -> WsFeedManager | None:
    return _MANAGER


def set_ws_feed_manager(manager: WsFeedManager | None) -> None:
    global _MANAGER
    _MANAGER = manager
