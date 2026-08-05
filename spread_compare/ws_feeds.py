"""Venue WebSocket feed workers that maintain :class:`WsBookRegistry` (WHI-847).

Each stream opens **one** connection and multiplexes symbol subscriptions.
Connect failure degrades that stream only (REST fallback remains available).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from spread_compare.local_book import BookHealth
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
_LIGHTER_REST = "https://mainnet.zklighter.elliot.ai"
_APEX_WS_BASE = "wss://quote.omni.apex.exchange/realtime_public"
_APEX_REST = "https://omni.apex.exchange"


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
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        self._spot_syncs: dict[str, BinanceSpotSync] = {}
        self._fut_syncs: dict[str, BinanceFuturesSync] = {}
        self._bybit_syncs: dict[str, BybitSync] = {}
        self._hl_syncs: dict[str, HyperliquidSync] = {}
        self._lighter_syncs: dict[str, LighterSync] = {}
        self._apex_syncs: dict[str, ApexSync] = {}
        self._lighter_last_resync_mono: dict[str, float] = {}
        # market_id → symbol for Lighter
        self._lighter_markets: dict[str, str] = {}
        self._symbols: dict[str, list[str]] = {}

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

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

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
            for sym in symbols:
                await self._resync_binance_spot(sym)

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
                await self._resync_binance_spot(sym)

        sock = ReconnectingWebSocket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

    async def _resync_binance_spot(self, symbol: str) -> None:
        sync = self._spot_syncs.get(symbol)
        if sync is None:
            return
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
            logger.info("binance spot resync ok %s lastUpdateId=%s", symbol, data["lastUpdateId"])
        except Exception as exc:  # noqa: BLE001
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

        sock = ReconnectingWebSocket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

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
            logger.info(
                "binance futures resync ok %s lastUpdateId=%s", symbol, data["lastUpdateId"]
            )
        except Exception as exc:  # noqa: BLE001
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

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            # Bybit multiplex: one subscribe op with multiple args.
            await sock.send_json({"op": "subscribe", "args": topics})

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
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

        sock = ReconnectingWebSocket(
            ws_url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

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
            logger.info("bybit %s resync ok %s", category, symbol)
        except Exception as exc:  # noqa: BLE001
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

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            for coin in coins:
                await sock.send_json(
                    {
                        "method": "subscribe",
                        "subscription": {"type": "l2Book", "coin": coin},
                    }
                )

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            channel = payload.get("channel")
            data = payload.get("data")
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

        sock = ReconnectingWebSocket(
            _HL_WS,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

    # ----- Lighter ------------------------------------------------------

    async def _start_lighter(self) -> None:
        for market_id, symbol in self._lighter_markets.items():
            book = self._registry.get_or_create("lighter", symbol, "perp")
            book.set_health(BookHealth.CONNECTING)
            self._lighter_syncs[str(market_id)] = LighterSync(book)

        stream_id = "lighter"

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            for market_id in self._lighter_markets:
                await sock.send_json(
                    {"type": "subscribe", "channel": f"order_book/{market_id}"}
                )

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
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

        sock = ReconnectingWebSocket(
            _LIGHTER_WS,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

    async def _resync_lighter(self, market_id: str, sync: LighterSync) -> None:
        now = time.monotonic()
        last = self._lighter_last_resync_mono.get(market_id, 0.0)
        min_iv = self._settings.lighter_min_resync_interval_sec
        if now - last < min_iv:
            logger.info("lighter resync throttled market=%s", market_id)
            return
        self._lighter_last_resync_mono[market_id] = now
        sync.book.set_health(BookHealth.RESYNCING)
        try:
            resp = await self._http().get(
                f"{_LIGHTER_REST}/api/v1/orderBookOrders",
                params={"market_id": market_id, "limit": "100"},
            )
            resp.raise_for_status()
            body = resp.json()
            # Aggregate like the REST adapter; treat as snapshot with nonce 0.
            bids = _aggregate_lighter_orders(body.get("bids") or body.get("bid_orders") or [])
            asks = _aggregate_lighter_orders(body.get("asks") or body.get("ask_orders") or [])
            sync.on_snapshot(bids=bids, asks=asks, nonce=0)
            logger.info("lighter resync ok market=%s", market_id)
        except Exception as exc:  # noqa: BLE001
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

        async def on_open() -> None:
            self._registry.mark_connection(stream_id, open=True)
            args = [f"orderBook200.H.{s}" for s in symbols]
            await sock.send_json({"op": "subscribe", "args": args})

        async def on_message(payload: dict[str, Any] | list[Any] | str) -> None:
            if not isinstance(payload, dict):
                return
            topic = str(payload.get("topic") or payload.get("stream") or "")
            if "orderBook" not in topic and "orderbook" not in topic.lower():
                # try channel field
                topic = str(payload.get("channel") or topic)
            sym = _apex_symbol_from_topic(topic, symbols)
            if sym is None:
                data = payload.get("data")
                if isinstance(data, dict) and data.get("s"):
                    sym = str(data["s"]).upper()
            if sym is None:
                return
            sync = self._apex_syncs.get(sym)
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
                await self._resync_apex(sym, sync)

        sock = ReconnectingWebSocket(
            url,
            stream_id=stream_id,
            on_message=on_message,
            on_open=on_open,
            reconnect_min_sec=self._settings.reconnect_min_sec,
            reconnect_max_sec=self._settings.reconnect_max_sec,
        )
        self._sockets.append(sock)
        sock.start()

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
            logger.info("apex resync ok %s", symbol)
        except Exception as exc:  # noqa: BLE001
            sync.book.set_health(BookHealth.DISCONNECTED, error=str(exc))
            logger.warning("apex resync failed %s: %s", symbol, exc)


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


def _aggregate_lighter_orders(orders: object) -> list[list[str]]:
    if not isinstance(orders, list):
        return []
    buckets: dict[Decimal, Decimal] = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        try:
            px = Decimal(str(order.get("price") or order.get("px")))
            sz = Decimal(
                str(
                    order.get("remaining_base_amount")
                    or order.get("size")
                    or order.get("sz")
                    or "0"
                )
            )
        except Exception:  # noqa: BLE001
            continue
        if sz <= 0:
            continue
        buckets[px] = buckets.get(px, Decimal("0")) + sz
    return [[str(px), str(sz)] for px, sz in buckets.items()]


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
