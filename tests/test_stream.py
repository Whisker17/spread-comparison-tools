"""WebSocket push stream (WHI-848): origin, coalesce, heartbeat, shared collect."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from spread_compare.aggregator import QuotesPackage
from spread_compare.api.app import create_app
from spread_compare.models import (
    FeeBreakdown,
    ReferenceMid,
    SizeQuotePair,
)
from spread_compare.settings import StreamSettings, clear_settings_cache
from spread_compare.stream import (
    QuoteStreamHub,
    StreamSubscribe,
    diff_pairs,
    origin_allowed,
    package_to_wire,
    pair_fingerprint,
    pair_identity_key,
    parse_notionals,
)


def _mid(asset: str = "BTC", snap: str = "snap-live") -> ReferenceMid:
    return ReferenceMid(
        snapshot_id=snap,
        asset=asset,
        mid=Decimal("100000"),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC),
    )


def _fee() -> FeeBreakdown:
    return FeeBreakdown(
        embedded_in_price=False,
        trading_fee_bps=Decimal("10"),
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=Decimal("10"),
        gas_bps=Decimal("0"),
    )


def _ok_pair(
    *,
    venue: str = "mock",
    asset: str = "BTC",
    notional: str = "1000",
    snap: str = "snap-row",
    total_cost: str = "20",
    age_sec: float | None = 2.0,
    quote_stale: bool = False,
) -> SizeQuotePair:
    from spread_compare.models import Quote

    n = Decimal(notional)
    buy = Quote(
        snapshot_id=snap,
        venue=venue,
        asset=asset,
        instrument_type="spot",
        side="buy",
        notional_usd=n,
        mid=Decimal("100000"),
        mid_source="binance_usdm_index",
        mid_timestamp=datetime(2026, 8, 5, 12, 0, 0, tzinfo=UTC),
        quote_stale=quote_stale,
        age_sec=age_sec,
        effective_price=Decimal("100100"),
        spread_bps=Decimal("10"),
        fee_breakdown=_fee(),
        total_cost_bps=Decimal(total_cost),
        timestamp=datetime(2026, 8, 5, 12, 0, 1, tzinfo=UTC),
        status="ok",
        qty_base=Decimal("0.01"),
    )
    return SizeQuotePair(
        snapshot_id=snap,
        venue=venue,
        asset=asset,
        instrument_type="spot",
        notional_usd=n,
        buy=buy,
        sell=None,
    )


def _package(
    asset: str = "BTC",
    pairs: list[SizeQuotePair] | None = None,
    snap: str = "snap-pkg",
) -> QuotesPackage:
    mid = _mid(asset, snap)
    return QuotesPackage(
        snapshot_id=snap,
        asset=asset,
        notional_usd=Decimal("1000"),
        mid=mid,
        pairs=pairs or [_ok_pair(asset=asset, snap=snap)],
        notionals=(Decimal("1000"),),
    )


def _stream_settings(**overrides: Any) -> StreamSettings:
    base = {
        "coalesce_interval_ms": 50.0,
        "heartbeat_interval_sec": 0.05,
        "client_liveness_timeout_sec": 0.2,
        "max_clients": 10,
        "max_assets_per_client": 5,
        "max_venues_per_client": 10,
        # WHI-888: depth must cover one frame per subscribed asset per tick.
        "max_queue_depth": 5,
    }
    base.update(overrides)
    # Keep the production invariant unless a test is explicitly probing rejection
    # (both caps overridden with an invalid pair).
    if (
        "max_queue_depth" not in overrides
        and base["max_queue_depth"] < base["max_assets_per_client"]
    ):
        base["max_queue_depth"] = base["max_assets_per_client"]
    return StreamSettings.model_validate(base)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_origin_allowed_matches_cors_list() -> None:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert origin_allowed("http://localhost:3000", origins) is True
    assert origin_allowed("http://localhost:3000/", origins) is True
    assert origin_allowed("http://evil.example", origins) is False
    assert origin_allowed(None, origins) is False
    assert origin_allowed("", origins) is False


def test_pair_identity_key_includes_form() -> None:
    """WHI-881: dual forms on same venue must not clobber in delta merge."""
    a = _ok_pair(venue="tessera_bsc", asset="NVDA")
    assert pair_identity_key(a) == f"tessera_bsc|{a.notional_usd}|{a.instrument_type}|-"
    bstock = a.model_copy(update={"form": "bstock"})
    ondo = a.model_copy(update={"form": "ondo"})
    assert pair_identity_key(bstock).endswith("|bstock")
    assert pair_identity_key(ondo).endswith("|ondo")
    assert pair_identity_key(bstock) != pair_identity_key(ondo)


def test_diff_pairs_ignores_age_sec_only_but_sees_stale() -> None:
    """age_sec advances every serve — must not force a delta alone (WHI-848)."""
    a = _ok_pair(age_sec=1.0, quote_stale=False)
    aged = _ok_pair(age_sec=40.0, quote_stale=False)
    prev = {pair_identity_key(a): a}
    changed, removed = diff_pairs(prev, [aged])
    assert removed == []
    assert changed == []
    # quote_stale flip still pushes.
    stale = _ok_pair(age_sec=40.0, quote_stale=True)
    changed2, _ = diff_pairs(prev, [stale])
    assert len(changed2) == 1
    assert changed2[0].buy is not None
    assert changed2[0].buy.quote_stale is True
    assert pair_fingerprint(a) != pair_fingerprint(stale)


def test_package_to_wire_carries_row_snapshot_and_age() -> None:
    pair = _ok_pair(snap="sweep-aaa", age_sec=12.5, quote_stale=False)
    wire = package_to_wire(_package(pairs=[pair], snap="pkg-bbb"))
    assert wire["snapshot_id"] == "pkg-bbb"
    row = wire["pairs"][0]["buy"]
    assert row["snapshot_id"] == "sweep-aaa"
    assert row["age_sec"] == 12.5
    assert row["timestamp"]
    assert row["quote_stale"] is False


def test_parse_notionals() -> None:
    assert parse_notionals(["1000", "10000"]) == (
        Decimal("1000"),
        Decimal("10000"),
    )
    with pytest.raises(ValueError, match="invalid notional"):
        parse_notionals(["nope"])


# ---------------------------------------------------------------------------
# Hub unit tests (no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hub_coalesce_caps_frame_rate() -> None:
    """Venue changing every 50 ms must not exceed coalesce frame rate.

    Hub is only ticked once per coalesce window (100 ms). Over 0.5 s that is
    ≤ 6 frames — far below the 10 updates a raw 50 ms source would emit.
    """
    packages = [
        _package(pairs=[_ok_pair(total_cost=str(i), snap=f"s{i}")])
        for i in range(20)
    ]
    idx = {"i": 0}

    async def collect(*_a: Any, **_k: Any) -> QuotesPackage:
        i = min(idx["i"], len(packages) - 1)
        idx["i"] += 1
        return packages[i]

    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(side_effect=collect)
    settings = _stream_settings(coalesce_interval_ms=100.0)
    hub = QuoteStreamHub(aggregator, settings, cors_origins=["http://localhost:3000"])
    client = await hub.register()
    hub.subscribe(
        client,
        StreamSubscribe.model_validate(
            {
                "type": "subscribe",
                "assets": ["BTC"],
                "notionals": ["1000"],
                "venues": ["mock"],
            }
        ),
    )

    # Tick at the coalesce interval only (what the hub loop does).
    frames = 0
    for _ in range(5):
        await hub.publish_once()
        while not client.outbound.empty():
            msg = client.outbound.get_nowait()
            if msg["type"] in ("snapshot", "delta"):
                frames += 1
        await asyncio.sleep(0.05)

    # 5 coalesce ticks ⇒ ≤ 5 frames; a 50 ms raw source over the same span
    # would emit ~10 updates. Assert the coalesce bound.
    assert frames == 5
    assert frames < 10
    await hub.unregister(client.client_id)


@pytest.mark.asyncio
async def test_hub_n_clients_share_one_collect() -> None:
    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(return_value=_package())
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(),
        cors_origins=["http://localhost:3000"],
    )
    clients = []
    for _ in range(5):
        c = await hub.register()
        hub.subscribe(
            c,
            StreamSubscribe.model_validate(
                {
                    "type": "subscribe",
                    "assets": ["BTC"],
                    "notionals": ["1000"],
                    "venues": ["mock"],
                }
            ),
        )
        clients.append(c)

    await hub.publish_once()
    assert hub.collect_calls == 1
    assert aggregator.collect.await_count == 1
    for c in clients:
        assert not c.outbound.empty()
        msg = c.outbound.get_nowait()
        assert msg["type"] == "snapshot"
        assert msg["data"]["asset"] == "BTC"


@pytest.mark.asyncio
async def test_hub_snapshot_then_delta() -> None:
    p1 = _package(pairs=[_ok_pair(total_cost="10", snap="s1")], snap="s1")
    p2 = _package(pairs=[_ok_pair(total_cost="11", snap="s2")], snap="s2")
    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(side_effect=[p1, p2])
    hub = QuoteStreamHub(
        aggregator, _stream_settings(), cors_origins=["http://localhost:3000"]
    )
    client = await hub.register()
    hub.subscribe(
        client,
        StreamSubscribe.model_validate(
            {
                "type": "subscribe",
                "assets": ["BTC"],
                "notionals": ["1000"],
            }
        ),
    )
    await hub.publish_once()
    snap = client.outbound.get_nowait()
    assert snap["type"] == "snapshot"
    assert snap["data"]["pairs"][0]["buy"]["total_cost_bps"] == "10"

    await hub.publish_once()
    delta = client.outbound.get_nowait()
    assert delta["type"] == "delta"
    assert delta["pairs"][0]["buy"]["total_cost_bps"] == "11"
    assert delta["pairs"][0]["buy"]["snapshot_id"] == "s2"


@pytest.mark.asyncio
async def test_hub_heartbeat_frames() -> None:
    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(return_value=_package())
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(heartbeat_interval_sec=0.05, client_liveness_timeout_sec=0.2),
        cors_origins=["http://localhost:3000"],
    )
    client = await hub.register()
    await hub.start()
    try:
        await asyncio.sleep(0.12)
        heartbeats = []
        while not client.outbound.empty():
            msg = client.outbound.get_nowait()
            if msg["type"] == "heartbeat":
                heartbeats.append(msg)
        assert len(heartbeats) >= 1
        assert "ts" in heartbeats[0]
    finally:
        await hub.stop()


# ---------------------------------------------------------------------------
# HTTP / WebSocket endpoint
# ---------------------------------------------------------------------------


def _inject_mid(client: TestClient) -> None:
    async def resolve(
        asset: str, snapshot_id: str | None = None, **_k: Any
    ) -> ReferenceMid:
        return _mid(asset.upper(), snapshot_id or "mid-snap")

    client.app.state.mid_service.resolve = AsyncMock(side_effect=resolve)  # type: ignore[attr-defined]


def test_stream_rejects_disallowed_origin() -> None:
    """Handshake fails when Origin is not on cors_origins (WHI-848)."""
    with TestClient(create_app()) as client:
        denied = False
        try:
            with client.websocket_connect(
                "/stream",
                headers={"Origin": "http://evil.example"},
            ):
                pass
        except Exception:  # noqa: B017 — TestClient maps denial to several types
            denied = True
        assert denied is True


def test_stream_rejects_missing_origin() -> None:
    with TestClient(create_app()) as client:
        denied = False
        try:
            with client.websocket_connect("/stream"):
                pass
        except Exception:  # noqa: B017 — TestClient maps denial to several types
            denied = True
        assert denied is True


def test_stream_subscribe_snapshot_and_rest_quotes_still_work() -> None:
    """WS snapshot + GET /quotes both work (REST unchanged)."""
    with TestClient(create_app()) as client:
        _inject_mid(client)
        # REST path still healthy.
        r = client.get(
            "/quotes",
            params={"asset": "BTC", "notional": "1000", "venues": "mock"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["asset"] == "BTC"
        assert body["pairs"]

        with client.websocket_connect(
            "/stream",
            headers={"Origin": "http://localhost:3000"},
        ) as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["client_liveness_timeout_sec"] == 45.0
            assert hello["coalesce_interval_ms"] == 400.0
            ws.send_json(
                {
                    "type": "subscribe",
                    "assets": ["BTC"],
                    "notionals": ["1000"],
                    "venues": ["mock"],
                }
            )
            # Drain until snapshot (may interleave with heartbeat if slow).
            msg = None
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "snapshot":
                    break
            assert msg is not None
            assert msg["type"] == "snapshot"
            data = msg["data"]
            assert data["asset"] == "BTC"
            assert data["pairs"]
            buy = data["pairs"][0]["buy"]
            assert "snapshot_id" in buy
            assert "timestamp" in buy
            # age_sec may be null for live mock rows; field present on schema dump.
            assert "quote_stale" in buy

            ws.send_json({"type": "ping"})
            pong = None
            for _ in range(5):
                m = ws.receive_json()
                if m["type"] == "pong":
                    pong = m
                    break
            assert pong == {"type": "pong"}


def test_stream_resnapshot_returns_full_snapshot() -> None:
    with TestClient(create_app()) as client:
        _inject_mid(client)
        with client.websocket_connect(
            "/stream",
            headers={"Origin": "http://localhost:3000"},
        ) as ws:
            assert ws.receive_json()["type"] == "hello"
            ws.send_json(
                {
                    "type": "subscribe",
                    "assets": ["BTC"],
                    "notionals": ["1000"],
                    "venues": ["mock"],
                }
            )
            first = None
            for _ in range(10):
                m = ws.receive_json()
                if m["type"] == "snapshot":
                    first = m
                    break
            assert first is not None

            ws.send_json({"type": "resnapshot"})
            second = None
            for _ in range(10):
                m = ws.receive_json()
                if m["type"] == "snapshot":
                    second = m
                    break
            assert second is not None
            assert second["type"] == "snapshot"
            assert second["data"]["asset"] == "BTC"


def test_stream_settings_load() -> None:
    clear_settings_cache()
    from spread_compare.settings import load_stream_settings

    s = load_stream_settings()
    assert s.coalesce_interval_ms == 400.0
    assert s.heartbeat_interval_sec == 15.0
    assert s.client_liveness_timeout_sec == 45.0
    assert s.max_clients >= 1
    # WHI-888: one frame per asset per coalesce tick must fit the queue.
    assert s.max_queue_depth >= s.max_assets_per_client


def test_stream_settings_reject_queue_shallower_than_assets() -> None:
    """max_queue_depth < max_assets_per_client is a structural storm config."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="max_queue_depth"):
        StreamSettings.model_validate(
            {
                "coalesce_interval_ms": 400.0,
                "heartbeat_interval_sec": 15.0,
                "client_liveness_timeout_sec": 45.0,
                "max_clients": 10,
                "max_assets_per_client": 20,
                "max_venues_per_client": 40,
                "max_queue_depth": 8,
            }
        )


