"""Browser WebSocket push hub (WHI-848).

Serves the same aggregator packages as ``GET /quotes`` over a single push
stream: full snapshot on subscribe/reconnect, then coalesced deltas. Multiple
clients sharing a filter key share one ``collect`` call per coalesce tick so
viewer count does not multiply upstream load.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Literal used by StreamSubscribe / StreamResnapshot / StreamPing / StreamPong.
from spread_compare.aggregator import QuoteAggregator, QuotesPackage
from spread_compare.models import InstrumentType, Side, SizeQuotePair
from spread_compare.settings import StreamSettings

logger = logging.getLogger(__name__)

class StreamFilterSpec(BaseModel):
    """One asset-set filter (section boards may send several on one socket)."""

    model_config = ConfigDict(extra="forbid")

    assets: list[str] = Field(min_length=1)
    notionals: list[str] = Field(min_length=1)
    venues: list[str] | None = None
    side: Side | None = None
    instrument_type: InstrumentType | None = None

    @field_validator("assets", mode="before")
    @classmethod
    def _upper_assets(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(v).strip().upper() for v in value if str(v).strip()]

    @field_validator("venues", mode="before")
    @classmethod
    def _strip_venues(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return [str(v).strip() for v in value if str(v).strip()]


class StreamSubscribe(BaseModel):
    """Client subscription request.

    Flat form (single filter)::

        {"type":"subscribe","assets":[...],"notionals":[...],...}

    Multi-filter form (e.g. stocks spot + equity perps on one socket)::

        {"type":"subscribe","filters":[{...},{...}]}
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["subscribe"] = "subscribe"
    # Flat fields — optional when ``filters`` is set.
    assets: list[str] | None = None
    notionals: list[str] | None = None
    venues: list[str] | None = None
    side: Side | None = None
    instrument_type: InstrumentType | None = None
    filters: list[StreamFilterSpec] | None = None

    @field_validator("assets", mode="before")
    @classmethod
    def _upper_assets(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return [str(v).strip().upper() for v in value if str(v).strip()]

    @field_validator("venues", mode="before")
    @classmethod
    def _strip_venues(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return [str(v).strip() for v in value if str(v).strip()]

    def resolved_filters(self) -> list[StreamFilterSpec]:
        """Normalize flat or multi form into a non-empty filter list."""
        if self.filters:
            return list(self.filters)
        if not self.assets or not self.notionals:
            raise ValueError("subscribe requires assets+notionals or filters")
        return [
            StreamFilterSpec(
                assets=self.assets,
                notionals=self.notionals,
                venues=self.venues,
                side=self.side,
                instrument_type=self.instrument_type,
            )
        ]


class StreamResnapshot(BaseModel):
    """Request full snapshots for all (or listed) subscribed assets."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["resnapshot"] = "resnapshot"
    assets: list[str] | None = None

    @field_validator("assets", mode="before")
    @classmethod
    def _upper_assets(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, list):
            return value
        return [str(v).strip().upper() for v in value if str(v).strip()]


class StreamPing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ping"] = "ping"


class StreamPong(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["pong"] = "pong"


@dataclass(frozen=True, slots=True)
class StreamFilter:
    """Canonical collect key shared across clients (WHI-848 fan-out dedupe)."""

    asset: str
    notionals: tuple[Decimal, ...]
    venues: tuple[str, ...] | None
    side: Side | None
    instrument_type: InstrumentType | None

    def cache_key(self) -> str:
        venues = ",".join(self.venues) if self.venues is not None else "*"
        notionals = ",".join(str(n) for n in self.notionals)
        return (
            f"{self.asset}|{notionals}|{venues}|{self.side or '*'}|"
            f"{self.instrument_type or '*'}"
        )


def parse_notionals(raw: Iterable[str]) -> tuple[Decimal, ...]:
    """Parse notional strings to Decimals (order preserved, no §4.1 check here)."""
    out: list[Decimal] = []
    for part in raw:
        try:
            out.append(Decimal(str(part).strip()))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid notional: {part!r}") from exc
    if not out:
        raise ValueError("notionals must list at least one tier")
    return tuple(out)


def pair_identity_key(pair: SizeQuotePair) -> str:
    """Stable key for delta merge (venue × notional × instrument)."""
    return f"{pair.venue}|{pair.notional_usd}|{pair.instrument_type}"


def pair_fingerprint(pair: SizeQuotePair) -> str:
    """Content hash for change detection.

    ``age_sec`` is excluded: it advances every serve and would force a full
    re-send of every store row on every coalesce tick. ``quote_stale`` stays
    in the dump so the best-eligibility flip still pushes. FE shows age from
    ``timestamp`` / last stamped ``age_sec`` (WHI-848).
    """
    dump = pair.model_dump(mode="json")
    for leg_name in ("buy", "sell"):
        leg = dump.get(leg_name)
        if isinstance(leg, dict):
            leg.pop("age_sec", None)
    return str(dump)


def diff_pairs(
    previous: Mapping[str, SizeQuotePair],
    current: list[SizeQuotePair],
) -> tuple[list[SizeQuotePair], list[str]]:
    """Return (changed_or_new pairs, removed identity keys)."""
    current_map = {pair_identity_key(p): p for p in current}
    changed: list[SizeQuotePair] = []
    for key, pair in current_map.items():
        prev = previous.get(key)
        if prev is None or pair_fingerprint(prev) != pair_fingerprint(pair):
            changed.append(pair)
    removed = [k for k in previous if k not in current_map]
    return changed, removed


def package_to_wire(package: QuotesPackage) -> dict[str, Any]:
    """Serialize a package into the REST ``QuotesResponse`` shape."""
    notionals = (
        list(package.notionals) if package.notionals else [package.notional_usd]
    )
    return {
        "snapshot_id": package.snapshot_id,
        "asset": package.asset,
        "notional_usd": str(package.notional_usd),
        "mid": package.mid.model_dump(mode="json"),
        "pairs": [p.model_dump(mode="json") for p in package.pairs],
        "notionals": [str(n) for n in notionals],
    }


def origin_allowed(origin: str | None, cors_origins: Iterable[str]) -> bool:
    """WS Origin check against the same allowlist as HTTP CORS (WHI-848).

    Missing Origin is rejected — browsers always send it; scripts must pass an
    allowed origin explicitly in tests / tooling.
    """
    if origin is None or origin == "":
        return False
    allowed = {o.rstrip("/") for o in cors_origins}
    return origin.rstrip("/") in allowed


class StreamLimitError(Exception):
    """Subscription or client cap exceeded."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StreamClient:
    """One connected browser session."""

    client_id: str
    # Outbound frames; bounded — drop oldest on overflow.
    outbound: asyncio.Queue[dict[str, Any]]
    filters: dict[str, StreamFilter] = field(default_factory=dict)
    last_pairs: dict[str, dict[str, SizeQuotePair]] = field(default_factory=dict)
    last_mid_json: dict[str, str] = field(default_factory=dict)
    need_snapshot: set[str] = field(default_factory=set)
    closed: bool = False

    def enqueue(
        self, message: dict[str, Any], *, important: bool = True
    ) -> None:
        """Push a frame; drop the oldest if the queue is full (backpressure).

        Important frames (snapshot/delta): a drop can skip a delta that later
        frames assume was applied, so force a full resnapshot on the next tick.

        Heartbeats are not important — drop silently without invalidating
        delta state when the client is already behind.
        """
        if self.closed:
            return
        if self.outbound.full():
            if not important:
                return
            try:
                self.outbound.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.need_snapshot = set(self.filters)
            self.last_pairs.clear()
            self.last_mid_json.clear()
            logger.warning(
                "stream client %s queue full; dropping oldest frame + "
                "forcing resnapshot",
                self.client_id,
            )
        try:
            self.outbound.put_nowait(message)
        except asyncio.QueueFull:
            if not important:
                return
            self.need_snapshot = set(self.filters)
            self.last_pairs.clear()
            self.last_mid_json.clear()
            logger.warning(
                "stream client %s still full after drop; forcing resnapshot",
                self.client_id,
            )


class QuoteStreamHub:
    """Process-wide stream hub: register clients, coalesce publishes."""

    def __init__(
        self,
        aggregator: QuoteAggregator,
        settings: StreamSettings,
        *,
        cors_origins: Iterable[str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._aggregator = aggregator
        self._settings = settings
        self._cors_origins = list(cors_origins or [])
        self._clock = clock or time.monotonic
        self._clients: dict[str, StreamClient] = {}
        self._lock = asyncio.Lock()
        # Serialise full publish ticks so subscribe cannot interleave with the
        # background coalesce and deliver packages out of order.
        self._publish_lock = asyncio.Lock()
        self._tick_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # Test hook: count of aggregator.collect calls (shared-key dedupe).
        self.collect_calls: int = 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def settings(self) -> StreamSettings:
        return self._settings

    def hello_message(self) -> dict[str, Any]:
        """First frame after accept — FE liveness mirrors server config."""
        return {
            "type": "hello",
            "coalesce_interval_ms": self._settings.coalesce_interval_ms,
            "heartbeat_interval_sec": self._settings.heartbeat_interval_sec,
            "client_liveness_timeout_sec": self._settings.client_liveness_timeout_sec,
        }

    def is_origin_allowed(self, origin: str | None) -> bool:
        return origin_allowed(origin, self._cors_origins)

    async def start(self) -> None:
        """Start coalesce + heartbeat loops."""
        if self._tick_task is not None:
            return
        self._stop.clear()
        self._tick_task = asyncio.create_task(
            self._tick_loop(), name="quote-stream-coalesce"
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="quote-stream-heartbeat"
        )

    async def stop(self) -> None:
        """Stop loops and close all clients."""
        self._stop.set()
        for task in (self._tick_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._tick_task = None
        self._heartbeat_task = None
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            # Enqueue while still open so the shutdown frame can leave the queue.
            try:
                if not client.outbound.full():
                    client.outbound.put_nowait(
                        {"type": "error", "code": "shutdown", "message": "hub stop"}
                    )
            except asyncio.QueueFull:
                pass
            client.closed = True

    async def register(self) -> StreamClient:
        """Accept a new client or raise when at capacity."""
        async with self._lock:
            if len(self._clients) >= self._settings.max_clients:
                raise StreamLimitError(
                    "max_clients",
                    f"max concurrent stream clients "
                    f"({self._settings.max_clients}) reached",
                )
            client = StreamClient(
                client_id=str(uuid.uuid4()),
                outbound=asyncio.Queue(maxsize=self._settings.max_queue_depth),
            )
            self._clients[client.client_id] = client
            return client

    async def unregister(self, client_id: str) -> None:
        async with self._lock:
            client = self._clients.pop(client_id, None)
        if client is not None:
            client.closed = True

    def subscribe(self, client: StreamClient, msg: StreamSubscribe) -> None:
        """Replace the client's asset filters with this subscription."""
        specs = msg.resolved_filters()
        new_filters: dict[str, StreamFilter] = {}
        venues_union: set[str] = set()
        for spec in specs:
            assets = list(dict.fromkeys(spec.assets))
            venues_tuple: tuple[str, ...] | None = None
            if spec.venues is not None:
                venues = list(dict.fromkeys(spec.venues))
                venues_tuple = tuple(venues)
                venues_union.update(venues)
            notionals = parse_notionals(spec.notionals)
            for asset in assets:
                # Later specs win on duplicate assets (last-writer).
                new_filters[asset] = StreamFilter(
                    asset=asset,
                    notionals=notionals,
                    venues=venues_tuple,
                    side=spec.side,
                    instrument_type=spec.instrument_type,
                )
        if len(new_filters) > self._settings.max_assets_per_client:
            raise StreamLimitError(
                "max_assets",
                f"max assets per client is {self._settings.max_assets_per_client}",
            )
        if len(venues_union) > self._settings.max_venues_per_client:
            raise StreamLimitError(
                "max_venues",
                f"max venues per client is {self._settings.max_venues_per_client}",
            )
        if not new_filters:
            raise StreamLimitError("empty_subscribe", "subscribe resolved zero assets")
        client.filters = new_filters
        client.need_snapshot = set(new_filters)
        # Drop state for assets no longer subscribed.
        for gone in set(client.last_pairs) - set(new_filters):
            client.last_pairs.pop(gone, None)
            client.last_mid_json.pop(gone, None)

    def request_resnapshot(
        self, client: StreamClient, assets: list[str] | None = None
    ) -> None:
        if assets is None:
            client.need_snapshot = set(client.filters)
            return
        for asset in assets:
            if asset in client.filters:
                client.need_snapshot.add(asset)

    async def publish_once(
        self, *, only_client: StreamClient | None = None
    ) -> None:
        """One coalesce tick (public for tests).

        When ``only_client`` is set (subscribe / resnapshot path), only that
        client's filters are collected — avoids amplifying other viewers' work
        on a new connection.
        """
        async with self._publish_lock:
            await self._publish_once_unlocked(only_client=only_client)

    async def _publish_once_unlocked(
        self, *, only_client: StreamClient | None = None
    ) -> None:
        async with self._lock:
            if only_client is not None:
                clients = (
                    [only_client]
                    if not only_client.closed
                    and only_client.client_id in self._clients
                    else []
                )
            else:
                clients = [c for c in self._clients.values() if not c.closed]
        if not clients:
            return

        # Unique filter keys → one collect each (shared across clients).
        key_to_filter: dict[str, StreamFilter] = {}
        for client in clients:
            for filt in client.filters.values():
                key_to_filter.setdefault(filt.cache_key(), filt)

        async def _collect_one(
            key: str, filt: StreamFilter
        ) -> tuple[str, QuotesPackage | None, BaseException | None]:
            self.collect_calls += 1
            try:
                pkg = await self._aggregator.collect(
                    filt.asset,
                    list(filt.notionals),
                    venues=list(filt.venues) if filt.venues is not None else None,
                    side=filt.side,
                    instrument_type=filt.instrument_type,
                )
                return key, pkg, None
            except Exception as exc:  # noqa: BLE001 — degrade one filter
                logger.exception("stream collect failed for %s: %s", key, exc)
                return key, None, exc

        results = await asyncio.gather(
            *(_collect_one(k, f) for k, f in key_to_filter.items())
        )
        packages: dict[str, QuotesPackage] = {}
        for key, pkg, exc in results:
            if pkg is not None:
                packages[key] = pkg
            elif exc is not None:
                for client in clients:
                    for asset, cf in client.filters.items():
                        if cf.cache_key() == key:
                            client.enqueue(
                                {
                                    "type": "error",
                                    "code": "collect_failed",
                                    "message": str(exc),
                                    "asset": asset,
                                }
                            )

        for client in clients:
            for asset, filt in client.filters.items():
                pkg = packages.get(filt.cache_key())
                if pkg is None:
                    continue
                self._deliver(client, asset, pkg)

    def _deliver(
        self, client: StreamClient, asset: str, package: QuotesPackage
    ) -> None:
        want_snap = asset in client.need_snapshot or asset not in client.last_pairs
        if want_snap:
            client.enqueue(
                {
                    "type": "snapshot",
                    "asset": asset,
                    "data": package_to_wire(package),
                }
            )
            client.last_pairs[asset] = {
                pair_identity_key(p): p for p in package.pairs
            }
            client.last_mid_json[asset] = package.mid.model_dump_json()
            client.need_snapshot.discard(asset)
            return

        prev = client.last_pairs.get(asset, {})
        changed, removed = diff_pairs(prev, package.pairs)
        mid_json = package.mid.model_dump_json()
        mid_changed = client.last_mid_json.get(asset) != mid_json
        if not changed and not removed and not mid_changed:
            return
        client.enqueue(
            {
                "type": "delta",
                "asset": asset,
                "snapshot_id": package.snapshot_id,
                "mid": package.mid.model_dump(mode="json"),
                "pairs": [p.model_dump(mode="json") for p in changed],
                "removed": removed,
                "notionals": [str(n) for n in package.notionals],
            }
        )
        client.last_pairs[asset] = {
            pair_identity_key(p): p for p in package.pairs
        }
        client.last_mid_json[asset] = mid_json

    async def _tick_loop(self) -> None:
        interval = self._settings.coalesce_interval_ms / 1000.0
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            try:
                await self.publish_once()
            except Exception:  # noqa: BLE001 — never kill the loop
                logger.exception("stream coalesce tick failed")

    async def _heartbeat_loop(self) -> None:
        interval = self._settings.heartbeat_interval_sec
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            async with self._lock:
                clients = list(self._clients.values())
            ts = time.time()
            for client in clients:
                client.enqueue(
                    {"type": "heartbeat", "ts": ts}, important=False
                )


