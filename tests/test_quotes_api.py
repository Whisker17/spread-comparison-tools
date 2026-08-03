"""HTTP API tests for /quotes, /venues, /assets, /fees."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from spread_compare.api.app import create_app
from spread_compare.mids import MidResolutionError
from spread_compare.models import ReferenceMid


@pytest.fixture
def client() -> Any:
    with TestClient(create_app()) as c:
        yield c


def test_get_venues(client: TestClient) -> None:
    resp = client.get("/venues")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 13  # WHI-799 §6.5 + mock
    by_slug = {r["slug"]: r for r in rows}
    assert "binance" in by_slug
    assert by_slug["binance"]["display_name"] == "Binance"
    assert by_slug["binance"]["venue_class"] == "cex"
    assert "chain" in by_slug["binance"]
    assert by_slug["uniswap_eth"]["chain"] == "ethereum"
    assert by_slug["mock"]["adapter_registered"] is True


def test_get_assets(client: TestClient) -> None:
    resp = client.get("/assets")
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["id"] for r in rows}
    assert ids == {"BTC", "ETH", "SOL"}
    btc = next(r for r in rows if r["id"] == "BTC")
    assert btc["category"] == "crypto_blue_chip"
    assert btc["representations"]["binance"] == "BTCUSDT"
    assert btc["representations"]["uniswap_eth"] == "WBTC"
    assert btc["representations"]["humidifi"] == "cbBTC"


def test_get_fees(client: TestClient) -> None:
    resp = client.get("/fees")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    by_key = {(r["venue"], r["instrument_type"]): r for r in rows}
    assert ("binance", "spot") in by_key
    assert ("binance", "perp") in by_key
    assert ("hyperliquid", "perp") in by_key
    assert ("uniswap_eth", "amm_pool") in by_key
    assert ("humidifi", "prop_amm") in by_key
    bn_spot = by_key[("binance", "spot")]
    assert Decimal(bn_spot["taker_bps"]) == Decimal("10")
    assert bn_spot["source_urls"]
    assert bn_spot["updated_at"]
    hl = by_key[("hyperliquid", "perp")]
    assert Decimal(hl["taker_bps"]) == Decimal("4.5")
    assert hl["funding_model"] == "perp_continuous"
    prop = by_key[("humidifi", "prop_amm")]
    assert prop["fee_embedded_in_quote"] is True
    assert prop["taker_bps"] is None


def test_quotes_happy_path_with_injected_mid(client: TestClient) -> None:
    mid = ReferenceMid(
        snapshot_id="will-be-overwritten",
        asset="BTC",
        mid=Decimal("100000"),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )

    async def fake_resolve(asset: str, *, snapshot_id: str) -> ReferenceMid:
        return mid.model_copy(update={"snapshot_id": snapshot_id, "asset": asset.upper()})

    client.app.state.aggregator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]

    resp = client.get("/quotes", params={"asset": "BTC", "notional": "10000", "venues": "mock"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset"] == "BTC"
    assert Decimal(body["notional_usd"]) == Decimal("10000")
    assert body["mid"]["mid_source"] == "binance_usdm_index"
    assert Decimal(body["mid"]["mid"]) == Decimal("100000")
    assert len(body["pairs"]) >= 1
    pair = next(p for p in body["pairs"] if p["venue"] == "mock")
    assert pair["buy"]["status"] == "ok"
    assert pair["sell"]["status"] == "ok"
    assert pair["buy"]["snapshot_id"] == pair["sell"]["snapshot_id"] == body["snapshot_id"]
    assert pair["buy"]["mid"] == pair["sell"]["mid"] == body["mid"]["mid"]
    assert Decimal(pair["round_trip_spread_bps"]) == Decimal("8.8")
    assert pair["top_of_book"] is not None


def test_quotes_invalid_notional(client: TestClient) -> None:
    client.app.state.aggregator.mid_service.resolve = AsyncMock(  # type: ignore[method-assign]
        return_value=ReferenceMid(
            snapshot_id="x",
            asset="BTC",
            mid=Decimal("1"),
            mid_source="binance_usdm_index",
            timestamp=datetime(2026, 8, 3, tzinfo=UTC),
        )
    )
    resp = client.get("/quotes", params={"asset": "BTC", "notional": "999"})
    assert resp.status_code == 422


def test_quotes_mid_failure_returns_503(client: TestClient) -> None:
    async def boom(asset: str, *, snapshot_id: str) -> ReferenceMid:
        raise MidResolutionError("all sources down")

    client.app.state.aggregator.mid_service.resolve = boom  # type: ignore[method-assign]
    resp = client.get("/quotes", params={"asset": "BTC", "notional": "10000", "venues": "mock"})
    assert resp.status_code == 503
    assert "reference mid" in resp.json()["detail"].lower()


def test_quotes_unknown_venue_422(client: TestClient) -> None:
    async def fake_resolve(asset: str, *, snapshot_id: str) -> ReferenceMid:
        return ReferenceMid(
            snapshot_id=snapshot_id,
            asset=asset.upper(),
            mid=Decimal("100000"),
            mid_source="binance_usdm_index",
            timestamp=datetime(2026, 8, 3, tzinfo=UTC),
        )

    client.app.state.aggregator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]
    resp = client.get(
        "/quotes",
        params={"asset": "BTC", "notional": "10000", "venues": "not_a_venue"},
    )
    assert resp.status_code == 422


@pytest.mark.live
def test_live_mid_and_quotes_smoke() -> None:
    """Hits real Binance mid; mock adapter only for quotes. Needs network."""
    with TestClient(create_app()) as client:
        resp = client.get(
            "/quotes",
            params={"asset": "BTC", "notional": "10000", "venues": "mock"},
        )
        # Mid may succeed against live Binance; require 200 if network works.
        assert resp.status_code in (200, 503)
        if resp.status_code == 200:
            body = resp.json()
            assert body["pairs"]
            assert Decimal(body["mid"]["mid"]) > 0
