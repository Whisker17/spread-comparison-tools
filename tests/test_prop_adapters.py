"""Unit tests for prop AMM adapters — Jupiter + KyberSwap (WHI-806)."""

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

import spread_compare.adapters  # noqa: F401 — ensure self-registration
from spread_compare.adapters import get, list_venues
from spread_compare.adapters.base import AdapterConfigError, AdapterError
from spread_compare.adapters.prop_jupiter import (
    HumidiFiAdapter,
    JupiterPropAdapter,
    _get_jupiter_limiter,
    _reset_jupiter_limiter_for_tests,
)
from spread_compare.adapters.prop_kyberswap import TesseraBaseAdapter, TesseraBscAdapter
from spread_compare.models import ReferenceMid
from tests.prop_offline_http import _PROGRAM_ID_TO_LABEL, install_offline_clients

_SAMPLES = Path(__file__).resolve().parents[1] / "docs" / "research" / "samples"

_PROP_SLUGS = (
    "humidifi",
    "tessera_solana",
    "bisonfi",
    "tessera_base",
    "tessera_bsc",
)


def _mid(asset: str, price: str) -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="snap-prop",
        asset=asset,
        mid=Decimal(price),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _load(name: str) -> dict[str, Any]:
    return json.loads((_SAMPLES / name).read_text(encoding="utf-8"))


def test_prop_venues_registered() -> None:
    venues = list_venues()
    for slug in _PROP_SLUGS:
        assert slug in venues, f"missing prop slug {slug}"
        adapter = get(slug)
        assert adapter.venue == slug
        assert adapter.venue_class == "prop_amm"


@pytest.mark.asyncio
async def test_orderbook_spread_is_none() -> None:
    install_offline_clients()
    for slug in _PROP_SLUGS:
        adapter = get(slug)
        await adapter.startup()
        try:
            assert await adapter.get_orderbook_spread("SOL", mid=_mid("SOL", "150")) is None
        finally:
            await adapter.aclose()


# ---------------------------------------------------------------------------
# Jupiter
# ---------------------------------------------------------------------------


def _jupiter_transport(
    *,
    quote_body: dict[str, Any] | None = None,
    quote_status: int = 200,
    label_map: dict[str, str] | None = None,
    call_log: list[float] | None = None,
    force_exclude_on_quote: bool = False,
) -> httpx.MockTransport:
    mapping = label_map if label_map is not None else dict(_PROGRAM_ID_TO_LABEL)
    body = quote_body

    def handler(request: httpx.Request) -> httpx.Response:
        if call_log is not None and request.url.path.endswith("/quote"):
            call_log.append(time.monotonic())
        if request.url.path.endswith("/program-id-to-label"):
            return httpx.Response(200, json=mapping)
        if request.url.path.endswith("/quote"):
            qs = parse_qs(urlparse(str(request.url)).query)
            if force_exclude_on_quote or (
                "excludeDexes" in qs and "dexes" in qs
            ):
                return httpx.Response(
                    400, json=_load("quote-dexes-and-exclude-same.json")
                )
            if body is not None:
                return httpx.Response(quote_status, json=body)
            return httpx.Response(200, json=_load("quote-humidifi-sol-usdc.json"))
        return httpx.Response(404, json={"error": "unexpected"})

    return httpx.MockTransport(handler)


async def _ready_jupiter(
    *,
    transport: httpx.MockTransport | None = None,
    adapter: JupiterPropAdapter | None = None,
) -> JupiterPropAdapter:
    inst = adapter or HumidiFiAdapter()
    inst._client = httpx.AsyncClient(
        transport=transport or _jupiter_transport()
    )
    await inst.startup()
    return inst


@pytest.mark.asyncio
async def test_jupiter_label_validation_fails_on_wrong_label() -> None:
    """Startup must fail fast when program_id no longer maps to the expected label."""
    bad_map = {
        "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp": "Tessera",  # wrong label
    }
    adapter = HumidiFiAdapter()
    adapter._client = httpx.AsyncClient(
        transport=_jupiter_transport(label_map=bad_map)
    )
    with pytest.raises(AdapterError, match="label validation failed"):
        await adapter.startup()
    await adapter.aclose()


