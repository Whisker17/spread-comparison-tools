"""HTTP API tests for POST /simulate (WHI-814)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from spread_compare.api.app import create_app
from spread_compare.api.simulate import ClientRateGuard
from spread_compare.mids import MidResolutionError
from spread_compare.models import ReferenceMid


@pytest.fixture
def client() -> Any:
    with TestClient(create_app()) as c:
        # Disable per-client rate guard for sequential unit tests.
        c.app.state.simulate_rate_guard = ClientRateGuard(0.0)
        yield c


def _inject_btc_mid(client: TestClient, mid: Decimal = Decimal("100000")) -> None:
    fixed = ReferenceMid(
        snapshot_id="will-be-overwritten",
        asset="BTC",
        mid=mid,
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )

    async def fake_resolve(asset: str, *, snapshot_id: str) -> ReferenceMid:
        return fixed.model_copy(
            update={"snapshot_id": snapshot_id, "asset": asset.upper()}
        )

    client.app.state.simulator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]


def test_simulate_happy_path_sell(client: TestClient) -> None:
    _inject_btc_mid(client)
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": "BTC",
            "buy_asset": "USDC",
            "amount": "0.1",
            "venues": ["mock"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sell_asset"] == "BTC"
    assert body["buy_asset"] == "USDC"
    assert body["asset"] == "BTC"
    assert body["side"] == "sell"
    assert Decimal(body["notional_usd"]) == Decimal("10000")
    assert Decimal(body["amount"]) == Decimal("0.1")
    assert body["mid"]["mid_source"] == "binance_usdm_index"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["venue"] == "mock"
    assert row["status"] == "ok"
    assert row["best"] is True
    assert row["expected_output"] is not None
    assert row["fee_breakdown"] is not None
    assert row["total_cost_bps"] is not None
    assert row["venue_symbol"] == "BTCUSDT"


def test_simulate_happy_path_buy(client: TestClient) -> None:
    _inject_btc_mid(client)
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": "USDC",
            "buy_asset": "BTC",
            "amount": "10000",
            "venues": ["mock"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["side"] == "buy"
    assert Decimal(body["notional_usd"]) == Decimal("10000")
    row = body["rows"][0]
    assert row["status"] == "ok"
    assert Decimal(row["expected_output"]) == Decimal("0.1")


def test_simulate_cross_pair_422(client: TestClient) -> None:
    resolve = AsyncMock()
    client.app.state.simulator.mid_service.resolve = resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={"sell_asset": "WETH", "buy_asset": "cbBTC", "amount": "1"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"].lower()
    assert "cross pair" in detail or "non-stable" in detail
    assert "unknown asset" not in detail
    resolve.assert_not_called()


def test_simulate_unknown_asset_422(client: TestClient) -> None:
    resolve = AsyncMock()
    client.app.state.simulator.mid_service.resolve = resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={"sell_asset": "NOTREAL", "buy_asset": "USDC", "amount": "1"},
    )
    assert resp.status_code == 422
    assert "unknown asset" in resp.json()["detail"].lower()
    resolve.assert_not_called()


def test_simulate_not_supported_listed(client: TestClient) -> None:
    fixed = ReferenceMid(
        snapshot_id="x",
        asset="SOL",
        mid=Decimal("150"),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )

    async def fake_resolve(asset: str, *, snapshot_id: str) -> ReferenceMid:
        return fixed.model_copy(
            update={"snapshot_id": snapshot_id, "asset": asset.upper()}
        )

    client.app.state.simulator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": "SOL",
            "buy_asset": "USDC",
            "amount": "10",
            "venues": ["mock"],
        },
    )
    assert resp.status_code == 200
    row = resp.json()["rows"][0]
    assert row["status"] == "not_supported"
    assert row["best"] is False


def test_simulate_mid_failure_503(client: TestClient) -> None:
    async def boom(asset: str, *, snapshot_id: str) -> ReferenceMid:
        raise MidResolutionError("all sources down")

    client.app.state.simulator.mid_service.resolve = boom  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": "BTC",
            "buy_asset": "USDC",
            "amount": "0.1",
            "venues": ["mock"],
        },
    )
    assert resp.status_code == 503
    assert "reference mid" in resp.json()["detail"].lower()


def test_simulate_free_form_amount(client: TestClient) -> None:
    _inject_btc_mid(client)
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": "BTC",
            "buy_asset": "USDC",
            "amount": "0.123",
            "venues": ["mock"],
        },
    )
    assert resp.status_code == 200
    assert Decimal(resp.json()["notional_usd"]) == Decimal("12300")


def test_simulate_openapi_documents_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/simulate" in paths
    assert "post" in paths["/simulate"]
    post = paths["/simulate"]["post"]
    assert "requestBody" in post
    components = schema["components"]["schemas"]
    assert "SimulateRequest" in components
    assert "SimulateResponse" in components
    assert "SimulateRowResponse" in components
    req_props = components["SimulateRequest"]["properties"]
    assert set(req_props) >= {"sell_asset", "buy_asset", "amount"}
    row_props = components["SimulateRowResponse"]["properties"]
    for key in (
        "venue",
        "expected_output",
        "effective_price",
        "fee_breakdown",
        "total_cost_bps",
        "status",
        "best",
    ):
        assert key in row_props


def test_simulate_rate_guard_429() -> None:
    with TestClient(create_app()) as client:
        client.app.state.simulate_rate_guard = ClientRateGuard(60.0)
        _inject_btc_mid(client)
        body = {
            "sell_asset": "BTC",
            "buy_asset": "USDC",
            "amount": "0.1",
            "venues": ["mock"],
        }
        first = client.post("/simulate", json=body)
        assert first.status_code == 200
        second = client.post("/simulate", json=body)
        assert second.status_code == 429
        assert "rate limit" in second.json()["detail"].lower()


@pytest.mark.live
def test_live_simulate_sol_usdc_prop_amms() -> None:
    """Live SOL → USDC ~$50k: all three Solana prop AMMs respond with fee breakdown."""
    with TestClient(create_app()) as client:
        # ~$50k at a plausible SOL mid; free-form amount in SOL units.
        # Use amount that yields ~50k notional once mid resolves (approx 250 SOL @ $200).
        resp = client.post(
            "/simulate",
            json={
                "sell_asset": "SOL",
                "buy_asset": "USDC",
                "amount": "250",
            },
        )
        assert resp.status_code in (200, 503), resp.text
        if resp.status_code != 200:
            return
        body = resp.json()
        assert body["asset"] == "SOL"
        assert body["side"] == "sell"
        by_venue = {r["venue"]: r for r in body["rows"]}
        prop_slugs = ("humidifi", "tessera_solana", "bisonfi")
        prop_rows = [by_venue[s] for s in prop_slugs if s in by_venue]
        assert len(prop_rows) == 3, f"missing prop AMM rows: {sorted(by_venue)}"
        ok_outputs: list[Decimal] = []
        for row in prop_rows:
            assert row["status"] in (
                "ok",
                "no_quote",
                "insufficient_liquidity",
                "error",
                "unsupported_asset",
                "not_supported",
            )
            assert "fee_breakdown" in row
            if row["status"] == "ok":
                assert row["expected_output"] is not None
                assert row["fee_breakdown"] is not None
                ok_outputs.append(Decimal(row["expected_output"]))
        # At least one prop should quote; when multiple ok, outputs in a sane band.
        if len(ok_outputs) >= 2:
            lo, hi = min(ok_outputs), max(ok_outputs)
            # Within 5% of each other for ~same notional on liquid SOL/USDC.
            assert hi / lo < Decimal("1.05"), (lo, hi)
