"""ApeX adapter fixture tests (WHI-803) — crossSymbolName resolution."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

import spread_compare.adapters  # noqa: F401
from spread_compare.adapters import get, list_venues
from spread_compare.adapters.perp_apex import ApexAdapter
from spread_compare.models import ReferenceMid

_SAMPLES = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "samples"
    / "venue-api"
)

# WHI-799 §4.7 as ApeX [price, size] arrays.
_FIXTURE_ASKS = [
    ["100010", "0.04"],
    ["100050", "0.04"],
    ["100100", "0.10"],
]
_FIXTURE_BIDS = [
    ["99990", "0.04"],
    ["99950", "0.04"],
    ["99900", "0.10"],
]


def _mid(asset: str = "BTC", price: str = "100000") -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="snap-apex",
        asset=asset,
        mid=Decimal(price),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _symbols_payload() -> dict[str, Any]:
    return {
        "data": {
            "contractConfig": {
                "perpetualContract": [
                    {
                        "symbol": "BTC-USDT",
                        "crossSymbolName": "BTCUSDT",
                        "baseTokenId": "BTC",
                        "tokenName": "Bitcoin",
                    },
                    {
                        "symbol": "ETH-USDT",
                        "crossSymbolName": "ETHUSDT",
                        "baseTokenId": "ETH",
                        "tokenName": "Ethereum",
                    },
                    {
                        "symbol": "SOL-USDT",
                        "crossSymbolName": "SOLUSDT",
                        "baseTokenId": "SOL",
                        "tokenName": "Solana",
                    },
                ]
            }
        }
    }


def _depth_payload(
    symbol: str,
    asks: list[list[str]] | None = None,
    bids: list[list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "data": {
            "a": asks if asks is not None else _FIXTURE_ASKS,
            "b": bids if bids is not None else _FIXTURE_BIDS,
            "s": symbol,
            "u": 1,
        },
        "timeCost": 1,
    }


def _null_depth_payload() -> dict[str, Any]:
    return {"data": {"a": None, "b": None, "s": None, "u": None}, "timeCost": 1}


def _ticker_payload(symbol: str) -> dict[str, Any]:
    return {
        "data": [
            {
                "symbol": symbol,
                "fundingRate": "0.0000125",
                "markPrice": "100050",
                "indexPrice": "100000",
            }
        ]
    }


class _ApexTransport:
    def __init__(
        self,
        *,
        asks: list[list[str]] | None = None,
        bids: list[list[str]] | None = None,
    ) -> None:
        self.depth_symbols: list[str] = []
        self._asks = asks
        self._bids = bids

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = urlparse(str(request.url)).path
        qs = parse_qs(urlparse(str(request.url)).query)
        if path.endswith("/symbols"):
            return httpx.Response(200, json=_symbols_payload())
        if path.endswith("/depth"):
            symbol = (qs.get("symbol") or [""])[0]
            self.depth_symbols.append(symbol)
            # Wrong form (hyphenated config symbol) → null books (live trap).
            if "-" in symbol:
                return httpx.Response(200, json=_null_depth_payload())
            return httpx.Response(
                200,
                json=_depth_payload(symbol, asks=self._asks, bids=self._bids),
            )
        if path.endswith("/ticker"):
            symbol = (qs.get("symbol") or [""])[0]
            return httpx.Response(200, json=_ticker_payload(symbol))
        return httpx.Response(404, json={"error": path})


async def _ready_adapter(
    transport: _ApexTransport | None = None,
) -> tuple[ApexAdapter, _ApexTransport]:
    transport = transport or _ApexTransport()
    adapter = ApexAdapter()
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    await adapter.startup()
    return adapter, transport


def test_apex_registered() -> None:
    assert "apex" in list_venues()
    assert get("apex").venue == "apex"


@pytest.mark.asyncio
async def test_apex_resolves_cross_symbol_from_symbols_endpoint() -> None:
    """BTC → BTCUSDT (not BTC-USDT); mapping comes from /v3/symbols."""
    adapter, _ = await _ready_adapter()
    try:
        assert adapter.cross_symbol_for("BTC") == "BTCUSDT"
        assert adapter.config_symbol_for("BTC") == "BTC-USDT"
        assert adapter.cross_symbol_for("ETH") == "ETHUSDT"
        assert adapter.cross_symbol_for("SOL") == "SOLUSDT"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_apex_depth_uses_cross_symbol_not_hyphenated() -> None:
    adapter, transport = await _ready_adapter()
    try:
        quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_mid())
        assert quote.status == "ok"
        assert quote.venue_symbol == "BTCUSDT"
        assert transport.depth_symbols
        assert all(s == "BTCUSDT" for s in transport.depth_symbols)
        assert all("-" not in s for s in transport.depth_symbols)
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_apex_section_4_7_vectors() -> None:
    adapter, _ = await _ready_adapter()
    try:
        buy = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_mid())
        sell = await adapter.get_quote("BTC", "sell", Decimal("10000"), mid=_mid())
        assert buy.status == "ok"
        assert buy.effective_price == Decimal("100044")
        assert buy.spread_bps == Decimal("4.4")
        assert buy.total_cost_bps == Decimal("14.4")
        # fundingRate hourly 0.0000125 → funding_rate_8h = 0.0001 (WHI-799 §5.3)
        assert buy.fee_breakdown.funding_rate_8h == Decimal("0.0001")
        assert buy.venue_mark == Decimal("100050")
        assert sell.status == "ok"
        assert sell.effective_price == Decimal("99956")
        assert sell.spread_bps == Decimal("4.4")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_apex_top_of_book() -> None:
    adapter, _ = await _ready_adapter()
    try:
        tob = await adapter.get_orderbook_spread("BTC", mid=_mid())
        assert tob is not None
        assert tob.best_bid == Decimal("99990")
        assert tob.best_ask == Decimal("100010")
        assert tob.instrument_type == "perp"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_apex_sample_depth_parses() -> None:
    sample = json.loads((_SAMPLES / "apex-depth-btcusdt.json").read_text())
    asks = sample["data"]["a"]
    bids = sample["data"]["b"]
    transport = _ApexTransport(asks=asks, bids=bids)
    adapter, _ = await _ready_adapter(transport)
    try:
        mid = _mid(price="62817")
        quote = await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=mid)
        assert quote.status == "ok"
        tob = await adapter.get_orderbook_spread("BTC", mid=mid)
        assert tob is not None
        assert tob.best_ask == Decimal("62817.4")
        assert tob.best_bid == Decimal("62816.8")
    finally:
        await adapter.aclose()
