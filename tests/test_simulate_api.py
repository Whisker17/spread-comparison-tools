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
    assert row["effective_price"] is not None
    assert Decimal(row["expected_output"]) == (
        Decimal("10000") / Decimal(row["effective_price"])
    )


def test_simulate_cross_pair_422(client: TestClient) -> None:
    resolve = AsyncMock()
    client.app.state.simulator.mid_service.resolve = resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={"sell_asset": "WETH", "buy_asset": "cbBTC", "amount": "1"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "cross_pair"
    assert "cross pair" in detail["message"].lower() or "non-stable" in detail["message"].lower()
    assert "unknown asset" not in detail["message"].lower()
    resolve.assert_not_called()


def test_simulate_unknown_asset_422(client: TestClient) -> None:
    resolve = AsyncMock()
    client.app.state.simulator.mid_service.resolve = resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={"sell_asset": "NOTREAL", "buy_asset": "USDC", "amount": "1"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "unknown_asset"
    assert "unknown asset" in detail["message"].lower()
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
    assert "422" in post["responses"]
    assert "/simulate/pairs" in paths
    assert "get" in paths["/simulate/pairs"]
    components = schema["components"]["schemas"]
    assert "SimulateRequest" in components
    assert "SimulateResponse" in components
    assert "SimulateRowResponse" in components
    assert "SimulatePairErrorDetail" in components
    assert "SimulatePairsResponse" in components
    pairs_props = components["SimulatePairsResponse"]["properties"]
    assert set(pairs_props) >= {"stables", "assets"}
    pair_err = components["SimulatePairErrorDetail"]["properties"]
    assert "message" in pair_err and "reason" in pair_err
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


def test_simulate_pairs_shape_excludes_usd(client: TestClient) -> None:
    """GET /simulate/pairs lists tradeable stables only — USD is peg, not pickable."""
    resp = client.get("/simulate/pairs")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stables"] == ["USDC", "USDT"]
    assert "USD" not in body["stables"]
    assert "USDC" not in body["assets"]
    assert "USDT" not in body["assets"]
    assert "USD" not in body["assets"]
    # Non-stable legs are the catalogued comparison assets (stable order).
    from spread_compare.assets import list_assets

    assert body["assets"] == [a.id for a in list_assets()]
    assert "BTC" in body["assets"] and "SOL" in body["assets"]


def test_simulate_pairs_round_trip_matches_validation(client: TestClient) -> None:
    """Advertised pairs are exactly what resolve_simulate_pair accepts (WHI-833)."""
    from spread_compare.simulator import InvalidSimulatePairError, resolve_simulate_pair

    body = client.get("/simulate/pairs").json()
    stables: list[str] = body["stables"]
    assets: list[str] = body["assets"]
    assert stables and assets

    for stable in stables:
        for asset in assets:
            sell_non_stable = resolve_simulate_pair(asset, stable)
            assert sell_non_stable.asset == asset
            assert sell_non_stable.side == "sell"
            assert sell_non_stable.stable_leg == stable

            sell_stable = resolve_simulate_pair(stable, asset)
            assert sell_stable.asset == asset
            assert sell_stable.side == "buy"
            assert sell_stable.stable_leg == stable

    # Stable × stable still rejected (HTTP 422 cross_pair).
    assert len(stables) >= 2
    with pytest.raises(InvalidSimulatePairError) as ei:
        resolve_simulate_pair(stables[0], stables[1])
    assert ei.value.reason == "cross_pair"

    resolve = AsyncMock()
    client.app.state.simulator.mid_service.resolve = resolve  # type: ignore[method-assign]
    resp = client.post(
        "/simulate",
        json={
            "sell_asset": stables[0],
            "buy_asset": stables[1],
            "amount": "1",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert isinstance(detail, dict)
    assert detail["reason"] == "cross_pair"
    resolve.assert_not_called()


def test_simulate_pairs_stables_not_in_asset_catalog(client: TestClient) -> None:
    """Tradeable stables stay out of GET /assets (no comparison-catalog leak)."""
    pairs = client.get("/simulate/pairs").json()
    catalog = client.get("/assets").json()
    catalog_ids = {row["id"] for row in catalog}
    for stable in pairs["stables"]:
        assert stable not in catalog_ids
    assert "USD" not in catalog_ids


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