@pytest.mark.asyncio
async def test_hub_max_clients_and_max_assets() -> None:
    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(return_value=_package())
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(max_clients=2, max_assets_per_client=1),
        cors_origins=["http://localhost:3000"],
    )
    c1 = await hub.register()
    c2 = await hub.register()
    from spread_compare.stream import StreamLimitError

    with pytest.raises(StreamLimitError, match="max concurrent"):
        await hub.register()

    with pytest.raises(StreamLimitError, match="max assets"):
        hub.subscribe(
            c1,
            StreamSubscribe.model_validate(
                {
                    "type": "subscribe",
                    "assets": ["BTC", "ETH"],
                    "notionals": ["1000"],
                }
            ),
        )
    hub.subscribe(
        c1,
        StreamSubscribe.model_validate(
            {
                "type": "subscribe",
                "assets": ["BTC"],
                "notionals": ["1000"],
            }
        ),
    )
    await hub.unregister(c1.client_id)
    await hub.unregister(c2.client_id)


@pytest.mark.asyncio
async def test_hub_max_venues_is_union_across_filters() -> None:
    """max_venues_per_client counts the union, not per-filter lists."""
    from spread_compare.stream import StreamLimitError

    aggregator = AsyncMock()
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(max_venues_per_client=2, max_assets_per_client=10),
        cors_origins=["http://localhost:3000"],
    )
    client = await hub.register()
    with pytest.raises(StreamLimitError, match="max venues"):
        hub.subscribe(
            client,
            StreamSubscribe.model_validate(
                {
                    "type": "subscribe",
                    "filters": [
                        {
                            "assets": ["BTC"],
                            "notionals": ["1000"],
                            "venues": ["a", "b"],
                        },
                        {
                            "assets": ["ETH"],
                            "notionals": ["1000"],
                            "venues": ["c"],
                        },
                    ],
                }
            ),
        )
    await hub.unregister(client.client_id)


