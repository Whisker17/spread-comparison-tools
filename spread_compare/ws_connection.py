"""Reconnecting WebSocket client with jittered backoff (WHI-847 / WHI-855).

One connection per stream multiplexes symbol subscriptions — asset count must
not increase connection count.

Heartbeat is a **per-venue** property (WHI-855):
- Transport-level WebSocket pings work for Binance / Bybit / Lighter.
- Hyperliquid ignores transport pings → disable them and send application
  ``{"method":"ping"}`` on a timer instead.
- ApeX *sends* application ``{"op":"ping"}``; the feed replies ``{"op":"pong"}``
  (not handled here).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any] | list[Any] | str], Awaitable[None]]


class ReconnectingWebSocket:
    """Single logical connection with auto-reconnect.

    ``on_open`` is invoked after each successful connect (subscribe there).
    ``on_close`` is invoked when the socket drops (mark books disconnected).
    """

    def __init__(
        self,
        url: str,
        *,
        stream_id: str,
        on_message: MessageHandler,
        on_open: Callable[[], Awaitable[None]] | None = None,
        on_close: Callable[[], Awaitable[None]] | None = None,
        reconnect_min_sec: float,
        reconnect_max_sec: float,
        ping_interval: float | None = 20.0,
        app_ping_interval_sec: float | None = None,
        app_ping_payload: dict[str, Any] | None = None,
    ) -> None:
        self.url = url
        self.stream_id = stream_id
        self._on_message = on_message
        self._on_open = on_open
        self._on_close = on_close
        self._reconnect_min = reconnect_min_sec
        self._reconnect_max = reconnect_max_sec
        self._ping_interval = ping_interval
        self._app_ping_interval_sec = app_ping_interval_sec
        self._app_ping_payload = app_ping_payload
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._send_queue: asyncio.Queue[str] = asyncio.Queue()
        self._connected = asyncio.Event()
        self._ws: Any = None
        self._open_count = 0

    @property
    def open_count(self) -> int:
        """How many times the socket has successfully opened (tests)."""
        return self._open_count

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"ws-{self.stream_id}")

    async def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._send_queue.put(json.dumps(payload))

    async def send_text(self, text: str) -> None:
        await self._send_queue.put(text)

    async def _run(self) -> None:
        delay = self._reconnect_min
        while not self._stop.is_set():
            try:
                await self._session()
                delay = self._reconnect_min
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect loop
                logger.warning(
                    "ws %s disconnected: %s; reconnect in %.1fs",
                    self.stream_id,
                    exc,
                    delay,
                )
                self._connected.clear()
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                    break
                except TimeoutError:
                    pass
                # Full jitter backoff.
                delay = min(self._reconnect_max, delay * 2)
                delay = random.uniform(self._reconnect_min, delay)

    async def _session(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "websockets package is required for WS orderbook ingest"
            ) from exc

        # When transport pings are disabled, also clear ping_timeout (websockets
        # treats a set timeout with no pings as a wait-for-server-ping).
        transport_ping = self._ping_interval
        transport_ping_timeout = self._ping_interval if transport_ping is not None else None

        async with connect(
            self.url,
            ping_interval=transport_ping,
            ping_timeout=transport_ping_timeout,
            max_size=8 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            self._open_count += 1
            self._connected.set()
            logger.info("ws %s connected url=%s", self.stream_id, self.url)
            if self._on_open is not None:
                await self._on_open()

            sender = asyncio.create_task(self._sender(ws), name=f"ws-send-{self.stream_id}")
            app_ping = self._maybe_start_app_ping()
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    try:
                        payload: dict[str, Any] | list[Any] | str = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = raw
                    await self._on_message(payload)
            finally:
                if app_ping is not None:
                    app_ping.cancel()
                    try:
                        await app_ping
                    except asyncio.CancelledError:
                        pass
                sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
                self._ws = None
                self._connected.clear()
                if self._on_close is not None:
                    try:
                        await self._on_close()
                    except Exception:  # noqa: BLE001
                        logger.exception("ws %s on_close failed", self.stream_id)

    def _maybe_start_app_ping(self) -> asyncio.Task[None] | None:
        if (
            self._app_ping_interval_sec is None
            or self._app_ping_interval_sec <= 0
            or self._app_ping_payload is None
        ):
            return None
        return asyncio.create_task(
            self._app_ping_loop(), name=f"ws-app-ping-{self.stream_id}"
        )

    async def _app_ping_loop(self) -> None:
        assert self._app_ping_interval_sec is not None
        assert self._app_ping_payload is not None
        payload = self._app_ping_payload
        interval = self._app_ping_interval_sec
        while not self._stop.is_set():
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            if self._stop.is_set() or not self._connected.is_set():
                break
            try:
                await self.send_json(payload)
            except Exception:  # noqa: BLE001
                logger.debug("ws %s app ping send failed", self.stream_id, exc_info=True)
                break

    async def _sender(self, ws: Any) -> None:
        while True:
            text = await self._send_queue.get()
            await ws.send(text)
