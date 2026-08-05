"""Per-venue sequence-gap fixtures for local order-book maintenance (WHI-847)."""

from __future__ import annotations

from decimal import Decimal

from spread_compare.local_book import BookHealth, LocalOrderBook
from spread_compare.ws_protocols import (
    ApexSync,
    BinanceFuturesSync,
    BinanceSpotSync,
    BybitSync,
    HyperliquidSync,
    LighterSync,
)

BIDS = [["100", "1"], ["99", "2"]]
ASKS = [["101", "1"], ["102", "2"]]


def _book(venue: str = "binance", symbol: str = "BTCUSDT", itype: str = "spot") -> LocalOrderBook:
    return LocalOrderBook(venue=venue, symbol=symbol, instrument_type=itype)


# --- Binance spot (U/u first-event rule) ------------------------------------


def test_binance_spot_first_event_u_u_rule_accepts() -> None:
    book = _book()
    sync = BinanceSpotSync(book)
    sync.apply_snapshot(last_update_id=100, bids=BIDS, asks=ASKS)
    # First event: U <= lastUpdateId+1 <= u
    result = sync.on_diff(
        {
            "U": 101,
            "u": 105,
            "b": [["100", "1.5"]],
            "a": [],
        }
    )
    assert result.accepted is True
    assert result.needs_resync is False
    assert book.health is BookHealth.HEALTHY
    assert book.last_update_id == 105
    bids, _ = book.levels()
    assert bids[0] == (Decimal("100"), Decimal("1.5"))


def test_binance_spot_first_event_miss_triggers_resync() -> None:
    book = _book()
    sync = BinanceSpotSync(book)
    sync.apply_snapshot(last_update_id=100, bids=BIDS, asks=ASKS)
    # U=110 > lastUpdateId+1=101 → gap / first-event miss
    result = sync.on_diff({"U": 110, "u": 115, "b": [], "a": []})
    assert result.needs_resync is True
    assert result.reason == "first_event"
    assert book.health is BookHealth.RESYNCING
    # Never serve while resyncing
    assert book.is_servable(max_age_sec=60.0) is False


def test_binance_spot_subsequent_gap_triggers_resync() -> None:
    book = _book()
    sync = BinanceSpotSync(book)
    sync.apply_snapshot(last_update_id=100, bids=BIDS, asks=ASKS)
    assert sync.on_diff({"U": 101, "u": 105, "b": [], "a": []}).accepted
    # Expected U=106, inject gap
    result = sync.on_diff({"U": 200, "u": 205, "b": [["100", "9"]], "a": []})
    assert result.needs_resync is True
    assert result.reason == "gap"
    assert book.health is BookHealth.RESYNCING
    # Corrupted delta must not have been applied
    bids, _ = book.levels()
    assert (Decimal("100"), Decimal("9")) not in bids


# --- Binance futures (pu continuity) ----------------------------------------


def test_binance_futures_pu_continuity_accepts() -> None:
    book = _book(itype="perp")
    sync = BinanceFuturesSync(book)
    sync.apply_snapshot(last_update_id=50, bids=BIDS, asks=ASKS)
    # First after snapshot: U <= last AND u >= last
    r1 = sync.on_diff({"U": 40, "u": 55, "pu": 49, "b": [], "a": [["101", "2"]]})
    assert r1.accepted is True
    assert book.last_update_id == 55
    r2 = sync.on_diff({"U": 56, "u": 60, "pu": 55, "b": [], "a": []})
    assert r2.accepted is True
    assert book.last_update_id == 60
    assert book.health is BookHealth.HEALTHY


def test_binance_futures_pu_gap_triggers_resync() -> None:
    book = _book(itype="perp")
    sync = BinanceFuturesSync(book)
    sync.apply_snapshot(last_update_id=50, bids=BIDS, asks=ASKS)
    assert sync.on_diff({"U": 40, "u": 55, "pu": 49, "b": [], "a": []}).accepted
    # pu must equal previous u (55); inject gap
    result = sync.on_diff({"U": 56, "u": 60, "pu": 54, "b": [["100", "99"]], "a": []})
    assert result.needs_resync is True
    assert result.reason == "gap"
    assert book.health is BookHealth.RESYNCING
    bids, _ = book.levels()
    assert all(sz != Decimal("99") for _, sz in bids)


# --- Bybit ------------------------------------------------------------------


def test_bybit_snapshot_then_delta() -> None:
    book = _book(venue="bybit")
    sync = BybitSync(book)
    r0 = sync.on_message(
        "snapshot",
        {"u": 10, "seq": 100, "b": BIDS, "a": ASKS},
    )
    assert r0.accepted is True
    r1 = sync.on_message(
        "delta",
        {"u": 11, "seq": 101, "b": [["100", "0"]], "a": []},  # delete bid 100
    )
    assert r1.accepted is True
    bids, _ = book.levels()
    assert Decimal("100") not in {px for px, _ in bids}