@pytest.mark.asyncio
async def test_hub_queue_overflow_forces_resnapshot() -> None:
    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(return_value=_package())
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(max_queue_depth=1, max_assets_per_client=1),
        cors_origins=["http://localhost:3000"],
    )
    client = await hub.register()
    hub.subscribe(
        client,
        StreamSubscribe.model_validate(
            {
                "type": "subscribe",
                "assets": ["BTC"],
                "notionals": ["1000"],
            }
        ),
    )
    await hub.publish_once()
    # Fill queue so next enqueue drops.
    while not client.outbound.full():
        client.outbound.put_nowait({"type": "heartbeat", "ts": 0})
    assert client.enqueue({"type": "delta", "asset": "BTC", "pairs": []}) is True
    assert "BTC" in client.need_snapshot
    # Dropped frame was a heartbeat (no asset) — baseline may remain until a
    # quote frame is dropped. Seed a quote frame then overflow again.
    while not client.outbound.empty():
        client.outbound.get_nowait()
    client.last_pairs["BTC"] = {"k": _ok_pair()}
    client.last_mid_json["BTC"] = "mid"
    client.need_snapshot.discard("BTC")
    client.outbound.put_nowait({"type": "delta", "asset": "BTC", "pairs": []})
    assert client.outbound.full()
    assert client.enqueue({"type": "delta", "asset": "BTC", "pairs": []}) is True
    assert "BTC" in client.need_snapshot
    assert "BTC" not in client.last_pairs
    await hub.unregister(client.client_id)


