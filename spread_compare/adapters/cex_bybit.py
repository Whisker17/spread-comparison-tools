"""Bybit CEX adapter: spot + linear perp orderbook → Quote (WHI-802).

Endpoints: WHI-800 §3.2. Symbol map: WHI-798 §3.3 via ``cex_symbols``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from spread_compare.adapters._cex_common import (
    CexBaseAdapter,
    CexBookSide,
    OrderbookLevels,
    parse_levels,
)
from spread_compare.adapters.base import AdapterError, AdapterFetchError
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import InstrumentType, Side

_BASE = "https://api.bybit.com"
# WHI-802: default limit=200. Tunables deferred — docs/DEFERRED_ISSUES.md (WHI-802).
_ORDERBOOK_LIMIT = 200
# bStocks (*B) are Binance-only; Bybit uses *X xStocks (out of Phase 1 — WHI-798 §4.3).
_BYBIT_NO_SPOT: frozenset[str] = frozenset({"QQQB", "SPCXB", "NVDAB"})


@register_adapter
class BybitAdapter(CexBaseAdapter):
    """Bybit spot + linear perpetual orderbook walker."""

    venue: str = "bybit"
    # Well under Bybit IP 600 req / 5s (~120 rps): ~10 rps.
    _min_interval_s: float = 0.1
    _retry_http_statuses: frozenset[int] = frozenset({403, 429})
    _rate_limit_log_headers: tuple[str, ...] = (
        "X-Bapi-Limit-Status",
        "x-bapi-limit-status",
    )

    def _venue_lists_asset(
        self,
        asset: str,
        instrument_type: InstrumentType | CexBookSide | None,
    ) -> bool:
        if asset.upper() in _BYBIT_NO_SPOT and instrument_type in (None, "spot"):
            return False
        return True

    async def _fetch_book(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        side: Side | None = None,
        q_star: Decimal | None = None,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        _ = side, q_star  # Bybit Phase 1: fixed depth 200 (no escalation in WHI-802)

        async def _raw() -> tuple[OrderbookLevels, OrderbookLevels]:
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
                raise AdapterFetchError(
                    f"bybit orderbook parse failed: {exc}"
                ) from exc
            return bids, asks

        snap = await self._cached_depth_fetch(
            symbol, book_side, depth=_ORDERBOOK_LIMIT, fetch=_raw
        )
        return snap.bids, snap.asks

    def _payload_is_rate_limited(self, payload: dict[str, Any]) -> bool:
        return payload.get("retCode") == 10006

    def _validate_success_payload(self, payload: dict[str, Any]) -> None:
        ret_code = payload.get("retCode")
        if ret_code not in (0, None):
            raise AdapterFetchError(
                f"bybit retCode={ret_code} retMsg={payload.get('retMsg')!r}"
            )