@pytest.mark.asyncio
async def test_jupiter_no_routes_is_no_quote() -> None:
    adapter = await _ready_jupiter(
        transport=_jupiter_transport(
            quote_body=_load("quote-no-routes-wrong-label.json"),
            quote_status=400,
        )
    )
    try:
        quote = await adapter.get_quote("SOL", "sell", Decimal("1000"), mid=_mid("SOL", "150"))
        assert quote.status == "no_quote"
        assert quote.error_code == "NO_ROUTES_FOUND"
        assert quote.effective_price is None
        assert quote.total_cost_bps is None
        assert quote.qty_base is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_jupiter_dexes_and_exclude_raises_config_error() -> None:
    """400 'Cannot set dexes and exclude dexes…' must raise, not no_quote."""
    adapter = await _ready_jupiter()
    try:
        # Simulate the body Jupiter returns when both params are set.
        resp = httpx.Response(400, json=_load("quote-dexes-and-exclude-same.json"))
        with pytest.raises(AdapterConfigError, match="exclude"):
            adapter._handle_400(resp)

        # Also via forced transport path if excludeDexes sneaks into the request.
        adapter._client = httpx.AsyncClient(
            transport=_jupiter_transport(force_exclude_on_quote=True)
        )
        with pytest.raises(AdapterConfigError, match="exclude"):
            await adapter.get_quote("SOL", "sell", Decimal("1000"), mid=_mid("SOL", "150"))
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_jupiter_sell_ok_uses_out_amount() -> None:
    adapter = await _ready_jupiter()
    try:
        # Fixture: 1 SOL → 72.886151 USDC (outAmount=72886151, 6 dec).
        # Use notional such that qty_base raw ≈ 1e9 (1 SOL): notional = mid * 1.
        mid = _mid("SOL", "72.886151")
        quote = await adapter.get_quote("SOL", "sell", Decimal("72.886151"), mid=mid)
        assert quote.status == "ok"
        assert quote.venue == "humidifi"
        assert quote.instrument_type == "prop_amm"
        assert quote.qty_method == "base_from_mid"
        assert quote.fee_breakdown.embedded_in_price is True
        assert quote.fee_breakdown.platform_fee_bps == Decimal("0")
        assert quote.fee_breakdown.gas_unknown is False
        assert quote.fee_breakdown.gas_bps == Decimal("0")
        assert quote.total_cost_bps is not None
        assert quote.effective_price is not None
        # out/in ≈ 72.886151 USDC per SOL
        assert abs(quote.effective_price - Decimal("72.886151")) < Decimal("0.01")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_jupiter_buy_qty_method_is_quote_exact_in_approx() -> None:
    # Scale fixture amounts so ExactIn USDC → SOL returns a positive base.
    body = _load("quote-humidifi-sol-usdc.json")
    # Pretend we spent 1000 USDC and got ~13.72 SOL.
    body = {
        **body,
        "inputMint": body["outputMint"],
        "outputMint": body["inputMint"],
        "inAmount": "1000000000",  # 1000 USDC
        "outAmount": "13720000000",  # 13.72 SOL (9 dec)
    }
    adapter = await _ready_jupiter(transport=_jupiter_transport(quote_body=body))
    try:
        quote = await adapter.get_quote(
            "SOL", "buy", Decimal("1000"), mid=_mid("SOL", "72.88")
        )
        assert quote.status == "ok"
        assert quote.qty_method == "quote_exact_in_approx"
        assert quote.qty_base is not None
        assert quote.qty_base > 0
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_jupiter_keyless_respects_min_interval() -> None:
    """Shared limiter enforces ≥2s spacing when keyless (acceptance criterion)."""
    _reset_jupiter_limiter_for_tests()
    call_log: list[float] = []
    transport = _jupiter_transport(call_log=call_log)
    # Force keyless interval.
    limiter = await _get_jupiter_limiter(has_api_key=False)
    assert limiter._min_interval_s >= 2.0  # type: ignore[attr-defined]

    a1 = HumidiFiAdapter()
    a1._client = httpx.AsyncClient(transport=transport)
    a1._api_key = None
    # Skip real startup network by marking validated + started.
    a1._started = True
    a1._labels_validated = True

    try:
        t0 = time.monotonic()
        await a1._fetch_quote(
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            1_000_000_000,
        )
        await a1._fetch_quote(
            "So11111111111111111111111111111111111111112",
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            1_000_000_000,
        )
        elapsed = time.monotonic() - t0
        assert len(call_log) == 2
        spacing = call_log[1] - call_log[0]
        assert spacing >= 1.9, f"spacing {spacing:.3f}s < 2s"
        assert elapsed >= 1.9
    finally:
        await a1.aclose()
        _reset_jupiter_limiter_for_tests()


@pytest.mark.asyncio
async def test_jupiter_unsupported_asset() -> None:
    adapter = await _ready_jupiter()
    try:
        quote = await adapter.get_quote(
            "DOGE", "buy", Decimal("1000"), mid=_mid("DOGE", "0.1")
        )
        assert quote.status == "unsupported_asset"
    finally:
        await adapter.aclose()


# ---------------------------------------------------------------------------
# KyberSwap
# ---------------------------------------------------------------------------