@pytest.mark.asyncio
async def test_enqueue_overflow_invalidates_only_dropped_asset() -> None:
    """WHI-888: full wipe of every baseline turned multi-asset overflow into a
    permanent snapshot storm; only the dropped frame's asset must re-snapshot.
    """
    from spread_compare.stream import StreamClient

    client = StreamClient(
        client_id="c1",
        outbound=asyncio.Queue(maxsize=1),
    )
    pair = _ok_pair()
    client.last_pairs = {
        "BTC": {"k": pair},
        "ETH": {"k": pair},
        "SOL": {"k": pair},
    }
    client.last_mid_json = {"BTC": "b", "ETH": "e", "SOL": "s"}
    client.need_snapshot = set()

    # Oldest frame is BTC; enqueue ETH while full → drop BTC only.
    client.outbound.put_nowait({"type": "delta", "asset": "BTC", "pairs": []})
    assert client.enqueue({"type": "delta", "asset": "ETH", "pairs": []}) is True

    assert client.need_snapshot == {"BTC"}
    assert "BTC" not in client.last_pairs
    assert "ETH" in client.last_pairs
    assert "SOL" in client.last_pairs
    assert client.last_mid_json == {"ETH": "e", "SOL": "s"}


@pytest.mark.asyncio
async def test_multi_asset_subscription_yields_deltas_not_snapshot_storm() -> None:
    """WHI-888 regression: N assets > prior queue cliff still delivers deltas.

    Pre-fix: queue depth 8 + full baseline wipe → permanent snapshot storm at
    N=14. Post-fix: after the initial snapshot pass, further ticks are deltas
    (snapshot count bounded by asset count + small constant).
    """
    assets = [
        "NVDA",
        "TSLA",
        "AAPL",
        "MSFT",
        "QQQ",
        "SPCX",
        "CRCL",
        "GOOGL",
        "AMD",
        "PLTR",
        "META",
        "AMZN",
        "SPY",
        "MSTR",
    ]
    n = len(assets)

    async def collect(asset: str, *args: Any, **kwargs: Any) -> QuotesPackage:
        return _package(asset=asset, snap=f"snap-{asset}")

    aggregator = AsyncMock()
    aggregator.collect = AsyncMock(side_effect=collect)
    # Depth covers one tick of N assets (production invariant); slow consumer
    # still drains between ticks so we observe frame types, not tunnel latency.
    hub = QuoteStreamHub(
        aggregator,
        _stream_settings(
            max_assets_per_client=n,
            max_queue_depth=n,
            coalesce_interval_ms=50.0,
        ),
        cors_origins=["http://localhost:3000"],
    )
    client = await hub.register()
    hub.subscribe(
        client,
        StreamSubscribe.model_validate(
            {
                "type": "subscribe",
                "assets": assets,
                "notionals": ["1000"],
            }
        ),
    )

    counts: dict[str, int] = {"snapshot": 0, "delta": 0}

    async def drain() -> None:
        while True:
            try:
                msg = client.outbound.get_nowait()
            except asyncio.QueueEmpty:
                return
            t = msg.get("type")
            if t in counts:
                counts[t] += 1

    # Initial tick: one snapshot per asset.
    await hub.publish_once()
    await drain()
    assert counts["snapshot"] == n
    assert counts["delta"] == 0
    assert not client.need_snapshot

    # Subsequent ticks with unchanged packages: mid/pairs unchanged → no frames.
    # Force a mid change path by returning packages with a new snapshot_id (and
    # therefore a new mid.snapshot_id) so every asset emits a delta.
    async def collect_v2(asset: str, *args: Any, **kwargs: Any) -> QuotesPackage:
        return _package(asset=asset, snap=f"snap2-{asset}")

    aggregator.collect = AsyncMock(side_effect=collect_v2)
    for _ in range(3):
        await hub.publish_once()
        await drain()

    assert counts["delta"] >= n  # at least one delta pass across all assets
    # Snapshots must not grow linearly with ticks (storm signature).
    assert counts["snapshot"] <= n + 2, counts
    await hub.unregister(client.client_id)
