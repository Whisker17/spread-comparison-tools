"""Bybit CEX adapter: spot + linear perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.2. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

import httpx

from spread_compare.adapters._cex_common import (
    CexBaseAdapter,
    CexBookSide,
    OrderbookLevels,
    parse_levels,
)
from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    AdapterTimeoutError,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import Side

logger = logging.getLogger(__name__)

_BASE = "https://api.bybit.com"
# WHI-802: default limit=200. Tunables deferred — docs/DEFERRED_ISSUES.md (WHI-802).
_ORDERBOOK_LIMIT = 200
_MAX_RETRIES = 4
_BACKOFF_START_S = 0.5


@register_adapter
class BybitAdapter(CexBaseAdapter):
    """Bybit spot + linear perpetual orderbook walker."""

    venue: str = "bybit"
    # Well under Bybit IP 600 req / 5s (~120 rps): ~10 rps.
    _min_interval_s: float = 0.1

    async def _fetch_book(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        side: Side | None = None,
        q_star: Decimal | None = None,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        _ = side, q_star  # Bybit Phase 1: fixed depth 200 (no escalation in WHI-802)
        category = "spot" if book_side == "spot" else "linear"
        url = f"{_BASE}/v5/market/orderbook"
        params = {
            "category": category,
            "symbol": symbol,
            "limit": str(_ORDERBOOK_LIMIT),
        }
        data = await self._request_json(url, params)
        try:
            result = data["result"]
            # Bybit: result.a = asks, result.b = bids as [px, sz] string arrays.
            asks = parse_levels(result["a"])
            bids = parse_levels(result["b"])
        except (KeyError, TypeError, AdapterError) as exc:
            raise AdapterFetchError(f"bybit orderbook parse failed: {exc}") from exc
        return bids, asks

    async def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        delay = _BACKOFF_START_S
        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await self._limiter.acquire()
            try:
                resp = await self.http.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"bybit timeout: {url}") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"bybit HTTP error: {exc}") from exc

            limit_status = resp.headers.get("X-Bapi-Limit-Status") or resp.headers.get(
                "x-bapi-limit-status"
            )
            if limit_status is not None:
                logger.info("bybit X-Bapi-Limit-Status=%s url=%s", limit_status, url)

            # IP throttle often returns 403; UID market-data may use retCode 10006.
            if resp.status_code in (403, 429):
                last_error = AdapterFetchError(
                    f"bybit rate limited (HTTP {resp.status_code}) attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"bybit HTTP {resp.status_code}: {resp.text[:200]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise AdapterFetchError("bybit response is not JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterFetchError(f"bybit unexpected JSON type: {type(payload)}")

            ret_code = payload.get("retCode")
            if ret_code == 10006:
                last_error = AdapterFetchError(
                    f"bybit retCode=10006 (too many visits) attempt={attempt + 1}"
                )
                logger.warning("%s; sleeping %.2fs", last_error, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            if ret_code not in (0, None):
                raise AdapterFetchError(
                    f"bybit retCode={ret_code} retMsg={payload.get('retMsg')!r}"
                )
            return payload

        assert last_error is not None
        raise last_error