def _kyber_transport(
    *,
    body: dict[str, Any] | None = None,
    chain: str = "base",
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if body is not None:
            return httpx.Response(200, json=body)
        if chain == "bsc" or "/bsc/" in request.url.path:
            return httpx.Response(200, json=_load("ks-route-tessera-bsc-btcb-usdt.json"))
        return httpx.Response(200, json=_load("ks-route-tessera-base-weth-usdc.json"))

    return httpx.MockTransport(handler)


async def _ready_kyber_base(
    *,
    transport: httpx.MockTransport | None = None,
) -> TesseraBaseAdapter:
    adapter = TesseraBaseAdapter()
    adapter._client = httpx.AsyncClient(transport=transport or _kyber_transport())
    await adapter.startup()
    return adapter


async def _ready_kyber_bsc(
    *,
    transport: httpx.MockTransport | None = None,
) -> TesseraBscAdapter:
    adapter = TesseraBscAdapter()
    adapter._client = httpx.AsyncClient(
        transport=transport or _kyber_transport(chain="bsc")
    )
    await adapter.startup()
    return adapter


def _kyber_scripted_transport(
    *,
    smoke_body: dict[str, Any],
    quote_body: dict[str, Any],
) -> httpx.MockTransport:
    """First successful routes call is smoke; subsequent use quote_body."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=smoke_body)
        return httpx.Response(200, json=quote_body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_kyber_4008_is_no_quote() -> None:
    adapter = await _ready_kyber_base(
        transport=_kyber_scripted_transport(
            smoke_body=_load("ks-route-tessera-base-weth-usdc.json"),
            quote_body=_load("ks-route-tessera-bsc-wbnb-usdt-noroute.json"),
        )
    )
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_mid("ETH", "3000"))
        assert quote.status == "no_quote"
        assert quote.error_code == "4008"
        assert quote.effective_price is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_kyber_40011_raises_config_error() -> None:
    adapter = await _ready_kyber_base(
        transport=_kyber_scripted_transport(
            smoke_body=_load("ks-route-tessera-base-weth-usdc.json"),
            quote_body=_load("ks-route-wrong-source-id.json"),
        )
    )
    try:
        with pytest.raises(AdapterConfigError, match="40011"):
            await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_mid("ETH", "3000"))
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_kyber_base_ok_with_gas_from_response() -> None:
    adapter = await _ready_kyber_base()
    try:
        # Sample: 1 WETH → ~1855.68 USDC. mid ≈ that so spread is small.
        mid = _mid("ETH", "1855.68")
        quote = await adapter.get_quote("ETH", "sell", mid.mid, mid=mid)
        assert quote.status == "ok"
        assert quote.venue == "tessera_base"
        assert quote.fee_breakdown.gas_unknown is False
        assert quote.fee_breakdown.gas_usd is not None
        assert quote.fee_breakdown.gas_usd > 0
        assert quote.fee_breakdown.gas_bps is not None
        assert quote.total_cost_bps is not None
        assert quote.qty_method == "base_from_mid"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_kyber_bsc_btcb_ok() -> None:
    adapter = await _ready_kyber_bsc()
    try:
        mid = _mid("BTC", "62765")
        quote = await adapter.get_quote("BTC", "sell", Decimal("1000"), mid=mid)
        assert quote.status == "ok"
        assert quote.venue == "tessera_bsc"
        assert quote.venue_symbol == "BTCB/USDT"
        assert quote.fee_breakdown.gas_usd is not None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_kyber_bsc_qqqb_returns_valid_quote() -> None:
    """BSC tokenized-stock pair QQQB/USDT via tessera_bsc (acceptance criterion)."""
    sample = _load("ks-route-tessera-bsc-usdt-qqqb.json")
    # For sell of QQQB we need amountIn=QQQB, amountOut=USDT — synthesize from sample.
    # Use buy path (USDT ExactIn → QQQB) which matches the sample direction.
    adapter = TesseraBscAdapter()
    adapter._client = httpx.AsyncClient(
        transport=_kyber_transport(body=sample, chain="bsc")
    )
    # Mark started without re-running smoke against QQQB body.
    adapter._started = True
    adapter._smoke_ok = True
    try:
        # mid ~ QQQB price ≈ 693 from sample (2000 USDT → 2.882 QQQB).
        mid = _mid("QQQB", "693.5")
        quote = await adapter.get_quote("QQQB", "buy", Decimal("2000"), mid=mid)
        assert quote.status == "ok"
        assert quote.venue == "tessera_bsc"
        assert quote.qty_method == "quote_exact_in_approx"
        assert quote.qty_base is not None
        assert quote.effective_price is not None
        assert quote.total_cost_bps is not None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_no_bps_arithmetic_in_prop_modules() -> None:
    """Guard: prop modules must not recompute bps outside costs.py."""
    adapters_dir = Path(__file__).resolve().parents[1] / "spread_compare" / "adapters"
    forbidden = (
        "* 10000",
        "* Decimal(\"10000\")",
        "/ mid *",
    )
    for path in list(adapters_dir.glob("prop_*.py")) + [adapters_dir / "_prop_common.py"]:
        text = path.read_text(encoding="utf-8")
        # Allow imports of costs helpers only.
        for needle in forbidden:
            # Crude scan — ensure raw bps math isn't hand-rolled.
            if needle in text and "costs" not in path.name:
                # Only flag if not inside a comment about the formula.
                lines = [
                    ln
                    for ln in text.splitlines()
                    if needle in ln and not ln.strip().startswith("#")
                ]
                assert not lines, f"{path.name} has hand-rolled bps: {lines}"
