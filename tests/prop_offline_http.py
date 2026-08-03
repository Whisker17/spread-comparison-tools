"""Offline MockTransport responses so registered prop adapters can startup().

Used by tests/conftest.py for non-live tests. Jupiter label map + KyberSwap
smoke pairs are stubbed so startup never hits the public network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from spread_compare.adapters.base import BaseAdapter
from spread_compare.adapters.registry import _REGISTRY

_SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "research" / "samples"

_PROGRAM_ID_TO_LABEL: dict[str, str] = {
    "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp": "HumidiFi",
    "TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH": "TesseraV",
    "BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi": "BisonFi",
    # Extra label seen in live map (not a baseline venue).
    "2DNbzPochEcyCcWMbL4d9S3u9QqQEj5bbe6cSZFvKsbh": "BisonFi Predict",
}


def _load_sample(name: str) -> dict[str, Any]:
    path = _SAMPLES / name
    return json.loads(path.read_text(encoding="utf-8"))


def _jupiter_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/program-id-to-label"):
        return httpx.Response(200, json=_PROGRAM_ID_TO_LABEL)

    if path.endswith("/quote"):
        qs = parse_qs(urlparse(str(request.url)).query)
        # Config-error branch used by unit tests that force excludeDexes.
        if "excludeDexes" in qs and "dexes" in qs:
            return httpx.Response(
                400,
                json=_load_sample("quote-dexes-and-exclude-same.json"),
            )
        dexes = (qs.get("dexes") or [""])[0]
        if dexes not in ("HumidiFi", "TesseraV", "BisonFi"):
            return httpx.Response(
                400,
                json=_load_sample("quote-no-routes-wrong-label.json"),
            )
        sample_name = {
            "HumidiFi": "quote-humidifi-sol-usdc.json",
            "TesseraV": "quote-tesserav-sol-usdc.json",
            "BisonFi": "quote-bisonfi-sol-usdc.json",
        }[dexes]
        return httpx.Response(200, json=_load_sample(sample_name))

    return httpx.Response(404, json={"error": f"unexpected path {path}"})


def _kyber_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    qs = parse_qs(urlparse(str(request.url)).query)
    sources = (qs.get("includedSources") or [""])[0].lower()
    if sources and sources != "tessera":
        return httpx.Response(200, json=_load_sample("ks-route-wrong-source-id.json"))

    if "/base/" in path:
        return httpx.Response(
            200, json=_load_sample("ks-route-tessera-base-weth-usdc.json")
        )
    if "/bsc/" in path:
        token_out = (qs.get("tokenOut") or [""])[0].lower()
        # QQQB token (sample is USDT → QQQB).
        if token_out == "0x205812cdbed920aff76c6580abd681a46d11efc7":
            return httpx.Response(
                200, json=_load_sample("ks-route-tessera-bsc-usdt-qqqb.json")
            )
        # WBNB-style noroute for unsupported pairs (tokenOut not in known set).
        # Default smoke + BTCB use the BTCB sample.
        return httpx.Response(
            200, json=_load_sample("ks-route-tessera-bsc-btcb-usdt.json")
        )
    return httpx.Response(404, json={"error": f"unexpected path {path}"})


def _prop_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host or ""
        if "jup.ag" in host:
            return _jupiter_handler(request)
        if "kyberswap.com" in host:
            return _kyber_handler(request)
        return httpx.Response(404, json={"error": f"unexpected host {host}"})

    return httpx.MockTransport(handler)


def install_offline_clients() -> list[httpx.AsyncClient]:
    """Attach MockTransport clients to registered prop adapters.

    Returns clients the caller must aclose.
    """
    transport = _prop_transport()
    clients: list[httpx.AsyncClient] = []
    prop_slugs = {
        "humidifi",
        "tessera_solana",
        "bisonfi",
        "tessera_base",
        "tessera_bsc",
    }
    for slug, adapter in _REGISTRY.items():
        if slug not in prop_slugs:
            continue
        if not isinstance(adapter, BaseAdapter):
            continue
        client = httpx.AsyncClient(transport=transport)
        adapter._client = client
        clients.append(client)
    return clients