def test_bybit_u_equals_1_is_restart_snapshot() -> None:
    book = _book(venue="bybit")
    sync = BybitSync(book)
    sync.on_message("snapshot", {"u": 10, "b": BIDS, "a": ASKS})
    # Service restart: u==1 overwrites even if type is delta-shaped
    result = sync.on_message(
        "delta",
        {"u": 1, "b": [["50", "5"]], "a": [["51", "5"]]},
    )
    assert result.accepted is True
    assert result.reason == "restart_snapshot"
    bids, asks = book.levels()
    assert bids[0][0] == Decimal("50")
    assert asks[0][0] == Decimal("51")


def test_bybit_gap_triggers_resync() -> None:
    book = _book(venue="bybit")
    sync = BybitSync(book)
    sync.on_message("snapshot", {"u": 10, "b": BIDS, "a": ASKS})
    result = sync.on_message("delta", {"u": 20, "b": [], "a": []})
    assert result.needs_resync is True
    assert result.reason == "gap"
    assert book.health is BookHealth.RESYNCING


def test_bybit_new_snapshot_rebuilds() -> None:
    book = _book(venue="bybit")
    sync = BybitSync(book)
    sync.on_message("snapshot", {"u": 10, "b": BIDS, "a": ASKS})
    result = sync.on_message(
        "snapshot",
        {"u": 99, "b": [["1", "1"]], "a": [["2", "1"]]},
    )
    assert result.accepted is True
    assert result.reason == "explicit_snapshot"
    bids, _ = book.levels()
    assert bids == [(Decimal("1"), Decimal("1"))]


# --- Hyperliquid ------------------------------------------------------------


def test_hyperliquid_full_snapshot_replace() -> None:
    book = _book(venue="hyperliquid", symbol="BTC", itype="perp")
    sync = HyperliquidSync(book)
    sync.on_snapshot(BIDS, ASKS)
    sync.on_snapshot([["200", "3"]], [["201", "3"]])
    bids, asks = book.levels()
    assert bids == [(Decimal("200"), Decimal("3"))]
    assert asks == [(Decimal("201"), Decimal("3"))]
    assert book.health is BookHealth.HEALTHY


# --- Lighter (begin_nonce; offset ignored) ----------------------------------


def test_lighter_nonce_chain_accepts() -> None:
    book = _book(venue="lighter", symbol="BTC", itype="perp")
    sync = LighterSync(book)
    assert sync.on_snapshot(bids=BIDS, asks=ASKS, nonce=10).accepted
    result = sync.on_update(
        bids=[["100", "2"]],
        asks=[],
        begin_nonce=10,
        nonce=12,
        offset=99999,  # discontinuous — must be ignored
    )
    assert result.accepted is True
    assert book.last_seq == 12


def test_lighter_begin_nonce_gap_triggers_resync() -> None:
    book = _book(venue="lighter", symbol="BTC", itype="perp")
    sync = LighterSync(book)
    sync.on_snapshot(bids=BIDS, asks=ASKS, nonce=10)
    result = sync.on_update(
        bids=[["100", "9"]],
        asks=[],
        begin_nonce=99,  # gap
        nonce=100,
        offset=1,
    )
    assert result.needs_resync is True
    assert result.reason == "gap"
    assert book.health is BookHealth.RESYNCING
    bids, _ = book.levels()
    assert all(sz != Decimal("9") for _, sz in bids)


# --- ApeX -------------------------------------------------------------------


def test_apex_snapshot_then_delta() -> None:
    book = _book(venue="apex", symbol="BTCUSDT", itype="perp")
    sync = ApexSync(book)
    assert sync.on_snapshot(bids=BIDS, asks=ASKS, update_id=5).accepted
    result = sync.on_delta(bids=[["100", "0"]], asks=[], update_id=6)
    assert result.accepted is True
    bids, _ = book.levels()
    assert Decimal("100") not in {px for px, _ in bids}


def test_apex_u_gap_triggers_resync() -> None:
    book = _book(venue="apex", symbol="BTCUSDT", itype="perp")
    sync = ApexSync(book)
    sync.on_snapshot(bids=BIDS, asks=ASKS, update_id=5)
    result = sync.on_delta(bids=[["100", "9"]], asks=[], update_id=9)
    assert result.needs_resync is True
    assert result.reason == "gap"
    assert book.health is BookHealth.RESYNCING
