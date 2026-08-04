"""Cross-venue quote aggregation (WHI-807).

Resolves one reference mid, fans out to adapters concurrently with per-venue
timeouts, assembles :class:`~spread_compare.models.SizeQuotePair` rows, and
optionally caches the response. **Never recomputes adapter bps** (WHI-799 §4.5).
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
from typing import Literal

from spread_compare.adapters.base import (
    AdapterError,
    AdapterRateLimitedError,
    VenueAdapter,
    default_instrument_type,
)
from spread_compare.adapters.registry import get as registry_get
from spread_compare.adapters.registry import is_available, list_venues
from spread_compare.budget import quote_deadline
from spread_compare.costs import (
    half_spread_bps,
    round_trip_spread_bps,
    round_trip_total_cost_bps,
)
from spread_compare.mids import MidResolutionError, MidService, is_mid_stale
from spread_compare.models import (
    NOTIONAL_TIERS_USD,
    PRICED_QUOTE_STATUSES,
    FeeBreakdown,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    SizeQuotePair,
    TopOfBook,
    VenueClass,
)
from spread_compare.settings import AggregatorSettings, MidSettings, load_aggregator_settings

logger = logging.getLogger(__name__)

_ORDERBOOK_CLASSES: frozenset[VenueClass] = frozenset({"cex", "perp_dex"})

# instrument_type overrides that each venue class can honor (WHI-799 §7).
# Public so simulator (WHI-814) shares the same map — do not fork.
CLASS_INSTRUMENTS: dict[VenueClass, frozenset[InstrumentType]] = {
    "cex": frozenset({"spot", "perp"}),
    "perp_dex": frozenset({"perp"}),
    "amm_dex": frozenset({"amm_pool"}),
    "prop_amm": frozenset({"prop_amm"}),
}


def effective_instrument_type(
    venue_class: VenueClass,
    requested: InstrumentType | None,
) -> InstrumentType:
    """Apply filter only when the venue class can serve that instrument type."""
    if requested is not None and requested in CLASS_INSTRUMENTS[venue_class]:
        return requested
    return default_instrument_type(venue_class)


def _append_raw_ref(existing: str | None, tag: str) -> str:
    """Append a degradation tag without clobbering an adapter-supplied raw_ref."""
    if existing:
        return f"{existing};{tag}"
    return tag


class AggregatorError(Exception):
    """Base aggregator failure."""


class InvalidNotionalError(AggregatorError):
    """Notional is not one of the four WHI-799 §4.1 tiers."""


class UnknownVenueError(AggregatorError):
    """Requested venue slug is not a registered adapter."""


@dataclass(frozen=True, slots=True)
class QuotesPackage:
    """One aggregation snapshot returned by :meth:`QuoteAggregator.collect`.

    ``notionals`` is the full requested tier set (len ≥ 1). ``notional_usd`` is
    the sole tier when len==1, else the first (sorted) tier — kept for single-
    notional response back-compat. All pairs share ``snapshot_id`` / ``mid``.
    """

    snapshot_id: str
    asset: str
    notional_usd: Decimal
    mid: ReferenceMid
    pairs: list[SizeQuotePair]
    notionals: tuple[Decimal, ...] = ()


@dataclass(slots=True)
class _CacheEntry:
    expires_at: float
    package: QuotesPackage


@dataclass(frozen=True, slots=True)
class _TobOutcome:
    """Result of a TOB fetch.

    ``book`` is set only on success. ``failed`` is True when an orderbook venue
    raised/timeout (WHI-799 §6.3 — never conflate with AMM's intentional None).
    """

    book: TopOfBook | None
    failed: bool
    error_code: str | None = None
    error_message: str | None = None


def _error_fee_breakdown() -> FeeBreakdown:
    return FeeBreakdown(
        embedded_in_price=False,
        fee_tier=None,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=None,
    )


def error_quote(
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    error_code: str,
    error_message: str,
    timestamp: datetime | None = None,
    status: Literal["error", "rate_limited"] = "error",
) -> Quote:
    """Build a non-ok Quote row (WHI-799 §6.6 / WHI-844 ``rate_limited``)."""
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        mid_stale=False,
        fee_breakdown=_error_fee_breakdown(),
        timestamp=timestamp or datetime.now(tz=UTC),
        status=status,
        error_code=error_code,
        error_message=error_message,
    )


def rate_limited_quote(
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    error_message: str,
    timestamp: datetime | None = None,
) -> Quote:
    """Build a ``status=rate_limited`` Quote row (WHI-844 / WHI-799 §6.1)."""
    return error_quote(
        mid=mid,
        venue=venue,
        asset=asset,
        side=side,
        notional_usd=notional_usd,
        instrument_type=instrument_type,
        error_code="rate_limited",
        error_message=error_message,
        timestamp=timestamp,
        status="rate_limited",
    )


def not_initialized_message(venue: str) -> str:
    """Canonical error_message for WHI-840 not_initialized rows."""
    return f"{venue}: adapter startup did not complete"


def not_initialized_quote(
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
) -> Quote:
    """``error_code=not_initialized`` row for venues whose startup() failed (WHI-840)."""
    return error_quote(
        mid=mid,
        venue=venue,
        asset=asset,
        side=side,
        notional_usd=notional_usd,
        instrument_type=instrument_type,
        error_code="not_initialized",
        error_message=not_initialized_message(venue),
    )


async def resolve_mid_with_budget(
    mid_service: MidService,
    asset: str,
    *,
    snapshot_id: str,
    venue_timeout_sec: float,
) -> ReferenceMid:
    """Resolve a reference mid with a timeout derived from per-venue budget.

    Mid resolution fans out over HTTP sources; do not let it stall past a
    multiple of ``venue_timeout_sec``. Shared by aggregator and simulator.
    """
    mid_timeout = max(venue_timeout_sec * 4, 10.0)
    try:
        async with asyncio.timeout(mid_timeout):
            return await mid_service.resolve(asset, snapshot_id=snapshot_id)
    except TimeoutError as exc:
        raise MidResolutionError(
            f"mid resolution timed out after {mid_timeout}s for {asset}"
        ) from exc


async def quote_with_timeout(
    adapter: VenueAdapter,
    *,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    timeout: float,
    log_tag: str = "",
) -> Quote:
    """Call ``get_quote`` with a per-venue timeout; degrade to ``status=error``.

    Shared by :class:`QuoteAggregator` and :class:`~spread_compare.simulator.TradeSimulator`.
    Venues that failed ``startup()`` return ``error_code=not_initialized`` (WHI-840)
    rather than ``unsupported_asset`` from empty warm-up caches.
    """
    suffix = f" {log_tag}" if log_tag else ""
    if not is_available(adapter.venue):
        logger.warning(
            "venue %s not initialized; returning not_initialized%s",
            adapter.venue,
            suffix,
        )
        return not_initialized_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
        )
    try:
        # Bind remaining budget so limiters / 429 sleeps can fail fast (WHI-844).
        with quote_deadline(timeout):
            async with asyncio.timeout(timeout):
                return await adapter.get_quote(
                    asset,
                    side,
                    notional_usd,
                    mid=mid,
                    instrument_type=instrument_type,
                )
    except TimeoutError:
        logger.warning(
            "venue %s get_quote timed out after %ss (%s %s)%s",
            adapter.venue,
            timeout,
            side,
            asset,
            suffix,
        )
        return error_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            error_code="timeout",
            error_message=f"get_quote timed out after {timeout}s",
        )
    except AdapterRateLimitedError as exc:
        logger.warning(
            "venue %s rate limited%s: %s", adapter.venue, suffix, exc
        )
        return rate_limited_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            error_message=str(exc),
        )
    except AdapterError as exc:
        logger.warning("venue %s get_quote error%s: %s", adapter.venue, suffix, exc)
        return error_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            error_code="adapter_error",
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — degrade per venue, never whole package
        logger.exception("venue %s get_quote unexpected error%s", adapter.venue, suffix)
        return error_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            error_code="adapter_error",
            error_message=f"{type(exc).__name__}: {exc}",
        )


def apply_mid_stale(quote: Quote, *, stale_threshold_sec: float) -> Quote:
    """Stamp ``mid_stale`` per WHI-799 §3.2 without changing any bps fields."""
    stale = is_mid_stale(
        quote.timestamp,
        quote.mid_timestamp,
        stale_threshold_sec=stale_threshold_sec,
    )
    if quote.mid_stale == stale:
        return quote
    return quote.model_copy(update={"mid_stale": stale})


def assemble_pair(
    *,
    mid: ReferenceMid,
    venue: str,
    asset: str,
    instrument_type: InstrumentType,
    notional_usd: Decimal,
    buy: Quote | None,
    sell: Quote | None,
    top_of_book: TopOfBook | None,
    stale_threshold_sec: float,
) -> SizeQuotePair:
    """Build a SizeQuotePair from legs; sum bps only via costs helpers (WHI-799 §4.6)."""
    if buy is not None:
        buy = apply_mid_stale(buy, stale_threshold_sec=stale_threshold_sec)
    if sell is not None:
        sell = apply_mid_stale(sell, stale_threshold_sec=stale_threshold_sec)

    # Priced statuses keep numbers readable (WHI-845 excessive_impact); only
    # status=ok remains §5.2 best / heat eligible (FE gates on status separately).
    def _priced(quote: Quote | None, value: Decimal | None) -> Decimal | None:
        if quote is None or quote.status not in PRICED_QUOTE_STATUSES:
            return None
        return value

    buy_spread = _priced(buy, buy.spread_bps if buy is not None else None)
    sell_spread = _priced(sell, sell.spread_bps if sell is not None else None)
    buy_total = _priced(buy, buy.total_cost_bps if buy is not None else None)
    sell_total = _priced(sell, sell.total_cost_bps if sell is not None else None)

    return SizeQuotePair(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        notional_usd=notional_usd,
        buy=buy,
        sell=sell,
        round_trip_spread_bps=round_trip_spread_bps(buy_spread, sell_spread),
        half_spread_bps=half_spread_bps(buy_spread, sell_spread),
        round_trip_total_cost_bps=round_trip_total_cost_bps(buy_total, sell_total),
        top_of_book=top_of_book,
    )


class QuoteAggregator:
    """Fan-out orchestrator. Does not own adapter lifecycle (registry/lifespan does)."""

    def __init__(
        self,
        mid_service: MidService,
        *,
        aggregator_settings: AggregatorSettings | None = None,
        mid_settings: MidSettings | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._mids = mid_service
        self._agg = (
            aggregator_settings
            if aggregator_settings is not None
            else load_aggregator_settings()
        )
        self._mid_settings = mid_settings if mid_settings is not None else mid_service.settings
        self._clock = clock or time.monotonic
        self._cache: dict[str, _CacheEntry] = {}
        # Single-flight: concurrent collect() for the same cache key share one fan-out.
        self._inflight: dict[str, asyncio.Future[QuotesPackage]] = {}
        # Strong refs so detached fan-out tasks are not GC'd mid-flight (WHI-844).
        self._inflight_tasks: set[asyncio.Task[None]] = set()

    @property
    def mid_service(self) -> MidService:
        return self._mids

    def clear_cache(self) -> None:
        """Drop cached packages. In-flight single-flight work is left alone
        (still fills the cache on completion); call sites that need a hard
        reset should also wait for outstanding collects to finish.
        """
        self._cache.clear()

    async def collect(
        self,
        asset: str,
        notional_usd: Decimal | Sequence[Decimal],
        *,
        venues: Sequence[str] | None = None,
        side: Side | None = None,
        instrument_type: InstrumentType | None = None,
        snapshot_id: str | None = None,
        use_cache: bool = True,
    ) -> QuotesPackage:
        """Aggregate quotes for one asset across one or more notional tiers.

        ``notional_usd`` may be a single Decimal (legacy) or a sequence of
        §4.1 tiers. Multi-tier packages share one ``snapshot_id`` and mid
        (WHI-843).

        Raises:
            InvalidNotionalError: any notional not in §4.1 tiers, or empty list.
            UnknownVenueError: filter names an unregistered adapter.
            MidResolutionError: mid unavailable (caller maps to HTTP 503).
        """
        notionals = self._normalize_notionals(notional_usd)

        asset_key = asset.upper()
        venue_slugs = self._resolve_venues(venues)
        sides: tuple[Side, ...] = (side,) if side is not None else ("buy", "sell")

        # Explicit snapshot_id (collector path) must never return a cached foreign id.
        cache_eligible = (
            use_cache
            and snapshot_id is None
            and self._agg.response_cache_ttl_sec > 0
        )
        cache_key = self._cache_key(
            asset_key, notionals, venue_slugs, sides, instrument_type
        )
        if cache_eligible:
            hit = self._lookup_cache(
                cache_key,
                asset_key=asset_key,
                notionals=notionals,
                venue_slugs=venue_slugs,
                sides=sides,
                instrument_type=instrument_type,
            )
            if hit is not None:
                return hit
            # Coalesce in-flight work for the same package key (WHI-844).
            # Fan-out runs in a detached task so one client disconnect does not
            # cancel the shared work for other waiters.
            existing = self._inflight.get(cache_key)
            if existing is not None:
                return await asyncio.shield(existing)

            loop = asyncio.get_running_loop()
            future: asyncio.Future[QuotesPackage] = loop.create_future()
            self._inflight[cache_key] = future

            async def _run() -> None:
                try:
                    package = await self._collect_uncached(
                        asset_key=asset_key,
                        notionals=notionals,
                        venue_slugs=venue_slugs,
                        sides=sides,
                        instrument_type=instrument_type,
                        snapshot_id=snapshot_id,
                    )
                    self._store_cache(package, venue_slugs, sides, instrument_type)
                    if not future.done():
                        future.set_result(package)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)
                except BaseException as exc:
                    # CancelledError etc.: still unblock waiters, then re-raise.
                    if not future.done():
                        future.set_exception(exc)
                    raise
                finally:
                    if self._inflight.get(cache_key) is future:
                        del self._inflight[cache_key]

            task = asyncio.create_task(_run())
            self._inflight_tasks.add(task)
            task.add_done_callback(self._inflight_tasks.discard)
            return await asyncio.shield(future)

        return await self._collect_uncached(
            asset_key=asset_key,
            notionals=notionals,
            venue_slugs=venue_slugs,
            sides=sides,
            instrument_type=instrument_type,
            snapshot_id=snapshot_id,
        )

    @staticmethod
    def _normalize_notionals(
        notional_usd: Decimal | Sequence[Decimal],
    ) -> tuple[Decimal, ...]:
        if isinstance(notional_usd, Decimal):
            raw = [notional_usd]
        else:
            raw = [Decimal(n) for n in notional_usd]
        if not raw:
            raise InvalidNotionalError("at least one notional is required")
        # Stable order = §4.1 tier order; reject duplicates and unknowns.
        seen: set[Decimal] = set()
        ordered: list[Decimal] = []
        for n in raw:
            if n not in NOTIONAL_TIERS_USD:
                raise InvalidNotionalError(
                    f"notional_usd must be one of {list(NOTIONAL_TIERS_USD)}, got {n}"
                )
            if n in seen:
                continue
            seen.add(n)
            ordered.append(n)
        ordered.sort()
        return tuple(ordered)

    async def _collect_uncached(
        self,
        *,
        asset_key: str,
        notionals: tuple[Decimal, ...],
        venue_slugs: Sequence[str],
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
        snapshot_id: str | None,
    ) -> QuotesPackage:
        snap = snapshot_id or str(uuid.uuid4())
        mid = await resolve_mid_with_budget(
            self._mids,
            asset_key,
            snapshot_id=snap,
            venue_timeout_sec=self._agg.venue_timeout_sec,
        )

        if len(notionals) == 1:
            pairs_nested = await asyncio.gather(
                *(
                    self._collect_venue(
                        slug,
                        asset=asset_key,
                        notional_usd=notionals[0],
                        mid=mid,
                        sides=sides,
                        instrument_type=instrument_type,
                    )
                    for slug in venue_slugs
                )
            )
            pairs = list(pairs_nested)
        else:
            # Multi-tier: one mid/snapshot; orderbook venues batch-walk one book.
            pairs_lists = await asyncio.gather(
                *(
                    self._collect_venue_multi(
                        slug,
                        asset=asset_key,
                        notionals=notionals,
                        mid=mid,
                        sides=sides,
                        instrument_type=instrument_type,
                    )
                    for slug in venue_slugs
                )
            )
            pairs = [p for group in pairs_lists for p in group]

        return QuotesPackage(
            snapshot_id=snap,
            asset=asset_key,
            notional_usd=notionals[0],
            mid=mid,
            pairs=pairs,
            notionals=notionals,
        )

    def _resolve_venues(self, venues: Sequence[str] | None) -> list[str]:
        if not venues:
            return list_venues()
        resolved: list[str] = []
        for slug in venues:
            try:
                registry_get(slug)
            except KeyError as exc:
                raise UnknownVenueError(f"unknown venue: {slug!r}") from exc
            resolved.append(slug)
        return resolved

    def _cache_key(
        self,
        asset: str,
        notionals: Sequence[Decimal],
        venues: Sequence[str],
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> str:
        return "|".join(
            [
                asset,
                ",".join(str(n) for n in notionals),
                ",".join(venues),
                ",".join(sides),
                instrument_type or "",
            ]
        )

    def _lookup_cache(
        self,
        exact_key: str,
        *,
        asset_key: str,
        notionals: tuple[Decimal, ...],
        venue_slugs: Sequence[str],
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> QuotesPackage | None:
        """Exact hit, or single-tier subset of a multi-tier cached package (WHI-843)."""
        now = self._clock()
        hit = self._cache.get(exact_key)
        if hit is not None and hit.expires_at > now:
            return hit.package

        # Single-tier request may slice a multi-tier package with the same filters.
        if len(notionals) != 1:
            return None
        want = notionals[0]
        venues_sig = ",".join(venue_slugs)
        sides_sig = ",".join(sides)
        itype_sig = instrument_type or ""
        prefix = f"{asset_key}|"
        suffix = f"|{venues_sig}|{sides_sig}|{itype_sig}"
        for key, entry in self._cache.items():
            if entry.expires_at <= now:
                continue
            if not (key.startswith(prefix) and key.endswith(suffix)):
                continue
            pkg = entry.package
            if want not in pkg.notionals:
                continue
            if len(pkg.notionals) <= 1:
                continue
            filtered = [p for p in pkg.pairs if p.notional_usd == want]
            return QuotesPackage(
                snapshot_id=pkg.snapshot_id,
                asset=pkg.asset,
                notional_usd=want,
                mid=pkg.mid,
                pairs=filtered,
                notionals=(want,),
            )
        return None

    def _store_cache(
        self,
        package: QuotesPackage,
        venue_slugs: Sequence[str],
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> None:
        """Cache multi-tier package and per-tier slices for single-tier reuse."""
        expires = self._clock() + self._agg.response_cache_ttl_sec
        multi_key = self._cache_key(
            package.asset, package.notionals, venue_slugs, sides, instrument_type
        )
        self._cache[multi_key] = _CacheEntry(expires_at=expires, package=package)
        if len(package.notionals) <= 1:
            return
        for n in package.notionals:
            single_key = self._cache_key(
                package.asset, (n,), venue_slugs, sides, instrument_type
            )
            # Don't clobber a fresher exact single-tier entry.
            existing = self._cache.get(single_key)
            if existing is not None and existing.expires_at > expires:
                continue
            filtered = [p for p in package.pairs if p.notional_usd == n]
            self._cache[single_key] = _CacheEntry(
                expires_at=expires,
                package=QuotesPackage(
                    snapshot_id=package.snapshot_id,
                    asset=package.asset,
                    notional_usd=n,
                    mid=package.mid,
                    pairs=filtered,
                    notionals=(n,),
                ),
            )

    async def _collect_venue_multi(
        self,
        slug: str,
        *,
        asset: str,
        notionals: tuple[Decimal, ...],
        mid: ReferenceMid,
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> list[SizeQuotePair]:
        """Collect SizeQuotePair rows for every notional on one venue.

        Orderbook venues (CEX / perp DEX) with ``get_quotes_batch`` price all
        tiers from one book fetch. AMM / prop AMM fall back to per-tier fan-out
        (no reusable snapshot upstream).
        """
        adapter = registry_get(slug)
        itype = effective_instrument_type(adapter.venue_class, instrument_type)
        timeout = self._agg.timeout_for(adapter.venue_class)
        stale_threshold = self._mid_settings.stale_threshold_sec
        side_order: list[Side] = list(sides)

        if not is_available(adapter.venue):
            return [
                assemble_pair(
                    mid=mid,
                    venue=slug,
                    asset=asset,
                    instrument_type=itype,
                    notional_usd=n,
                    buy=(
                        not_initialized_quote(
                            mid=mid,
                            venue=slug,
                            asset=asset,
                            side="buy",
                            notional_usd=n,
                            instrument_type=itype,
                        )
                        if "buy" in side_order
                        else None
                    ),
                    sell=(
                        not_initialized_quote(
                            mid=mid,
                            venue=slug,
                            asset=asset,
                            side="sell",
                            notional_usd=n,
                            instrument_type=itype,
                        )
                        if "sell" in side_order
                        else None
                    ),
                    top_of_book=None,
                    stale_threshold_sec=stale_threshold,
                )
                for n in notionals
            ]

        batch_fn = getattr(adapter, "get_quotes_batch", None)
        use_batch = (
            callable(batch_fn) and adapter.venue_class in _ORDERBOOK_CLASSES
        )

        if use_batch:
            assert batch_fn is not None
            try:
                with quote_deadline(timeout):
                    async with asyncio.timeout(timeout):
                        batch_quotes: list[Quote] = await batch_fn(
                            asset,
                            side_order,
                            notionals,
                            mid=mid,
                            instrument_type=itype,
                        )
            except TimeoutError:
                logger.warning(
                    "venue %s get_quotes_batch timed out after %ss", slug, timeout
                )
                batch_quotes = [
                    error_quote(
                        mid=mid,
                        venue=slug,
                        asset=asset,
                        side=side,
                        notional_usd=n,
                        instrument_type=itype,
                        error_code="timeout",
                        error_message=f"get_quotes_batch timed out after {timeout}s",
                    )
                    for n in notionals
                    for side in side_order
                ]
            except AdapterRateLimitedError as exc:
                logger.warning("venue %s get_quotes_batch rate limited: %s", slug, exc)
                batch_quotes = [
                    rate_limited_quote(
                        mid=mid,
                        venue=slug,
                        asset=asset,
                        side=side,
                        notional_usd=n,
                        instrument_type=itype,
                        error_message=str(exc),
                    )
                    for n in notionals
                    for side in side_order
                ]
            except AdapterError as exc:
                logger.warning("venue %s get_quotes_batch error: %s", slug, exc)
                batch_quotes = [
                    error_quote(
                        mid=mid,
                        venue=slug,
                        asset=asset,
                        side=side,
                        notional_usd=n,
                        instrument_type=itype,
                        error_code="adapter_error",
                        error_message=str(exc),
                    )
                    for n in notionals
                    for side in side_order
                ]
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "venue %s get_quotes_batch unexpected error", slug
                )
                batch_quotes = [
                    error_quote(
                        mid=mid,
                        venue=slug,
                        asset=asset,
                        side=side,
                        notional_usd=n,
                        instrument_type=itype,
                        error_code="adapter_error",
                        error_message=f"{type(exc).__name__}: {exc}",
                    )
                    for n in notionals
                    for side in side_order
                ]

            by_key: dict[tuple[Decimal, Side], Quote] = {}
            for q in batch_quotes:
                by_key[(q.notional_usd, q.side)] = q

            tob_outcome = await self._tob_with_timeout(
                adapter,
                asset=asset,
                mid=mid,
                instrument_type=itype,
                timeout=timeout,
            )
            top_of_book = tob_outcome.book
            tob_tag: str | None = None
            if tob_outcome.failed and adapter.venue_class in _ORDERBOOK_CLASSES:
                top_of_book = None
                err_code = tob_outcome.error_code or "tob_error"
                err_msg = tob_outcome.error_message or "orderbook spread fetch failed"
                tob_tag = f"tob_error:{err_code}:{err_msg}"
                logger.warning(
                    "venue %s orderbook TOB failed (%s); stamping raw_ref on ok legs",
                    slug,
                    err_msg,
                )

            pairs: list[SizeQuotePair] = []
            for n in notionals:
                buy = by_key.get((n, "buy")) if "buy" in side_order else None
                sell = by_key.get((n, "sell")) if "sell" in side_order else None
                if tob_tag is not None:
                    if buy is not None and buy.status == "ok":
                        buy = buy.model_copy(
                            update={"raw_ref": _append_raw_ref(buy.raw_ref, tob_tag)}
                        )
                    if sell is not None and sell.status == "ok":
                        sell = sell.model_copy(
                            update={"raw_ref": _append_raw_ref(sell.raw_ref, tob_tag)}
                        )
                pairs.append(
                    assemble_pair(
                        mid=mid,
                        venue=slug,
                        asset=asset,
                        instrument_type=itype,
                        notional_usd=n,
                        buy=buy,
                        sell=sell,
                        # TOB is book-level; attach to every tier (same snapshot).
                        top_of_book=top_of_book,
                        stale_threshold_sec=stale_threshold,
                    )
                )
            return pairs

        # Non-orderbook (or no batch): one fan-out per notional, shared mid.
        pairs_out = await asyncio.gather(
            *(
                self._collect_venue(
                    slug,
                    asset=asset,
                    notional_usd=n,
                    mid=mid,
                    sides=sides,
                    instrument_type=instrument_type,
                )
                for n in notionals
            )
        )
        return list(pairs_out)

    async def _collect_venue(
        self,
        slug: str,
        *,
        asset: str,
        notional_usd: Decimal,
        mid: ReferenceMid,
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> SizeQuotePair:
        adapter = registry_get(slug)
        itype = effective_instrument_type(adapter.venue_class, instrument_type)
        timeout = self._agg.timeout_for(adapter.venue_class)
        stale_threshold = self._mid_settings.stale_threshold_sec

        # Concurrent legs + TOB within a venue (each call bounded by class timeout).
        side_order: list[Side] = list(sides)
        quote_coros = [
            quote_with_timeout(
                adapter,
                asset=asset,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=itype,
                timeout=timeout,
            )
            for side in side_order
        ]
        tob_coro = self._tob_with_timeout(
            adapter,
            asset=asset,
            mid=mid,
            instrument_type=itype,
            timeout=timeout,
        )
        gathered = await asyncio.gather(*quote_coros, tob_coro)
        leg_results = list(gathered[:-1])
        tob_outcome = gathered[-1]
        assert isinstance(tob_outcome, _TobOutcome)

        buy: Quote | None = None
        sell: Quote | None = None
        for side, result in zip(side_order, leg_results, strict=True):
            assert isinstance(result, Quote)
            if side == "buy":
                buy = result
            else:
                sell = result

        # WHI-799 §6.3: orderbook TOB failure must not look like AMM "no TOB concept".
        # SizeQuotePair has no tob_error field — stamp ok legs' raw_ref so the FE can
        # see the degradation while keeping authoritative spread bps (quotes are primary).
        top_of_book = tob_outcome.book
        if tob_outcome.failed and adapter.venue_class in _ORDERBOOK_CLASSES:
            top_of_book = None
            err_code = tob_outcome.error_code or "tob_error"
            err_msg = tob_outcome.error_message or "orderbook spread fetch failed"
            tag = f"tob_error:{err_code}:{err_msg}"
            if buy is not None and buy.status == "ok":
                buy = buy.model_copy(update={"raw_ref": _append_raw_ref(buy.raw_ref, tag)})
            if sell is not None and sell.status == "ok":
                sell = sell.model_copy(
                    update={"raw_ref": _append_raw_ref(sell.raw_ref, tag)}
                )
            logger.warning(
                "venue %s orderbook TOB failed (%s); stamped raw_ref on ok legs",
                slug,
                err_msg,
            )

        return assemble_pair(
            mid=mid,
            venue=slug,
            asset=asset,
            instrument_type=itype,
            notional_usd=notional_usd,
            buy=buy,
            sell=sell,
            top_of_book=top_of_book,
            stale_threshold_sec=stale_threshold,
        )

    async def _tob_with_timeout(
        self,
        adapter: VenueAdapter,
        *,
        asset: str,
        mid: ReferenceMid,
        instrument_type: InstrumentType,
        timeout: float,
    ) -> _TobOutcome:
        if not is_available(adapter.venue):
            return _TobOutcome(
                book=None,
                failed=True,
                error_code="not_initialized",
                error_message=not_initialized_message(adapter.venue),
            )
        try:
            with quote_deadline(timeout):
                async with asyncio.timeout(timeout):
                    if instrument_type in ("spot", "perp"):
                        tob_itype: Literal["spot", "perp"] = instrument_type
                        book = await adapter.get_orderbook_spread(
                            asset, mid=mid, instrument_type=tob_itype
                        )
                    else:
                        book = await adapter.get_orderbook_spread(asset, mid=mid)
            return _TobOutcome(book=book, failed=False)
        except TimeoutError:
            logger.warning(
                "venue %s get_orderbook_spread timed out after %ss",
                adapter.venue,
                timeout,
            )
            return _TobOutcome(
                book=None,
                failed=True,
                error_code="timeout",
                error_message=f"get_orderbook_spread timed out after {timeout}s",
            )
        except AdapterRateLimitedError as exc:
            logger.warning(
                "venue %s get_orderbook_spread rate limited: %s", adapter.venue, exc
            )
            return _TobOutcome(
                book=None,
                failed=True,
                error_code="rate_limited",
                error_message=str(exc),
            )
        except AdapterError as exc:
            logger.warning("venue %s get_orderbook_spread error: %s", adapter.venue, exc)
            return _TobOutcome(
                book=None,
                failed=True,
                error_code="tob_error",
                error_message=str(exc),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "venue %s get_orderbook_spread unexpected error", adapter.venue
            )
            return _TobOutcome(
                book=None,
                failed=True,
                error_code="tob_error",
                error_message=f"{type(exc).__name__}: {exc}",
            )
