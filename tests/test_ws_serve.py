"""Serve-from-local-book path: zero REST when healthy, error when stale (WHI-847)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from spread_compare.adapters._cex_common import build_quote_from_book
from spread_compare.adapters.cex_binance import BinanceAdapter
from spread_compare.local_book import BookHealth
from spread_compare.models import ReferenceMid
from spread_compare.settings import clear_settings_cache, load_mid_settings, load_ws_settings
from spread_compare.ws_registry import WsBookRegistry, default_ws_registry
from spread_compare.ws_serve import LocalBookUnavailable, try_local_book

# WHI-799 §4.7 fixture book
MID = Decimal("100000")
NOTIONAL = Decimal("10000")
ASKS = [
    (Decimal("100010"), Decimal("0.04")),
    (Decimal("100050"), Decimal("0.04")),
    (Decimal("100100"), Decimal("0.10")),
]
BIDS = [
    (Decimal("99990"), Decimal("0.04")),
    (Decimal("99950"), Decimal("0.04")),
    (Decimal("99900"), Decimal("0.10")),
]


def _mid(*, age_sec: float = 0.5) -> ReferenceMid:
    now = datetime.now(tz=UTC)
    return ReferenceMid(
        snapshot_id="snap-ws",
        asset="BTC",
        mid=MID,
        mid_source="binance_usdm_index",
        timestamp=now - timedelta(seconds=age_sec),
    )


def test_ws_fed_quote_matches_rest_book_canonical() -> None:
    """Same book → same walk whether labeled WS or REST; §4.7 spread_bps == 4.4."""
    mid = _mid()
    rest = build_quote_from_book(
        venue="binance",
        asset="BTC",
        side="buy",
        notional_usd=NOTIONAL,
        mid=mid,
        instrument_type="spot",
        venue_symbol="BTCUSDT",
        bids=BIDS,
        asks=ASKS,
        trading_fee_bps=Decimal("10"),
        from_ws=False,
    )
    ws = build_quote_from_book(
        venue="binance",
        asset="BTC",
        side="buy",
        notional_usd=NOTIONAL,
        mid=mid,
        instrument_type="spot",
        venue_symbol="BTCUSDT",
        bids=BIDS,
        asks=ASKS,
        trading_fee_bps=Decimal("10"),
        from_ws=True,
        book_age_sec=0.05,
    )
    assert rest.effective_price == Decimal("100044")
    assert rest.spread_bps == Decimal("4.4")
    assert ws.effective_price == rest.effective_price
    assert ws.spread_bps == rest.spread_bps
    assert ws.age_sec == pytest.approx(0.05)
    assert ws.mid_stale is False


def test_ws_quote_mid_stale_when_mid_older_than_max_age() -> None:
    clear_settings_cache()
    settings = load_mid_settings()
    mid = _mid(age_sec=settings.max_age_for_ws_quote_sec + 1.0)
    quote = build_quote_from_book(
        venue="binance",
        asset="BTC",
        side="buy",
        notional_usd=NOTIONAL,
        mid=mid,
        instrument_type="spot",
        venue_symbol="BTCUSDT",
        bids=BIDS,
        asks=ASKS,
        trading_fee_bps=Decimal("10"),
        from_ws=True,
        book_age_sec=0.1,
    )
    assert quote.status == "ok"
    assert quote.mid_stale is True
    # Still priced — §3.2 degrades via flag, does not drop numbers.
    assert quote.spread_bps == Decimal("4.4")


@pytest.mark.asyncio
async def test_adapter_serves_local_book_without_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = default_ws_registry()
    reg.put_fixture_book("binance", "BTCUSDT", "spot", BIDS, ASKS)
    adapter = BinanceAdapter(ws_registry=reg)
    rest_calls = {"n": 0}

    async def boom(*_a: object, **_k: object) -> tuple[list[object], list[object]]:
        rest_calls["n"] += 1
        raise AssertionError("REST must not be called when WS book is healthy")

    monkeypatch.setattr(adapter, "_fetch_book", boom)
    mid = _mid()
    quote = await adapter.get_quote(
        "BTC", "buy", NOTIONAL, mid=mid, instrument_type="spot"
    )
    assert rest_calls["n"] == 0
    assert quote.status == "ok"
    assert quote.spread_bps == Decimal("4.4")
    assert quote.age_sec is not None


@pytest.mark.asyncio
async def test_stale_local_book_errors_not_stale_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_cache()
    reg = default_ws_registry()
    book = reg.put_fixture_book("binance", "BTCUSDT", "spot", BIDS, ASKS)
    # Force age past max_book_age_sec
    max_age = load_ws_settings().max_book_age_sec
    book.updated_mono = (book.updated_mono or 0.0) - (max_age + 1.0)
    assert book.health is BookHealth.HEALTHY

    adapter = BinanceAdapter(ws_registry=reg)
    rest_calls = {"n": 0}

    async def rest_ok(*_a: object, **_k: object) -> tuple[list, list]:
        rest_calls["n"] += 1
        return BIDS, ASKS

    monkeypatch.setattr(adapter, "_fetch_book", rest_ok)
    mid = _mid()
    quote = await adapter.get_quote(
        "BTC", "buy", NOTIONAL, mid=mid, instrument_type="spot"
    )
    # Healthy-but-stale → error, not silent REST of stale local numbers
    assert quote.status == "error"
    assert quote.error_code == "book_stale"
    assert rest_calls["n"] == 0


def test_try_local_book_stale_raises() -> None:
    clear_settings_cache()
    reg = WsBookRegistry(max_book_age_sec=1.0)
    book = reg.put_fixture_book("bybit", "BTCUSDT", "spot", BIDS, ASKS)
    # Well past config max_book_age_sec (5s) so the healthy-but-stale gate fires.
    book.updated_mono = (book.updated_mono or 0.0) - 30.0
    with pytest.raises(LocalBookUnavailable) as ei:
        try_local_book("bybit", "BTCUSDT", "spot", registry=reg)
    assert ei.value.code == "book_stale"


def test_disconnected_book_falls_through_to_rest() -> None:
    reg = WsBookRegistry()
    book = reg.get_or_create("binance", "ETHUSDT", "spot")
    book.set_health(BookHealth.DISCONNECTED)
    assert try_local_book("binance", "ETHUSDT", "spot", registry=reg) is None


def test_depth_1m_btc_levels_sufficient() -> None:
    """Synthetic deep book covers $1M; shallow HL-style 20-level SOL does not fabricate."""
    from spread_compare.bookwalk import walk_book

    mid = Decimal("100000")
    # 70 levels × 0.2 BTC ≈ $1.4M capacity
    deep_asks = [(mid + Decimal(i), Decimal("0.2")) for i in range(70)]
    q = Decimal("1000000") / mid
    assert walk_book(deep_asks, q) is not None

    # 20 levels × small size — $1M fails (HL SOL case)
    shallow = [(Decimal("150"), Decimal("100")) for _ in range(20)]  # ~$300k
    q_sol = Decimal("1000000") / Decimal("150")
    assert walk_book(shallow, q_sol) is None


def test_one_connection_per_stream_not_per_asset() -> None:
    """Registry connection accounting: many symbols, one stream_id open count."""
    reg = WsBookRegistry()
    reg.mark_connection("binance_spot", open=True)
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"):
        reg.put_fixture_book("binance", sym, "spot", BIDS, ASKS)
    assert reg.connection_count("binance_spot") == 1
    assert reg.book_count() == 4
    assert reg.total_connections() == 1
