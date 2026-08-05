"""Background pull-only quote poller (WHI-846).

Sweeps AMM DEX and prop AMM venues on a fixed interval, writing the latest
``Quote`` for every ``(venue, asset, tier, side)`` into
:class:`~spread_compare.quote_store.QuoteStore`. ``GET /quotes`` reads the
store; ``POST /simulate`` stays pull-based and shares the same limiters with
reserved headroom (``budget_share`` / ``max_rps``).

Pairing invariant: one ``snapshot_id`` and one mid per asset per sweep. Stored
quotes are never re-priced against a fresher mid at read time.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from spread_compare.adapters.base import VenueAdapter, default_instrument_type
from spread_compare.adapters.registry import get as registry_get
from spread_compare.adapters.registry import is_available, list_venues
from spread_compare.aggregator import (
    assemble_pair,
    effective_instrument_type,
    error_quote,
    quote_with_timeout,
    resolve_mid_with_budget,
)
from spread_compare.mids import MidResolutionError, MidService
from spread_compare.models import (
    PRICED_QUOTE_STATUSES,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    SizeQuotePair,
    VenueClass,
)
from spread_compare.quote_store import (
    QuoteStore,
    QuoteStoreKey,
    StoredQuote,
    default_quote_store,
)
from spread_compare.settings import (
    AggregatorSettings,
    PollerGroupSettings,
    PollerSettings,
    load_aggregator_settings,
    load_jupiter_settings,
    load_poller_settings,
)

logger = logging.getLogger(__name__)

# Jupiter-served Solana prop venues (dexes= filter path).
_JUPITER_VENUES: frozenset[str] = frozenset(
    {"humidifi", "tessera_solana", "bisonfi"}
)
# KyberSwap-served EVM prop venues.
_KYBER_VENUES: frozenset[str] = frozenset({"tessera_base", "tessera_bsc"})

POLLER_GROUP_JUPITER = "jupiter"
POLLER_GROUP_KYBER = "kyber"
POLLER_GROUP_RPC = "rpc"

_SIDES: tuple[Side, ...] = ("buy", "sell")


def group_for_venue(venue: str, venue_class: VenueClass) -> str | None:
    """Map a venue to its upstream sweep group, or None if not poller-served."""
    if venue_class == "amm_dex":
        return POLLER_GROUP_RPC
    if venue in _JUPITER_VENUES:
        return POLLER_GROUP_JUPITER
    if venue in _KYBER_VENUES:
        return POLLER_GROUP_KYBER
    if venue_class == "prop_amm":
        # Unknown prop slug: treat as Jupiter-class pacing (safe default).
        return POLLER_GROUP_JUPITER
    return None


def is_poller_class(
    venue_class: VenueClass, settings: PollerSettings | None = None
) -> bool:
    """True when ``venue_class`` is served from the store on GET /quotes."""
    cfg = settings if settings is not None else load_poller_settings()
    return bool(cfg.enabled) and venue_class in cfg.poller_served_classes


@dataclass(frozen=True, slots=True)
class _WorkItem:
    venue: str
    asset: str
    notional_usd: Decimal
    side: Side
    instrument_type: InstrumentType


def _serve_quote(
    entry_quote: Quote,
    *,
    age_sec: float,
    quote_stale: bool,
) -> Quote:
    """Stamp age / stale flags without changing bps (pairing invariant)."""
    return entry_quote.model_copy(
        update={
            "age_sec": age_sec,
            "quote_stale": quote_stale,
        }
    )


def stamp_stored_quote(
    stored_quote: Quote,
    *,
    age_sec: float,
    max_quote_age_for_best_sec: float,
) -> Quote:
    """Public helper for aggregator store reads (tests + collect path)."""
    return _serve_quote(
        stored_quote,
        age_sec=age_sec,
        quote_stale=age_sec > max_quote_age_for_best_sec,
    )


class PullQuotePoller:
    """Background scheduler: one asyncio task per configured sweep group."""

    def __init__(
        self,
        mid_service: MidService,
        *,
        store: QuoteStore | None = None,
        settings: PollerSettings | None = None,
        aggregator_settings: AggregatorSettings | None = None,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], object] | None = None,
    ) -> None:
        self._mids = mid_service
        self._store = store if store is not None else default_quote_store()
        self._settings = settings if settings is not None else load_poller_settings()
        self._agg = (
            aggregator_settings
            if aggregator_settings is not None
            else load_aggregator_settings()
        )
        self._clock = clock or time.monotonic
        self._wall = wall_clock or (lambda: datetime.now(tz=UTC))
        self._sleep = sleep  # injected for tests; default asyncio.sleep
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._started = False
        # Per-group in-flight guard (WHI-864): never run two sweeps concurrently.
        self._sweep_in_progress: dict[str, bool] = {}
        # Diagnostics for tests / PR verification / WHI-819 monitor.
        self.sweep_counts: dict[str, int] = {}
        # Skipped because a previous sweep was still running (or schedule overrun).
        self.sweep_skips: dict[str, int] = {}
        self.upstream_calls: int = 0
        # Monotonic timestamp of last completed sweep per group (None = never).
        self.last_sweep_completed_mono: dict[str, float] = {}
        # Wall clock of last completed sweep (for /health human display).
        self.last_sweep_completed_at: dict[str, datetime] = {}

    @property
    def store(self) -> QuoteStore:
        return self._store

    @property
    def settings(self) -> PollerSettings:
        return self._settings

    def group_settings(self, group: str) -> PollerGroupSettings | None:
        return self._settings.groups.get(group)

    async def start(self) -> None:
        """Spawn group loops. Idempotent; no-op when poller disabled."""
        if self._started:
            return
        self._started = True
        self._stop.clear()
        if not self._settings.enabled:
            logger.info("pull quote poller disabled (config/poller.yaml enabled=false)")
            return
        for name, group_cfg in self._settings.groups.items():
            task = asyncio.create_task(
                self._group_loop(name, group_cfg),
                name=f"poller-{name}",
            )
            self._tasks.append(task)
        logger.info(
            "pull quote poller started groups=%s",
            sorted(self._settings.groups),
        )

    async def stop(self) -> None:
        """Cancel group loops and wait for them to exit."""
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._started = False
        logger.info("pull quote poller stopped")

    async def _group_loop(self, group: str, cfg: PollerGroupSettings) -> None:
        """Run sweeps until stop; failures never kill the loop (WHI-840 style).

        Fixed-period schedule: each tick is due at ``next_due``. If a sweep is
        still in flight when the next tick arrives (should not happen with a
        single task, but guards concurrent ``run_sweep`` callers), the tick is
        **skipped** and counted. If a sweep overruns ``interval_sec``, missed
        ticks are skipped rather than stacking back-to-back (WHI-864).
        """
        next_due = self._clock()
        while not self._stop.is_set():
            now = self._clock()
            wait = next_due - now
            if wait > 0:
                try:
                    await self._async_sleep(wait)
                except asyncio.CancelledError:
                    raise
            if self._stop.is_set():
                break
            try:
                # run_sweep skips (returns None) when already in flight —
                # that is the sole overlap guard (WHI-864).
                await self.run_sweep(group)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep other groups alive
                logger.exception("poller group %s sweep failed", group)
            # Advance schedule from the planned slot; skip any fully elapsed
            # intervals so a slow sweep cannot collapse the period to zero.
            next_due += cfg.interval_sec
            now = self._clock()
            skipped_ticks = 0
            while next_due <= now:
                next_due += cfg.interval_sec
                skipped_ticks += 1
            if skipped_ticks:
                self._mark_sweep_skipped(
                    group,
                    reason="overrun",
                    n=skipped_ticks,
                )

    async def run_sweep(self, group: str) -> str | None:
        """Execute one sweep for ``group``. Returns the sweep ``snapshot_id``.

        Returns ``None`` when a sweep is already in flight for ``group``
        (WHI-864 non-overlap). Public so tests can drive a single pass without
        the background loop.
        """
        cfg = self._settings.groups.get(group)
        if cfg is None:
            raise KeyError(f"unknown poller group: {group!r}")

        if self._sweep_in_progress.get(group, False):
            self._mark_sweep_skipped(group, reason="in_flight")
            return None
        self._sweep_in_progress[group] = True
        try:
            return await self._run_sweep_body(group, cfg)
        finally:
            self._sweep_in_progress[group] = False

    async def _run_sweep_body(self, group: str, cfg: PollerGroupSettings) -> str:
        snapshot_id = str(uuid.uuid4())
        work = self._plan_work(group, cfg)
        if not work:
            logger.debug("poller group %s: no work items", group)
            self._mark_sweep_complete(group)
            return snapshot_id

        # One mid per asset for this snapshot (pairing invariant).
        assets = sorted({item.asset for item in work})
        mids: dict[str, ReferenceMid] = {}
        for asset in assets:
            try:
                mids[asset] = await resolve_mid_with_budget(
                    self._mids,
                    asset,
                    snapshot_id=snapshot_id,
                    venue_timeout_sec=self._agg.venue_timeout_sec,
                )
            except MidResolutionError as exc:
                logger.warning(
                    "poller group %s: mid unavailable for %s: %s",
                    group,
                    asset,
                    exc,
                )

        delay = self._inter_call_delay(group, cfg, n_calls=len(work))
        # Deadline pacing: schedule starts every ``delay`` seconds so call
        # latency is absorbed into the budget instead of added after it
        # (otherwise wall-clock sweep ≈ n×(delay+latency) and rows age past
        # max_quote_age_for_best_sec before the next sample).
        next_at = self._clock()
        for item in work:
            if self._stop.is_set():
                break
            now = self._clock()
            wait = next_at - now
            if wait > 0:
                await self._async_sleep(wait)
            mid = mids.get(item.asset)
            if mid is None:
                self._record_mid_unavailable(item, group=group, cfg=cfg)
            else:
                await self._sample_one(item, mid=mid, group=group, cfg=cfg)
            next_at = max(next_at + delay, self._clock()) if delay > 0 else self._clock()

        self._mark_sweep_complete(group)
        logger.info(
            "poller group %s sweep done snapshot_id=%s items=%s",
            group,
            snapshot_id,
            len(work),
        )
        return snapshot_id

    def _mark_sweep_complete(self, group: str) -> None:
        """Record diagnostics used by WHI-819 sweep-stale alerts."""
        now_mono = self._clock()
        self.sweep_counts[group] = self.sweep_counts.get(group, 0) + 1
        self.last_sweep_completed_mono[group] = now_mono
        self.last_sweep_completed_at[group] = self._wall()

    def _mark_sweep_skipped(
        self, group: str, *, reason: str, n: int = 1
    ) -> None:
        """Count and log a skipped sweep tick (visible on /health)."""
        if n < 1:
            return
        self.sweep_skips[group] = self.sweep_skips.get(group, 0) + n
        logger.warning(
            "poller group %s skipped %s sweep(s) reason=%s total_skips=%s",
            group,
            n,
            reason,
            self.sweep_skips[group],
        )

    def _plan_work(self, group: str, cfg: PollerGroupSettings) -> list[_WorkItem]:
        """Enumerate (venue, asset, tier, side) for venues in this group."""
        notionals = list(cfg.notionals_usd)
        items: list[_WorkItem] = []
        for slug in list_venues():
            try:
                adapter = registry_get(slug)
            except KeyError:
                continue
            if not is_poller_class(adapter.venue_class, self._settings):
                continue
            g = group_for_venue(adapter.venue, adapter.venue_class)
            if g != group:
                continue
            # Startup-failed venues stay in the plan; quote_with_timeout
            # writes not_initialized rows so the store is not empty.
            itype = default_instrument_type(adapter.venue_class)
            try:
                assets = adapter.supported_assets(instrument_type=itype)
            except Exception:  # noqa: BLE001
                logger.exception("poller: supported_assets failed for %s", slug)
                continue
            for asset in assets:
                asset_key = asset.upper()
                for notional in notionals:
                    for side in _SIDES:
                        items.append(
                            _WorkItem(
                                venue=slug,
                                asset=asset_key,
                                notional_usd=notional,
                                side=side,
                                instrument_type=itype,
                            )
                        )
        # Stable order: venue, asset, notional, side — predictable pacing.
        items.sort(
            key=lambda w: (w.venue, w.asset, w.notional_usd, w.side)
        )
        return items

    def _inter_call_delay(
        self, group: str, cfg: PollerGroupSettings, *, n_calls: int
    ) -> float:
        """Seconds between call starts so avg RPS ≤ the group budget.

        Pace at the budget cap (``budget_share`` / ``max_rps``), not stretched
        to fill ``interval_sec`` — the loop idles the remainder so real
        headroom exists for RTT / 429 / ``/simulate`` (WHI-864). When no cap
        is configured, spread work evenly across the interval.
        """
        if n_calls <= 1:
            return 0.0
        caps: list[float] = []
        if cfg.max_rps is not None:
            caps.append(cfg.max_rps)
        if cfg.budget_share is not None:
            capacity = self._group_capacity_rps(group)
            if capacity is not None:
                caps.append(capacity * cfg.budget_share)
        if caps:
            target_rps = min(caps)
        else:
            target_rps = n_calls / cfg.interval_sec
        if target_rps <= 0:
            return cfg.interval_sec
        return 1.0 / target_rps

    def _group_capacity_rps(self, group: str) -> float | None:
        """Known upstream capacity for budget_share calculation."""
        if group == POLLER_GROUP_JUPITER:
            jup = load_jupiter_settings()
            # Match prop_jupiter active mode: keyless when no API key is set.
            import os

            has_key = bool(os.environ.get("JUPITER_API_KEY", "").strip())
            capacity = jup.keyed_capacity if has_key else jup.keyless_capacity
            # window_sec is the refill window → sustained RPS = capacity/window.
            return float(capacity) / float(jup.window_sec)
        return None

    async def _sample_one(
        self,
        item: _WorkItem,
        *,
        mid: ReferenceMid,
        group: str,
        cfg: PollerGroupSettings,
    ) -> None:
        adapter = registry_get(item.venue)
        timeout = self._agg.timeout_for(adapter.venue_class)
        self.upstream_calls += 1
        quote = await quote_with_timeout(
            adapter,
            asset=item.asset,
            side=item.side,
            notional_usd=item.notional_usd,
            mid=mid,
            instrument_type=item.instrument_type,
            timeout=timeout,
            log_tag=f"poller/{group}",
        )
        key = QuoteStoreKey(
            venue=item.venue,
            asset=item.asset,
            instrument_type=item.instrument_type,
            notional_usd=item.notional_usd,
            side=item.side,
        )
        # Adapter-returned non-ok (unsupported_asset, no_quote, …) is still a
        # successful *sample* — we got a definitive answer for this key.
        # Only transport failures (error / rate_limited) keep previous values.
        if quote.status in ("error", "rate_limited"):
            self._record_failure_from_quote(
                key, quote, group=group, cfg=cfg, mid=mid
            )
            return
        self._store.put(
            key,
            quote,
            group=group,
            success=True,
            observed_at=self._wall(),
        )

    def _record_mid_unavailable(
        self,
        item: _WorkItem,
        *,
        group: str,
        cfg: PollerGroupSettings,
    ) -> None:
        """Keep previous value or expire; cannot build a Quote without a mid."""
        key = QuoteStoreKey(
            venue=item.venue,
            asset=item.asset,
            instrument_type=item.instrument_type,
            notional_usd=item.notional_usd,
            side=item.side,
        )
        prev = self._store.get(key)
        if prev is None:
            return
        degraded = self._maybe_expire(prev, cfg=cfg, quote=prev.quote)
        if degraded is not None:
            self._store.put(
                key,
                degraded,
                group=group,
                success=False,
            )
        else:
            self._store.put(
                key,
                prev.quote,
                group=group,
                success=False,
            )

    def _record_failure_from_quote(
        self,
        key: QuoteStoreKey,
        failed: Quote,
        *,
        group: str,
        cfg: PollerGroupSettings,
        mid: ReferenceMid,
    ) -> None:
        prev = self._store.get(key)
        if prev is None:
            # Cold miss: store the error so GET /quotes has a row.
            self._store.put(
                key,
                failed,
                group=group,
                success=False,
                observed_at=self._wall(),
            )
            return
        age = self._clock() - prev.last_success_mono
        if age > cfg.max_stale_sec:
            # Past max age: replace with error / rate_limited.
            self._store.put(
                key,
                failed,
                group=group,
                success=False,
                observed_at=self._wall(),
            )
            return
        # Keep previous value; last_success_mono preserved (success=False).
        self._store.put(
            key,
            prev.quote,
            group=group,
            success=False,
            observed_at=prev.observed_at,
        )

    def _maybe_expire(
        self,
        prev: StoredQuote,
        *,
        cfg: PollerGroupSettings,
        quote: Quote,
    ) -> Quote | None:
        """Return an error quote when past max_stale_sec, else None to keep."""
        age = self._clock() - prev.last_success_mono
        if age <= cfg.max_stale_sec:
            return None
        return error_quote(
            mid=ReferenceMid(
                snapshot_id=quote.snapshot_id,
                asset=quote.asset,
                mid=quote.mid,
                mid_source=quote.mid_source,
                timestamp=quote.mid_timestamp,
            ),
            venue=quote.venue,
            asset=quote.asset,
            side=quote.side,
            notional_usd=quote.notional_usd,
            instrument_type=quote.instrument_type,
            error_code="stale",
            error_message=(
                f"quote older than max_stale_sec={cfg.max_stale_sec} "
                f"(age≈{age:.1f}s)"
            ),
            timestamp=self._wall(),
        )

    async def _async_sleep(self, seconds: float) -> None:
        if self._sleep is not None:
            result = self._sleep(seconds)
            if asyncio.iscoroutine(result):
                await result
            return
        await asyncio.sleep(seconds)

def not_yet_sampled_quote(
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
) -> Quote:
    """Row for a poller venue that has not produced a sample yet."""
    return error_quote(
        mid=mid,
        venue=venue,
        asset=asset,
        side=side,
        notional_usd=notional_usd,
        instrument_type=instrument_type,
        error_code="not_yet_sampled",
        error_message=f"{venue}: pull poller has not sampled this key yet",
        timestamp=datetime.now(tz=UTC),
    )


def pair_from_store(
    store: QuoteStore,
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    instrument_type: InstrumentType | None,
    notional_usd: Decimal,
    sides: Sequence[Side],
    poller_settings: PollerSettings,
    stale_threshold_sec: float,
    adapter: VenueAdapter,
    clock: Callable[[], float] | None = None,
) -> SizeQuotePair:
    """Build a store-backed SizeQuotePair for the aggregator.

    Uses the package ``mid`` only for *missing* legs (not_yet_sampled /
    not_initialized). Present legs keep their sweep mid and snapshot_id —
    ``assemble_pair`` is adjusted via direct construction when snapshot ids
    differ from the package mid.
    """
    mono = clock or time.monotonic
    itype = effective_instrument_type(adapter.venue_class, instrument_type)
    asset_key = asset.upper()
    now = mono()
    buy: Quote | None = None
    sell: Quote | None = None
    # Freshest *stored* sample wins pair identity (not first side in order).
    # A failed refresh keeps the old snapshot_id; the surviving leg from the
    # current sweep must not be dropped in favour of the stale one (WHI-846).
    freshest: tuple[float, Quote] | None = None

    for side in sides:
        key = QuoteStoreKey(
            venue=venue,
            asset=asset_key,
            instrument_type=itype,
            notional_usd=notional_usd,
            side=side,
        )
        entry = store.get(key)
        if entry is None:
            if not is_available(venue):
                from spread_compare.aggregator import not_initialized_quote

                q = not_initialized_quote(
                    mid=mid,
                    venue=venue,
                    asset=asset_key,
                    side=side,
                    notional_usd=notional_usd,
                    instrument_type=itype,
                )
            else:
                q = not_yet_sampled_quote(
                    mid=mid,
                    venue=venue,
                    asset=asset_key,
                    side=side,
                    notional_usd=notional_usd,
                    instrument_type=itype,
                )
        else:
            gcfg = poller_settings.groups.get(entry.group)
            max_best = (
                gcfg.max_quote_age_for_best_sec if gcfg is not None else float("inf")
            )
            age = max(0.0, now - entry.observed_mono)
            q = stamp_stored_quote(
                entry.quote,
                age_sec=age,
                max_quote_age_for_best_sec=max_best,
            )
            if freshest is None or entry.observed_mono > freshest[0]:
                freshest = (entry.observed_mono, q)

        if side == "buy":
            buy = q
        else:
            sell = q

    # SizeQuotePair requires legs to share snapshot_id with the pair.
    # When both stored legs share a sweep, use that. When they disagree
    # (one kept across a failed refresh of the other), drop the *older*
    # priced leg rather than silently rewriting mid under a foreign
    # snapshot_id (WHI-799 §6.2 inv. 3 / pairing invariant).
    if freshest is not None:
        stored_ref = freshest[1]
        pair_snap = stored_ref.snapshot_id
        pair_mid_value = stored_ref.mid
        pair_mid_source = stored_ref.mid_source
        pair_mid_ts = stored_ref.mid_timestamp

        def _align(q: Quote | None) -> Quote | None:
            if q is None:
                return None
            if q.snapshot_id == pair_snap and q.mid == pair_mid_value:
                return q
            # Placeholder / foreign-snapshot legs: only rewrite when they
            # carry no priced bps (error / not_yet_sampled). Priced foreign
            # legs are dropped so we never mix two mids under one id.
            if q.status in PRICED_QUOTE_STATUSES and q.snapshot_id != pair_snap:
                return None
            return q.model_copy(
                update={
                    "snapshot_id": pair_snap,
                    "mid": pair_mid_value,
                    "mid_source": pair_mid_source,
                    "mid_timestamp": pair_mid_ts,
                }
            )

        buy = _align(buy)
        sell = _align(sell)
        pair_mid = ReferenceMid(
            snapshot_id=pair_snap,
            asset=asset_key,
            mid=pair_mid_value,
            mid_source=pair_mid_source,
            timestamp=pair_mid_ts,
        )
        # Re-fill a missing leg with a truthful error (not not_yet_sampled —
        # the key was sampled, but under a different sweep mid).
        if "buy" in sides and buy is None:
            buy = error_quote(
                mid=pair_mid,
                venue=venue,
                asset=asset_key,
                side="buy",
                notional_usd=notional_usd,
                instrument_type=itype,
                error_code="snapshot_mismatch",
                error_message=(
                    f"{venue}: buy leg kept under a prior sweep snapshot; "
                    "serving fresher sell only"
                ),
            )
        if "sell" in sides and sell is None:
            sell = error_quote(
                mid=pair_mid,
                venue=venue,
                asset=asset_key,
                side="sell",
                notional_usd=notional_usd,
                instrument_type=itype,
                error_code="snapshot_mismatch",
                error_message=(
                    f"{venue}: sell leg kept under a prior sweep snapshot; "
                    "serving fresher buy only"
                ),
            )
    else:
        pair_mid = mid

    return assemble_pair(
        mid=pair_mid,
        venue=venue,
        asset=asset_key,
        instrument_type=itype,
        notional_usd=notional_usd,
        buy=buy if "buy" in sides else None,
        sell=sell if "sell" in sides else None,
        top_of_book=None,
        stale_threshold_sec=stale_threshold_sec,
    )
