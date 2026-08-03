"""Lighter adapter fixture tests (WHI-803) — per-order aggregation + rate limit."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import spread_compare.adapters  # noqa: F401
from spread_compare.adapters import get, list_venues
from spread_compare.adapters.perp_lighter import LighterAdapter
from spread_compare.models import ReferenceMid

_SAMPLES = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "samples"
    / "venue-api"
)

# WHI-799 §4.7 as per-order rows (multiple orders share a price → must aggregate).
_FIXTURE_ASK_ORDERS = [
    {"price": "100010", "remaining_base_amount": "0.02"},
    {"price": "100010", "remaining_base_amount": "0.02"},  # same level
    {"price": "100050", "remaining_base_amount": "0.04"},
    {"price": "100100", "remaining_base_amount": "0.10"},
]
_FIXTURE_BID_ORDERS = [
    {"price": "99990", "remaining_base_amount": "0.01"},
    {"price": "99990", "remaining_base_amount": "0.03"},
    {"price": "99950", "remaining_base_amount": "0.04"},
    {"price": "99900", "remaining_base_amount": "0.10"},
]


def _mid(asset: str = "BTC", price: str = "100000") -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="snap-lighter",
        asset=asset,
        mid=Decimal(price),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _details_payload() -> dict[str, Any]:
    return {
        "code": 200,
        "order_book_details": [
            {
                "symbol": "ETH",
                "market_id": 0,
                "mark_price": "3000",
                "index_price": "3001",
            },
            {
                "symbol": "BTC",
                "market_id": 1,
                "mark_price": "100050",
                "index_price": "100000",
            },
            {
                "symbol": "SOL",
                "market_id": 2,
                "mark_price": "150",
                "index_price": "150.1",
            },
        ],
    }


def _orders_payload(
    asks: list[dict[str, str]] | None = None,
    bids: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "code": 200,
        "asks": asks if asks is not None else _FIXTURE_ASK_ORDERS,
        "bids": bids if bids is not None else _FIXTURE_BID_ORDERS,
    }


class _CountingTransport:
    """Mock transport that counts orderBookOrders hits."""

    def __init__(
        self,
        *,
        asks: list[dict[str, str]] | None = None,
        bids: list[dict[str, str]] | None = None,
    ) -> None:
        self.order_requests = 0
        self.detail_requests = 0
        self._asks = asks
        self._bids = bids

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        if path.endswith("/orderBookDetails"):
            self.detail_requests += 1
            return httpx.Response(200, json=_details_payload())
        if path.endswith("/orderBookOrders"):
            self.order_requests += 1
            qs = parse_qs(urlparse(str(request.url)).query)
            assert qs.get("market_id") == ["1"] or qs.get("market_id")
            return httpx.Response(
                200, json=_orders_payload(asks=self._asks, bids=self._bids)
            )
        return httpx.Response(404, json={"error": path})


async def _ready_adapter(
    *,
    max_rpm: int = 60,
    window_s: float = 60.0,
    counter: _CountingTransport | None = None,
) -> tuple[LighterAdapter, _CountingTransport]:
    counter = counter or _CountingTransport()
    adapter = LighterAdapter(
        max_requests_per_minute=max_rpm,
        rate_window_s=window_s,
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(counter))
    await adapter.startup()
    return adapter, counter


def test_lighter_registered() -> None:
    assert "lighter" in list_venues()
    assert get("lighter").venue == "lighter"


def test_lighter_default_rate_budget_is_60_per_minute() -> None:
    """AC: Standard tier 60 req/min is the adapter default (not only test knobs)."""
    adapter = LighterAdapter()
    assert adapter._limiter.max_requests == 60
    assert adapter._limiter.window_s == 60.0


@pytest.mark.asyncio
async def test_lighter_market_id_resolved_from_details_not_hardcoded() -> None:
    adapter, _ = await _ready_adapter()
    try:
        assert adapter.market_id_for("BTC") == 1
        assert adapter.market_id_for("ETH") == 0
        assert adapter.market_id_for("SOL") == 2
        assert adapter.market_id_for("NOPE") is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_lighter_per_order_aggregation_section_4_7() -> None:
    """Orders at the same price must be summed before walk_book (WHI-803 AC)."""
    adapter, _ = await _ready_adapter()
    try:
        quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_mid())
        assert quote.status == "ok"
        assert quote.effective_price == Decimal("100044")
        assert quote.spread_bps == Decimal("4.4")
        # Standard account: 0 maker / 0 taker → total_cost = spread only.
        assert quote.total_cost_bps == Decimal("4.4")
        assert quote.fee_breakdown.trading_fee_bps == Decimal("0")
        assert quote.venue_symbol == "BTC"
        assert quote.venue_mark == Decimal("100050")
        assert quote.instrument_type == "perp"

        sell = await adapter.get_quote("BTC", "sell", Decimal("10000"), mid=_mid())
        assert sell.status == "ok"
        assert sell.effective_price == Decimal("99956")
        assert sell.spread_bps == Decimal("4.4")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_lighter_sample_orders_aggregate() -> None:
    sample = json.loads((_SAMPLES / "lighter-orderbook-orders-btc.json").read_text())
    counter = _CountingTransport(asks=sample["asks"], bids=sample["bids"])
    adapter, _ = await _ready_adapter(counter=counter)
    try:
        mid = _mid(price="62810")
        quote = await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=mid)
        # Sample depth is small; $1k may or may not fill — either ok or insufficient.
        assert quote.status in ("ok", "insufficient_liquidity")
        tob = await adapter.get_orderbook_spread("BTC", mid=mid)
        assert tob is not None
        # Best ask should be the min price after aggregation (62812.1 from sample).
        assert tob.best_ask == Decimal("62812.1")
        assert tob.ask_size == Decimal("0.00499") + Decimal("0.41253")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_lighter_rate_limit_burst_against_stub() -> None:
    """Adapter must stay within the configured rolling-window budget."""
    # 3 req / 0.5s window; 5 sequential order fetches must span ≥ one window.
    counter = _CountingTransport()
    adapter, _ = await _ready_adapter(max_rpm=3, window_s=0.5, counter=counter)
    try:
        t0 = time.monotonic()
        for _ in range(5):
            await adapter.get_orderbook_spread("BTC", mid=_mid())
        elapsed = time.monotonic() - t0
        assert counter.order_requests == 5
        # First 3 immediate; 4th waits for window; 5th may be immediate after 4th.
        assert elapsed >= 0.45
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_lighter_unsupported_without_market() -> None:
    adapter, _ = await _ready_adapter()
    try:
        quote = await adapter.get_quote("ZZZ", "buy", Decimal("1000"), mid=_mid("ZZZ"))
        assert quote.status == "unsupported_asset"
    finally:
        await adapter.aclose()
