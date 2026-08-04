"""WHI-843: multi-notional packages from one orderbook snapshot."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from spread_compare.adapters import get
from spread_compare.adapters._cex_common import CexBaseAdapter, OrderbookLevels
from spread_compare.adapters.cex_binance import BinanceAdapter
from spread_compare.api.app import create_app
from spread_compare.models import NOTIONAL_TIERS_USD, Quote, ReferenceMid
from spread_compare.orderbook_cache import (
    book_cache_key,
    default_orderbook_cache,
)

# WHI-799 §4.7 fixture book (symmetric about mid=100_000).
_ASKS: OrderbookLevels = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
_BIDS: OrderbookLevels = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]
# Fills $10k (q*=0.1) but not $1M (q*=10).
_PARTIAL_ASKS: OrderbookLevels = [
    (Decimal("100010"), Decimal("0.05")),
    (Decimal("100050"), Decimal("0.05")),
]
_PARTIAL_BIDS: OrderbookLevels = [
    (Decimal("99990"), Decimal("0.05")),
    (Decimal("99950"), Decimal("0.05")),
]

_MID = ReferenceMid(
    snapshot_id="snap-multi",
    asset="BTC",
    mid=Decimal("100000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)


@pytest.fixture(autouse=True)
def _clear_book_cache() -> Any:
    default_orderbook_cache().clear()
    yield
    default_orderbook_cache().clear()


def _inject_mid(client: TestClient) -> None:
    async def fake_resolve(asset: str, *, snapshot_id: str) -> ReferenceMid:
        return _MID.model_copy(
            update={"snapshot_id": snapshot_id, "asset": asset.upper()}
        )

    client.app.state.aggregator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]


def test_multi_tier_one_snapshot_and_mid() -> None:
    """One GET /quotes returns all five tiers under one snapshot_id + mid."""
    with TestClient(create_app()) as client:
        _inject_mid(client)
        tiers = ",".join(str(t) for t in NOTIONAL_TIERS_USD)
        resp = client.get(
            "/quotes",
            params={"asset": "BTC", "notionals": tiers, "venues": "mock"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["snapshot_id"]
        assert body["mid"]["mid_source"] == "binance_usdm_index"
        assert Decimal(body["mid"]["mid"]) == Decimal("100000")
        notionals = {Decimal(n) for n in body["notionals"]}
        assert notionals == set(NOTIONAL_TIERS_USD)
        pairs = body["pairs"]
        pair_notionals = {Decimal(p["notional_usd"]) for p in pairs}
        assert pair_notionals == set(NOTIONAL_TIERS_USD)
        for p in pairs:
            assert p["snapshot_id"] == body["snapshot_id"]
            assert p["buy"]["snapshot_id"] == body["snapshot_id"]
            assert p["buy"]["mid"] == body["mid"]["mid"]


def test_single_notional_still_works() -> None:
    with TestClient(create_app()) as client:
        _inject_mid(client)
        resp = client.get(
            "/quotes",
            params={"asset": "BTC", "notional": "10000", "venues": "mock"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert Decimal(body["notional_usd"]) == Decimal("10000")
        assert body["notionals"] == ["10000"] or [
            Decimal(n) for n in body["notionals"]
        ] == [Decimal("10000")]


def test_invalid_notionals_422() -> None:
    with TestClient(create_app()) as client:
        _inject_mid(client)
        r1 = client.get("/quotes", params={"asset": "BTC", "notional": "999"})
        assert r1.status_code == 422
        r2 = client.get(
            "/quotes", params={"asset": "BTC", "notionals": "100,999"}
        )
        assert r2.status_code == 422
        r3 = client.get(
            "/quotes",
            params={"asset": "BTC", "notional": "100", "notionals": "1000"},
        )
        assert r3.status_code == 422
        r4 = client.get("/quotes", params={"asset": "BTC"})
        assert r4.status_code == 422


def test_mixed_statuses_partial_depth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smaller tier ok, larger tier insufficient_liquidity in one package."""
    adapter = get("binance")
    assert isinstance(adapter, CexBaseAdapter)
    fetch_count = {"n": 0}

    async def fake_book(
        *args: Any, **kwargs: Any
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        fetch_count["n"] += 1
        return _PARTIAL_BIDS, _PARTIAL_ASKS

    monkeypatch.setattr(adapter, "_fetch_book", fake_book)

    with TestClient(create_app()) as client:
        _inject_mid(client)
        resp = client.get(
            "/quotes",
            params={
                "asset": "BTC",
                "notionals": "10000,1000000",
                "venues": "binance",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        by_n = {Decimal(p["notional_usd"]): p for p in body["pairs"]}
        assert by_n[Decimal("10000")]["buy"]["status"] == "ok"
        assert (
            by_n[Decimal("1000000")]["buy"]["status"] == "insufficient_liquidity"
        )
        # Batch walk (+ optional dual-side escalate) + TOB; far below per-tier.
        assert fetch_count["n"] <= 4


@pytest.mark.asyncio
async def test_batch_equals_per_tier_for_same_book(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batched multi-tier results match sequential single-tier for one book."""
    adapter = get("binance")
    assert isinstance(adapter, BinanceAdapter)

    async def fake_book(
        *args: Any, **kwargs: Any
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        return _BIDS, _ASKS

    monkeypatch.setattr(adapter, "_fetch_book", fake_book)

    single: list[Quote] = []
    for n in (Decimal("1000"), Decimal("10000")):
        q = await adapter.get_quote("BTC", "buy", n, mid=_MID)
        single.append(q)

    batch = await adapter.get_quotes_batch(
        "BTC",
        ["buy"],
        [Decimal("1000"), Decimal("10000")],
        mid=_MID,
    )
    assert len(batch) == 2
    for a, b in zip(single, batch, strict=True):
        assert a.status == b.status == "ok"
        assert a.spread_bps == b.spread_bps
        assert a.effective_price == b.effective_price
        assert a.total_cost_bps == b.total_cost_bps


@pytest.mark.asyncio
async def test_canonical_spread_bps_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHI-799 §4.7: spread_bps == 4.4 on the fixture book at $10k."""
    adapter = get("binance")
    assert isinstance(adapter, CexBaseAdapter)

    async def fake_book(
        *args: Any, **kwargs: Any
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        return _BIDS, _ASKS

    monkeypatch.setattr(adapter, "_fetch_book", fake_book)
    batch = await adapter.get_quotes_batch(
        "BTC",
        ["buy", "sell"],
        [Decimal("10000")],
        mid=_MID,
    )
    by_side = {q.side: q for q in batch}
    assert by_side["buy"].spread_bps == Decimal("4.4")
    assert by_side["sell"].spread_bps == Decimal("4.4")


@pytest.mark.asyncio
async def test_depth_key_shallow_not_reused_for_deeper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snapshot fetched at limit=100 must not silently answer a larger q*.

    Seed a shallow book under the limit=100 key; escalate for a large q* must
    either refetch a deeper limit or report insufficient_liquidity — never
    walk the truncated book as if it were full depth.
    """
    adapter = get("binance")
    assert isinstance(adapter, BinanceAdapter)
    cache = default_orderbook_cache()
    # Seed shallow cache entry as if a $100 walk had just completed.
    key100 = book_cache_key("binance", "BTCUSDT", "spot", 100)
    cache.put(
        key100,
        bids=_PARTIAL_BIDS,
        asks=_PARTIAL_ASKS,
        depth=100,
    )

    depths_fetched: list[int] = []

    async def counting_depth(
        symbol: str,
        book_side: str,
        *,
        limit: int,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        depths_fetched.append(limit)
        # Still shallow at every limit — proves we don't accept the shallow
        # cache as sufficient for q* that exceeds it without checking.
        return _PARTIAL_BIDS, _PARTIAL_ASKS

    monkeypatch.setattr(adapter, "_fetch_depth", counting_depth)

    # q* for $1M at mid 100k = 10 BTC; partial book only has 0.1.
    q = await adapter.get_quote("BTC", "buy", Decimal("1000000"), mid=_MID)
    assert q.status == "insufficient_liquidity"
    # Escalation walked higher limits rather than trusting the shallow cache.
    assert 500 in depths_fetched or 1000 in depths_fetched


def test_orderbook_call_count_multi_asset_multi_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 assets × 5 tiers → ~9 upstream depth calls, not 45 (WHI-843 table).

    Counts Binance ``_fetch_depth`` HTTP layer (the real cost). Uses a book deep
    enough for $1M so escalation stops at the first limit (happy path).
    """
    adapter = get("binance")
    assert isinstance(adapter, BinanceAdapter)
    depth_calls = {"n": 0}
    # Deep book: fills q*=10 ($1M at mid 100k) without climbing limit ladder.
    deep_asks: OrderbookLevels = [(Decimal("100010"), Decimal("20"))]
    deep_bids: OrderbookLevels = [(Decimal("99990"), Decimal("20"))]

    async def counting_depth(
        symbol: str,
        book_side: str,
        *,
        limit: int,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        depth_calls["n"] += 1
        return deep_bids, deep_asks

    monkeypatch.setattr(adapter, "_fetch_depth", counting_depth)

    with TestClient(create_app()) as client:
        _inject_mid(client)
        tiers = ",".join(str(t) for t in NOTIONAL_TIERS_USD)
        for asset in ("BTC", "ETH", "SOL"):
            async def fake_resolve(
                a: str, *, snapshot_id: str, _asset: str = asset
            ) -> ReferenceMid:
                return _MID.model_copy(
                    update={
                        "snapshot_id": snapshot_id,
                        "asset": a.upper(),
                        "mid": Decimal("100000"),
                    }
                )

            client.app.state.aggregator.mid_service.resolve = fake_resolve  # type: ignore[method-assign]
            resp = client.get(
                "/quotes",
                params={
                    "asset": asset,
                    "notionals": tiers,
                    "venues": "binance",
                },
            )
            assert resp.status_code == 200, resp.text
            assert len(resp.json()["pairs"]) == 5

    # Spec target: 45 → 9. Allow small headroom for TOB + dual-side escalate.
    assert depth_calls["n"] <= 12, depth_calls["n"]
    assert depth_calls["n"] >= 3, depth_calls["n"]
