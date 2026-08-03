"""Reference-mid service unit tests (WHI-807 / WHI-799 §3)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from spread_compare.mids import MidResolutionError, MidService, is_mid_stale, median_marks
from spread_compare.settings import MidSettings

_TEST_MID = MidSettings(
    force_pyth=False,
    stale_threshold_sec=5,
    cache_max_age_sec=30,
    http_timeout_sec=5,
    pyth_feed_ids={},
)


def test_median_marks_odd() -> None:
    assert median_marks([Decimal("3"), Decimal("1"), Decimal("2")]) == Decimal("2")


def test_median_marks_even_arithmetic_mean() -> None:
    # WHI-799 §3.3: even count → mean of the two middle values.
    assert median_marks(
        [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    ) == Decimal("2.5")


def test_median_marks_empty() -> None:
    assert median_marks([]) is None


def test_is_mid_stale_threshold() -> None:
    mid_ts = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)
    quote_ok = datetime(2026, 8, 3, 12, 0, 4, tzinfo=UTC)
    quote_stale = datetime(2026, 8, 3, 12, 0, 6, tzinfo=UTC)
    assert is_mid_stale(quote_ok, mid_ts, stale_threshold_sec=5) is False
    assert is_mid_stale(quote_stale, mid_ts, stale_threshold_sec=5) is True


def _handler_factory(
    routes: dict[str, httpx.Response],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = f"{request.url.host}{request.url.path}"
        # Match host+path; query handled inside.
        for pattern, response in routes.items():
            if pattern in key or key.endswith(pattern) or pattern in str(request.url):
                return response
        return httpx.Response(404, json={"error": f"unmocked {request.url}"})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_resolve_p0_binance_usdm_index() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"indexPrice": "100000.50", "time": 1_725_000_000_000},
        )
        if "premiumIndex" in str(request.url)
        else httpx.Response(500)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        svc = MidService(_TEST_MID, client=client)
        mid = await svc.resolve("BTC", snapshot_id="snap-1")
    assert mid.snapshot_id == "snap-1"
    assert mid.asset == "BTC"
    assert mid.mid == Decimal("100000.50")
    assert mid.mid_source == "binance_usdm_index"


@pytest.mark.asyncio
async def test_resolve_falls_through_to_binance_spot_tob() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "premiumIndex" in url:
            return httpx.Response(503)
        if "bookTicker" in url:
            return httpx.Response(
                200,
                json={"bidPrice": "100", "askPrice": "102", "symbol": "BTCUSDT"},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = MidService(_TEST_MID, client=client)
        mid = await svc.resolve("BTC", snapshot_id="s2")
    assert mid.mid_source == "binance_spot_tob"
    assert mid.mid == Decimal("101")


@pytest.mark.asyncio
async def test_resolve_all_fail_raises() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        svc = MidService(_TEST_MID, client=client)
        with pytest.raises(MidResolutionError, match="no mid"):
            await svc.resolve("BTC", snapshot_id="s3")


@pytest.mark.asyncio
async def test_force_pyth() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "hermes.pyth.network" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "parsed": [
                        {
                            "price": {
                                "price": "9500012345",
                                "expo": -8,
                                "publish_time": 1_725_000_000,
                            }
                        }
                    ]
                },
            )
        return httpx.Response(503)

    settings = MidSettings(
        force_pyth=True,
        stale_threshold_sec=5,
        cache_max_age_sec=30,
        http_timeout_sec=5,
        pyth_feed_ids={
            "BTC": "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"
        },
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = MidService(settings, client=client)
        mid = await svc.resolve("BTC", snapshot_id="s4")
    assert mid.mid_source == "pyth"
    # 9500012345 * 10^-8 = 95.00012345
    assert mid.mid == Decimal("9500012345") * (Decimal("10") ** Decimal(-8))


@pytest.mark.asyncio
async def test_mid_cache_reuses_source_within_ttl() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "premiumIndex" in str(request.url):
            calls["n"] += 1
            return httpx.Response(
                200,
                json={"indexPrice": str(100_000 + calls["n"]), "time": 1},
            )
        return httpx.Response(404)

    clock = {"t": 0.0}

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        svc = MidService(
            _TEST_MID.model_copy(update={"cache_max_age_sec": 30}),
            client=client,
            clock=lambda: clock["t"],
        )
        m1 = await svc.resolve("BTC", snapshot_id="a")
        clock["t"] = 10.0
        m2 = await svc.resolve("BTC", snapshot_id="b")
        clock["t"] = 40.0
        m3 = await svc.resolve("BTC", snapshot_id="c")

    assert calls["n"] == 2
    assert m1.mid == m2.mid == Decimal("100001")
    assert m3.mid == Decimal("100002")
    # snapshot_id is always the caller's, even on cache hit
    assert m2.snapshot_id == "b"


class _Marks:
    async def marks_for(self, asset: str) -> list[tuple[str, Decimal]]:
        assert asset == "TSLA"
        return [
            ("binance", Decimal("250")),
            ("bybit", Decimal("252")),
            ("hyperliquid", Decimal("248")),
            ("lighter", Decimal("254")),
        ]


@pytest.mark.asyncio
async def test_proxy_perp_mark_median_for_equity() -> None:
    # Even count: mean of two middle values after sort → (250+252)/2 = 251
    transport = httpx.MockTransport(lambda _r: httpx.Response(503))
    async with httpx.AsyncClient(transport=transport) as client:
        svc = MidService(
            _TEST_MID,
            client=client,
            mark_provider=_Marks(),
        )
        mid = await svc.resolve("TSLA", snapshot_id="eq")
    assert mid.mid_source == "proxy_perp_mark_median"
    assert mid.mid == Decimal("251")
    assert mid.sources_detail is not None
    assert len(mid.sources_detail) == 4
