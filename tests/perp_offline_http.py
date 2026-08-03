"""Offline MockTransport responses so registered perp adapters can startup().

Used by tests/conftest.py for non-live tests. Keeps startup_all() offline-safe
without silent production fallbacks.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

_HL_META: list[Any] = [
    {"universe": [{"name": "BTC"}, {"name": "ETH"}, {"name": "SOL"}]},
    [
        {"funding": "0.0000125", "markPx": "100000"},
        {"funding": "0.00001", "markPx": "3000"},
        {"funding": "0.00002", "markPx": "150"},
    ],
]

_HL_BOOK: dict[str, Any] = {
    "coin": "BTC",
    "time": 1,
    "levels": [
        [{"px": "99990", "sz": "1", "n": 1}],
        [{"px": "100010", "sz": "1", "n": 1}],
    ],
}

_LIGHTER_DETAILS: dict[str, Any] = {
    "code": 200,
    "order_book_details": [
        {"symbol": "ETH", "market_id": 0, "mark_price": "3000", "index_price": "3001"},
        {"symbol": "BTC", "market_id": 1, "mark_price": "100000", "index_price": "100000"},
        {"symbol": "SOL", "market_id": 2, "mark_price": "150", "index_price": "150"},
    ],
}

_LIGHTER_ORDERS: dict[str, Any] = {
    "code": 200,
    "asks": [{"price": "100010", "remaining_base_amount": "1"}],
    "bids": [{"price": "99990", "remaining_base_amount": "1"}],
}

_APEX_SYMBOLS: dict[str, Any] = {
    "data": {
        "contractConfig": {
            "perpetualContract": [
                {
                    "symbol": "BTC-USDT",
                    "crossSymbolName": "BTCUSDT",
                    "baseTokenId": "BTC",
                },
                {
                    "symbol": "ETH-USDT",
                    "crossSymbolName": "ETHUSDT",
                    "baseTokenId": "ETH",
                },
                {
                    "symbol": "SOL-USDT",
                    "crossSymbolName": "SOLUSDT",
                    "baseTokenId": "SOL",
                },
            ]
        }
    }
}

_APEX_DEPTH: dict[str, Any] = {
    "data": {
        "a": [["100010", "1"]],
        "b": [["99990", "1"]],
        "s": "BTCUSDT",
        "u": 1,
    }
}

_APEX_TICKER: dict[str, Any] = {
    "data": [
        {
            "symbol": "BTCUSDT",
            "fundingRate": "0.0000125",
            "markPrice": "100000",
        }
    ]
}


def hyperliquid_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content.decode()) if request.content else {}
    if body.get("type") == "metaAndAssetCtxs":
        return httpx.Response(200, json=_HL_META)
    if body.get("type") == "l2Book":
        return httpx.Response(200, json=_HL_BOOK)
    return httpx.Response(400, json={"error": body})


def lighter_handler(request: httpx.Request) -> httpx.Response:
    path = urlparse(str(request.url)).path
    if path.endswith("/orderBookDetails"):
        return httpx.Response(200, json=_LIGHTER_DETAILS)
    if path.endswith("/orderBookOrders"):
        return httpx.Response(200, json=_LIGHTER_ORDERS)
    return httpx.Response(404, json={"error": path})


def apex_handler(request: httpx.Request) -> httpx.Response:
    path = urlparse(str(request.url)).path
    qs = parse_qs(urlparse(str(request.url)).query)
    if path.endswith("/symbols"):
        return httpx.Response(200, json=_APEX_SYMBOLS)
    if path.endswith("/depth"):
        return httpx.Response(200, json=_APEX_DEPTH)
    if path.endswith("/ticker"):
        symbol = (qs.get("symbol") or ["BTCUSDT"])[0]
        body = {
            "data": [
                {
                    "symbol": symbol,
                    "fundingRate": "0.0000125",
                    "markPrice": "100000",
                }
            ]
        }
        return httpx.Response(200, json=body)
    return httpx.Response(404, json={"error": path})


def install_offline_clients() -> list[httpx.AsyncClient]:
    """Attach MockTransport clients to registered perp adapters. Returns clients to close."""
    from spread_compare.adapters.registry import _REGISTRY

    mapping = {
        "hyperliquid": hyperliquid_handler,
        "lighter": lighter_handler,
        "apex": apex_handler,
    }
    clients: list[httpx.AsyncClient] = []
    for slug, handler in mapping.items():
        adapter = _REGISTRY.get(slug)
        if adapter is None:
            continue
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        adapter._client = client  # type: ignore[attr-defined]
        # Force re-warm on next startup after a prior aclose_all().
        adapter._started = False  # type: ignore[attr-defined]
        clients.append(client)
    return clients
