"""Hyperliquid adapter fixture tests (WHI-803)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

import spread_compare.adapters  # noqa: F401 — ensure self-registration
from spread_compare.adapters import get, list_venues
from spread_compare.adapters.perp_hyperliquid import HyperliquidAdapter
from spread_compare.models import ReferenceMid

_SAMPLES = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "samples"
    / "venue-api"
)

# WHI-799 §4.7 book encoded as HL {px, sz, n} levels.
_FIXTURE_BIDS = [
    {"px": "99990", "sz": "0.04", "n": 1},
    {"px": "99950", "sz": "0.04", "n": 1},
    {"px": "99900", "sz": "0.10", "n": 1},
]
_FIXTURE_ASKS = [
    {"px": "100010", "sz": "0.04", "n": 1},
    {"px": "100050", "sz": "0.04", "n": 1},
    {"px": "100100", "sz": "0.10", "n": 1},
]

# 20-level thin book: total size per side = 0.20 BTC → $1M walk fails at mid=100k.
_THIN_LEVEL = {"px": "100000", "sz": "0.01", "n": 1}
_THIN_BIDS = [{**_THIN_LEVEL, "px": str(99990 - i)} for i in range(20)]
_THIN_ASKS = [{**_THIN_LEVEL, "px": str(100010 + i)} for i in range(20)]


def _mid(asset: str = "BTC", price: str = "100000") -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="snap-hl",
        asset=asset,
        mid=Decimal(price),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )


def _meta_payload_main() -> list[Any]:
    return [
        {
            "universe": [
                {"name": "BTC"},
                {"name": "ETH"},
                {"name": "SOL"},
                {"name": "DOGE"},
                {"name": "kPEPE"},
            ]
        },
        [
            {"funding": "0.0000125", "markPx": "100050"},
            {"funding": "0.00001", "markPx": "3000"},
            {"funding": "0.00002", "markPx": "150"},
            {"funding": "0.00003", "markPx": "0.15"},
            {"funding": "0.00004", "markPx": "0.01"},
        ],
    ]


def _meta_payload_xyz() -> list[Any]:
    return [
        {
            "universe": [
                {"name": "TSLA"},
                {"name": "NVDA"},
                {"name": "AAPL"},
                {"name": "MSFT"},
            ]
        },
        [
            {"funding": "0.00001", "markPx": "250"},
            {"funding": "0.00001", "markPx": "120"},
            {"funding": "0.00001", "markPx": "200"},
            {"funding": "0.00001", "markPx": "400"},
        ],
    ]


def _transport(
    *,
    book_levels: list[list[dict[str, object]]] | None = None,
) -> httpx.MockTransport:
    levels = book_levels or [_FIXTURE_BIDS, _FIXTURE_ASKS]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content.decode())
        if body.get("type") == "metaAndAssetCtxs":
            if body.get("dex") == "xyz":
                return httpx.Response(200, json=_meta_payload_xyz())
            return httpx.Response(200, json=_meta_payload_main())
        if body.get("type") == "l2Book":
            return httpx.Response(
                200,
                json={
                    "coin": body.get("coin"),
                    "time": 1,
                    "levels": levels,
                },
            )
        return httpx.Response(400, json={"error": f"unexpected body {body}"})

    return httpx.MockTransport(handler)


async def _ready_adapter(
    book_levels: list[list[dict[str, object]]] | None = None,
) -> HyperliquidAdapter:
    adapter = HyperliquidAdapter()
    adapter._client = httpx.AsyncClient(transport=_transport(book_levels=book_levels))
    await adapter.startup()
    return adapter


def test_hyperliquid_registered() -> None:
    assert "hyperliquid" in list_venues()
    assert get("hyperliquid").venue == "hyperliquid"


@pytest.mark.asyncio
async def test_hl_section_4_7_buy_vector() -> None:
    adapter = await _ready_adapter()
    try:
        quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_mid())
        assert quote.status == "ok"
        assert quote.venue == "hyperliquid"
        assert quote.instrument_type == "perp"
        assert quote.effective_price == Decimal("100044")
        assert quote.spread_bps == Decimal("4.4")
        # spread 4.4 + HL Tier-0 taker 4.5
        assert quote.total_cost_bps == Decimal("8.9")
        assert quote.fee_breakdown.trading_fee_bps == Decimal("4.5")
        assert quote.fee_breakdown.funding_rate_8h == Decimal("0.0001")  # 0.0000125 * 8
        assert quote.venue_mark == Decimal("100050")
        assert quote.basis_bps == Decimal("5")  # (100050-100000)/100000*10000
        assert quote.fee_breakdown.gas_bps == Decimal("0")
        assert quote.fee_breakdown.embedded_in_price is False
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_section_4_7_sell_vector() -> None:
    adapter = await _ready_adapter()
    try:
        quote = await adapter.get_quote("BTC", "sell", Decimal("10000"), mid=_mid())
        assert quote.status == "ok"
        assert quote.effective_price == Decimal("99956")
        assert quote.spread_bps == Decimal("4.4")
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_one_million_walk_insufficient_on_20_level_thin_book() -> None:
    adapter = await _ready_adapter(book_levels=[_THIN_BIDS, _THIN_ASKS])
    try:
        quote = await adapter.get_quote(
            "BTC", "buy", Decimal("1000000"), mid=_mid()
        )
        assert quote.status == "insufficient_liquidity"
        assert quote.error_code == "insufficient_liquidity"
        assert quote.effective_price is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_hard_caps_levels_at_20_per_side() -> None:
    """WHI-800 §4.1: at most 20 levels/side even if the payload is longer."""
    fat_bids = [{**_THIN_LEVEL, "px": str(99990 - i)} for i in range(25)]
    fat_asks = [{**_THIN_LEVEL, "px": str(100010 + i)} for i in range(25)]
    adapter = await _ready_adapter(book_levels=[fat_bids, fat_asks])
    try:
        bids, asks, _from_ws, _age = await adapter._fetch_l2_book("BTC")
        assert len(bids) == 20
        assert len(asks) == 20
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_top_of_book() -> None:
    adapter = await _ready_adapter()
    try:
        tob = await adapter.get_orderbook_spread("BTC", mid=_mid())
        assert tob is not None
        assert tob.best_bid == Decimal("99990")
        assert tob.best_ask == Decimal("100010")
        assert tob.instrument_type == "perp"
        assert tob.venue == "hyperliquid"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_sample_file_parses() -> None:
    sample = json.loads((_SAMPLES / "hyperliquid-l2book-btc.json").read_text())
    levels = sample["levels"]
    adapter = await _ready_adapter(book_levels=levels)
    try:
        # mid near sample TOB so small notional walks.
        mid = _mid(price="62824.5")
        quote = await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=mid)
        assert quote.status == "ok"
        assert quote.effective_price is not None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_startup_idempotent() -> None:
    adapter = await _ready_adapter()
    try:
        await adapter.startup()  # second call is no-op
        assert "BTC" in adapter.supported_assets()
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_xyz_equity_perp_resolves() -> None:
    """WHI-826: TSLA → xyz:TSLA with HIP-3 meta loaded."""
    # Book sized for equity mid (~250) so q_star fits fixture depth.
    eq_bids = [
        {"px": "249.90", "sz": "40", "n": 1},
        {"px": "249.50", "sz": "40", "n": 1},
    ]
    eq_asks = [
        {"px": "250.10", "sz": "40", "n": 1},
        {"px": "250.50", "sz": "40", "n": 1},
    ]
    adapter = await _ready_adapter(book_levels=[eq_bids, eq_asks])
    try:
        assert "TSLA" in adapter.supported_assets()
        quote = await adapter.get_quote(
            "TSLA", "buy", Decimal("1000"), mid=_mid("TSLA", "250")
        )
        assert quote.status == "ok"
        assert quote.asset == "TSLA"
        assert quote.venue_symbol == "xyz:TSLA"
        assert quote.instrument_type == "perp"
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_hl_kpepe_multiplier_normalizes() -> None:
    """kPEPE book prices are 1000×; spread matches 1× mid after scale."""
    # Contract book around 0.01 with mid 0.00001 (1× PEPE).
    k_bids = [
        {"px": "0.009999", "sz": "500000", "n": 1},
        {"px": "0.009995", "sz": "500000", "n": 1},
    ]
    k_asks = [
        {"px": "0.010001", "sz": "500000", "n": 1},
        {"px": "0.010005", "sz": "500000", "n": 1},
    ]
    adapter = await _ready_adapter(book_levels=[k_bids, k_asks])
    try:
        mid = _mid("PEPE", "0.00001")
        quote = await adapter.get_quote(
            "PEPE", "buy", Decimal("10000"), mid=mid
        )
        assert quote.status == "ok"
        assert quote.venue_symbol == "kPEPE"
        assert quote.effective_price is not None
        # Effective should be near 1× mid, not near 0.01.
        assert quote.effective_price < Decimal("0.0001")
        assert quote.spread_bps is not None
        assert quote.spread_bps < Decimal("1000")
    finally:
        await adapter.aclose()
