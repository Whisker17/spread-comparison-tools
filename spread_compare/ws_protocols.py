"""Pure per-venue sequence rules for local order-book maintenance (WHI-847).

Each handler is free of I/O so fixture tests can inject gaps without sockets.
Binance spot and futures are **separate** — do not share one sync routine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from spread_compare.bookwalk import OrderbookLevels
from spread_compare.local_book import BookHealth, LocalOrderBook

ResyncReason = Literal[
    "gap",
    "first_event",
    "restart_snapshot",
    "explicit_snapshot",
    "stale",
]


@dataclass
class ApplyResult:
    """Outcome of applying one WS/REST frame to a local book."""

    accepted: bool
    needs_resync: bool = False
    reason: ResyncReason | str | None = None
    message: str | None = None


def _parse_level_rows(raw: object) -> OrderbookLevels:
    if not isinstance(raw, list):
        raise ValueError(f"levels must be a list, got {type(raw).__name__}")
    out: OrderbookLevels = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError(f"bad level row: {row!r}")
        out.append((Decimal(str(row[0])), Decimal(str(row[1]))))
    return out


# ---------------------------------------------------------------------------
# Binance spot — REST snapshot + buffered diffs; first-event U/u rule
# ---------------------------------------------------------------------------


@dataclass
class BinanceSpotSync:
    """Maintain one Binance **spot** book (not futures).

    Procedure (official local-order-book guide):
    1. Buffer WS diffs.
    2. REST snapshot → ``lastUpdateId``.
    3. Drop events with ``u < lastUpdateId``.
    4. First applied event must satisfy ``U <= lastUpdateId+1 <= u``.
    5. Subsequent events: ``U <= lastUpdateId+1 <= u`` continuity via last ``u``.
    """

    book: LocalOrderBook
    _buffer: list[dict[str, Any]] = field(default_factory=list)
    _synced: bool = False

    def buffer_event(self, event: dict[str, Any]) -> None:
        self._buffer.append(event)

    def apply_snapshot(self, *, last_update_id: int, bids: object, asks: object) -> None:
        self.book.apply_snapshot(
            _parse_level_rows(bids),
            _parse_level_rows(asks),
            update_id=last_update_id,
            health=BookHealth.SYNCING,
        )
        self._synced = False
        self._drain_buffer()

    def on_diff(self, event: dict[str, Any]) -> ApplyResult:
        if not self._synced:
            self._buffer.append(event)
            if self.book.last_update_id is None:
                self.book.set_health(BookHealth.SYNCING)
                return ApplyResult(
                    accepted=False,
                    reason="first_event",
                    message="awaiting snapshot",
                )
            return self._drain_buffer()
        return self._apply_event(event)

    def _drain_buffer(self) -> ApplyResult:
        if self.book.last_update_id is None:
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")
        # Drop events fully behind the snapshot.
        kept: list[dict[str, Any]] = []
        for ev in self._buffer:
            u = int(ev["u"])
            if u < self.book.last_update_id:
                continue
            kept.append(ev)
        self._buffer = kept
        if not self._buffer:
            return ApplyResult(
                accepted=False,
                reason="first_event",
                message="buffer empty after drop",
            )

        first = self._buffer[0]
        u_first = int(first["U"])
        u_last = int(first["u"])
        target = self.book.last_update_id + 1
        if not (u_first <= target <= u_last):
            self._buffer.clear()
            self.book.set_health(BookHealth.RESYNCING, error="first event failed U/u rule")
            return ApplyResult(
                accepted=False,
                needs_resync=True,
                reason="first_event",
                message=f"U={u_first} u={u_last} lastUpdateId={self.book.last_update_id}",
            )

        last_result = ApplyResult(accepted=False)
        while self._buffer:
            last_result = self._apply_event(self._buffer.pop(0), is_first=not self._synced)
            if last_result.needs_resync:
                self._buffer.clear()
                return last_result
            self._synced = True
        return last_result

    def _apply_event(self, event: dict[str, Any], *, is_first: bool = False) -> ApplyResult:
        u = int(event["u"])
        U = int(event["U"])
        last = self.book.last_update_id
        if last is None:
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")
        # After first event, each subsequent must continue: U == last+1 (strict cont.).
        if not is_first and not self._synced:
            # Should not happen — treat as resync.
            return ApplyResult(accepted=False, needs_resync=True, reason="gap")
        if self._synced:
            if U != last + 1:
                self.book.set_health(BookHealth.RESYNCING, error="spot sequence gap")
                return ApplyResult(
                    accepted=False,
                    needs_resync=True,
                    reason="gap",
                    message=f"expected U={last + 1}, got U={U}",
                )
        else:
            target = last + 1
            if not (U <= target <= u):
                self.book.set_health(BookHealth.RESYNCING, error="spot first-event miss")
                return ApplyResult(accepted=False, needs_resync=True, reason="first_event")

        bids = _parse_level_rows(event.get("b") or [])
        asks = _parse_level_rows(event.get("a") or [])
        self.book.apply_levels(bids=bids, asks=asks, update_id=u)
        return ApplyResult(accepted=True)


# ---------------------------------------------------------------------------
# Binance USDⓈ-M futures — pu continuity (NOT the spot U/u first-event rule)
# ---------------------------------------------------------------------------


@dataclass
class BinanceFuturesSync:
    """Maintain one Binance **futures** book.

    Continuity rule: each event's ``pu`` must equal the previous event's ``u``
    (after the snapshot is applied). Gap → full resync. Never use the spot
    first-event routine here.
    """

    book: LocalOrderBook
    _buffer: list[dict[str, Any]] = field(default_factory=list)
    _synced: bool = False

    def buffer_event(self, event: dict[str, Any]) -> None:
        self._buffer.append(event)

    def apply_snapshot(self, *, last_update_id: int, bids: object, asks: object) -> None:
        self.book.apply_snapshot(
            _parse_level_rows(bids),
            _parse_level_rows(asks),
            update_id=last_update_id,
            health=BookHealth.SYNCING,
        )
        self._synced = False
        self._drain_buffer()

    def on_diff(self, event: dict[str, Any]) -> ApplyResult:
        if not self._synced:
            self._buffer.append(event)
            if self.book.last_update_id is None:
                self.book.set_health(BookHealth.SYNCING)
                return ApplyResult(accepted=False, reason="first_event")
            return self._drain_buffer()
        return self._apply_event(event)

    def _drain_buffer(self) -> ApplyResult:
        if self.book.last_update_id is None:
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")
        last = self.book.last_update_id
        kept: list[dict[str, Any]] = []
        for ev in self._buffer:
            if int(ev["u"]) < last:
                continue
            kept.append(ev)
        self._buffer = kept
        if not self._buffer:
            return ApplyResult(accepted=False, reason="first_event")

        # First applied event after snapshot: U <= lastUpdateId AND u >= lastUpdateId
        # (futures guide) — then subsequent use pu continuity.
        first = self._buffer[0]
        U = int(first["U"])
        u = int(first["u"])
        if not (U <= last and u >= last):
            self._buffer.clear()
            self.book.set_health(BookHealth.RESYNCING, error="futures first event out of range")
            return ApplyResult(
                accepted=False,
                needs_resync=True,
                reason="first_event",
                message=f"U={U} u={u} lastUpdateId={last}",
            )
        last_result = ApplyResult(accepted=False)
        prev_u = last
        # Apply first without pu check; then track u for pu.
        last_result = self._apply_event(self._buffer.pop(0), prev_u=prev_u, first=True)
        if last_result.needs_resync:
            self._buffer.clear()
            return last_result
        self._synced = True
        while self._buffer:
            last_result = self._apply_event(self._buffer.pop(0))
            if last_result.needs_resync:
                self._buffer.clear()
                return last_result
        return last_result

    def _apply_event(
        self,
        event: dict[str, Any],
        *,
        prev_u: int | None = None,
        first: bool = False,
    ) -> ApplyResult:
        u = int(event["u"])
        pu = event.get("pu")
        last = self.book.last_update_id
        if last is None:
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")

        if not first and self._synced:
            if pu is None or int(pu) != last:
                self.book.set_health(BookHealth.RESYNCING, error="futures pu gap")
                return ApplyResult(
                    accepted=False,
                    needs_resync=True,
                    reason="gap",
                    message=f"pu={pu!r} expected {last}",
                )
        elif first:
            # First after snapshot already validated U/u range in drain.
            _ = prev_u

        bids = _parse_level_rows(event.get("b") or [])
        asks = _parse_level_rows(event.get("a") or [])
        self.book.apply_levels(bids=bids, asks=asks, update_id=u)
        return ApplyResult(accepted=True)


# ---------------------------------------------------------------------------
# Bybit v5 orderbook — snapshot → delta; u==1 restart; new snapshot rebuilds
# ---------------------------------------------------------------------------


@dataclass
class BybitSync:
    """Bybit ``orderbook.{depth}.{symbol}`` maintainer."""

    book: LocalOrderBook

    def on_message(self, msg_type: str, data: dict[str, Any]) -> ApplyResult:
        """Apply snapshot or delta. ``u == 1`` forces overwrite (service restart)."""
        update_id = int(data.get("u", 0))
        seq = data.get("seq")
        seq_i = int(seq) if seq is not None else None
        bids = _parse_level_rows(data.get("b") or [])
        asks = _parse_level_rows(data.get("a") or [])

        if msg_type == "snapshot" or update_id == 1:
            self.book.apply_snapshot(
                bids,
                asks,
                update_id=update_id,
                seq=seq_i,
                health=BookHealth.HEALTHY,
            )
            reason: ResyncReason | str | None
            if update_id == 1 and msg_type != "snapshot":
                reason = "restart_snapshot"
            else:
                reason = "explicit_snapshot"
            return ApplyResult(accepted=True, reason=reason)

        if msg_type != "delta":
            return ApplyResult(accepted=False, message=f"unknown type {msg_type!r}")

        last = self.book.last_update_id
        if last is None or self.book.health is not BookHealth.HEALTHY:
            self.book.set_health(BookHealth.RESYNCING, error="delta before snapshot")
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")

        # Bybit docs: u increases; gap if not last+1 (some feeds use seq).
        if update_id != last + 1:
            self.book.set_health(BookHealth.RESYNCING, error="bybit u gap")
            return ApplyResult(
                accepted=False,
                needs_resync=True,
                reason="gap",
                message=f"u={update_id} expected {last + 1}",
            )

        self.book.apply_levels(bids=bids, asks=asks, update_id=update_id, seq=seq_i)
        return ApplyResult(accepted=True)


# ---------------------------------------------------------------------------
# Hyperliquid — every push is a full 20-level snapshot (no sequencing)
# ---------------------------------------------------------------------------


@dataclass
class HyperliquidSync:
    """HL ``l2Book``: replace book on every push. No gap logic."""

    book: LocalOrderBook

    def on_snapshot(self, bids: object, asks: object) -> ApplyResult:
        self.book.apply_snapshot(
            _parse_level_rows(bids),
            _parse_level_rows(asks),
            update_id=(self.book.last_update_id or 0) + 1,
            health=BookHealth.HEALTHY,
        )
        return ApplyResult(accepted=True)


# ---------------------------------------------------------------------------
# Lighter — begin_nonce chain; offset is NOT continuous
# ---------------------------------------------------------------------------


@dataclass
class LighterSync:
    """Lighter ``order_book`` channel: snapshot then deltas via nonce chain.

    Gap detection: each update's ``begin_nonce`` must equal the previous
    update's ``nonce``. Never use ``offset`` for continuity.
    """

    book: LocalOrderBook

    def on_snapshot(
        self,
        *,
        bids: object,
        asks: object,
        nonce: int,
    ) -> ApplyResult:
        self.book.apply_snapshot(
            _parse_level_rows(bids),
            _parse_level_rows(asks),
            update_id=nonce,
            seq=nonce,
            health=BookHealth.HEALTHY,
        )
        return ApplyResult(accepted=True)

    def on_update(
        self,
        *,
        bids: object,
        asks: object,
        begin_nonce: int,
        nonce: int,
        offset: object = None,
    ) -> ApplyResult:
        _ = offset  # explicitly ignored — not continuous
        last = self.book.last_seq
        if last is None:
            self.book.set_health(BookHealth.RESYNCING, error="lighter delta before snapshot")
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")
        if begin_nonce != last:
            self.book.set_health(BookHealth.RESYNCING, error="lighter begin_nonce gap")
            return ApplyResult(
                accepted=False,
                needs_resync=True,
                reason="gap",
                message=f"begin_nonce={begin_nonce} expected {last} (offset ignored)",
            )
        self.book.apply_levels(
            bids=_parse_level_rows(bids),
            asks=_parse_level_rows(asks),
            update_id=nonce,
            seq=nonce,
        )
        return ApplyResult(accepted=True)


# ---------------------------------------------------------------------------
# ApeX — snapshot then delta with u update id
# ---------------------------------------------------------------------------


@dataclass
class ApexSync:
    """ApeX ``orderBook200.H.<sym>``: snapshot then delta; u must be continuous."""

    book: LocalOrderBook

    def on_snapshot(self, *, bids: object, asks: object, update_id: int) -> ApplyResult:
        self.book.apply_snapshot(
            _parse_level_rows(bids),
            _parse_level_rows(asks),
            update_id=update_id,
            health=BookHealth.HEALTHY,
        )
        return ApplyResult(accepted=True)

    def on_delta(self, *, bids: object, asks: object, update_id: int) -> ApplyResult:
        last = self.book.last_update_id
        if last is None:
            self.book.set_health(BookHealth.RESYNCING, error="apex delta before snapshot")
            return ApplyResult(accepted=False, needs_resync=True, reason="first_event")
        if update_id != last + 1:
            self.book.set_health(BookHealth.RESYNCING, error="apex u gap")
            return ApplyResult(
                accepted=False,
                needs_resync=True,
                reason="gap",
                message=f"u={update_id} expected {last + 1}",
            )
        self.book.apply_levels(
            bids=_parse_level_rows(bids),
            asks=_parse_level_rows(asks),
            update_id=update_id,
        )
        return ApplyResult(accepted=True)
