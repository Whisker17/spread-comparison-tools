"""Fast mid path for WS-served quotes (WHI-847).

Polls Binance USDM ``GET /fapi/v1/premiumIndex`` at ~1 Hz (verified live;
markPrice WS delivered no messages). Seeds :class:`MidService` cache so
WS books are not priced against a 30 s-stale mid.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

import httpx

from spread_compare.cex_symbols import resolve_cex_multiplier, resolve_cex_symbol
from spread_compare.mids import MidService
from spread_compare.settings import MidSettings, WsSettings, load_mid_settings, load_ws_settings

logger = logging.getLogger(__name__)

_BINANCE_FAPI = "https://fapi.binance.com"


class FastMidPoller:
    """Background ~1 Hz premiumIndex poller for a set of logical assets."""

    def __init__(
        self,
        mid_service: MidService,
        assets: Sequence[str],
        *,
        ws_settings: WsSettings | None = None,
        mid_settings: MidSettings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._mid = mid_service
        self._assets = [a.upper() for a in assets]
        self._ws = ws_settings if ws_settings is not None else load_ws_settings()
        self._mid_settings = mid_settings if mid_settings is not None else load_mid_settings()
        self._client = client
        self._owns_client = client is None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._ws.enabled or not self._assets:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="fast-mid-poller")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._mid_settings.http_timeout_sec)
        return self._client

    async def _run(self) -> None:
        interval = self._ws.fast_mid_poll_interval_sec
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001
                logger.exception("fast mid poll failed")
            elapsed = time.monotonic() - started
            wait = max(0.0, interval - elapsed)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
                break
            except TimeoutError:
                continue

    async def poll_once(self) -> int:
        """Fetch premiumIndex for configured assets. Returns success count."""
        ok = 0
        for asset in self._assets:
            symbol = resolve_cex_symbol(asset, "perp")
            if symbol is None:
                # Spot-only assets: skip (crypto chain falls back elsewhere).
                continue
            mult = resolve_cex_multiplier(asset, "perp")
            try:
                resp = await self._http().get(
                    f"{_BINANCE_FAPI}/fapi/v1/premiumIndex",
                    params={"symbol": symbol},
                )
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                raw = data.get("indexPrice") or data.get("markPrice")
                if raw is None:
                    continue
                price = Decimal(str(raw))
                if price <= 0:
                    continue
                if mult != 1:
                    price = price / mult
                ts_raw = data.get("time")
                if ts_raw is not None:
                    ts = datetime.fromtimestamp(int(ts_raw) / 1000, tz=UTC)
                else:
                    ts = datetime.now(tz=UTC)
                self._mid.seed_cache(
                    asset,
                    mid=price,
                    mid_source="binance_usdm_index",
                    timestamp=ts,
                )
                ok += 1
            except (httpx.HTTPError, InvalidOperation, TypeError, ValueError, OSError) as exc:
                logger.debug("fast mid %s failed: %s", asset, exc)
        return ok
