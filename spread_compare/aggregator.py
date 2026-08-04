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

from spread_compare.adapters.base import AdapterError, VenueAdapter, default_instrument_type
from spread_compare.adapters.registry import get as registry_get
from spread_compare.adapters.registry import is_available, list_venues
from spread_compare.costs import (
    half_spread_bps,
    round_trip_spread_bps,
    round_trip_total_cost_bps,
)
from spread_compare.mids import MidResolutionError, MidService, is_mid_stale
from spread_compare.models import (
    NOTIONAL_TIERS_USD,
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
    """One aggregation snapshot returned by :meth:`QuoteAggregator.collect`."""

    snapshot_id: str
    asset: str
    notional_usd: Decimal
    mid: ReferenceMid
    pairs: list[SizeQuotePair]


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
) -> Quote:
    """Build a ``status=error`` Quote row (WHI-799 §6.6)."""
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
        status="error",
        error_code=error_code,
        error_message=error_message,
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
        return error_quote(
            mid=mid,
            venue=adapter.venue,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            error_code="not_initialized",
            error_message=f"{adapter.venue}: adapter startup did not complete",
        )
    try:
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

    buy_spread = buy.spread_bps if buy is not None and buy.status == "ok" else None
    sell_spread = sell.spread_bps if sell is not None and sell.status == "ok" else None
    buy_total = buy.total_cost_bps if buy is not None and buy.status == "ok" else None
    sell_total = sell.total_cost_bps if sell is not None and sell.status == "ok" else None

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

    @property
    def mid_service(self) -> MidService:
        return self._mids

    def clear_cache(self) -> None:
        self._cache.clear()

    async def collect(
        self,
        asset: str,
        notional_usd: Decimal,
        *,
        venues: Sequence[str] | None = None,
        side: Side | None = None,
        instrument_type: InstrumentType | None = None,
        snapshot_id: str | None = None,
        use_cache: bool = True,
    ) -> QuotesPackage:
        """Aggregate quotes for one asset/notional across registered venues.

        Raises:
            InvalidNotionalError: notional not in §4.1 tiers.
            UnknownVenueError: filter names an unregistered adapter.
            MidResolutionError: mid unavailable (caller maps to HTTP 503).
        """
        notional = Decimal(notional_usd)
        if notional not in NOTIONAL_TIERS_USD:
            raise InvalidNotionalError(
                f"notional_usd must be one of {list(NOTIONAL_TIERS_USD)}, got {notional}"
            )

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
            asset_key, notional, venue_slugs, sides, instrument_type
        )
        if cache_eligible:
            hit = self._cache.get(cache_key)
            if hit is not None and hit.expires_at > self._clock():
                return hit.package

        snap = snapshot_id or str(uuid.uuid4())
        mid = await resolve_mid_with_budget(
            self._mids,
            asset_key,
            snapshot_id=snap,
            venue_timeout_sec=self._agg.venue_timeout_sec,
        )

        pairs = await asyncio.gather(
            *(
                self._collect_venue(
                    slug,
                    asset=asset_key,
                    notional_usd=notional,
                    mid=mid,
                    sides=sides,
                    instrument_type=instrument_type,
                )
                for slug in venue_slugs
            )
        )

        package = QuotesPackage(
            snapshot_id=snap,
            asset=asset_key,
            notional_usd=notional,
            mid=mid,
            pairs=list(pairs),
        )

        if cache_eligible:
            self._cache[cache_key] = _CacheEntry(
                expires_at=self._clock() + self._agg.response_cache_ttl_sec,
                package=package,
            )
        return package

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
        notional: Decimal,
        venues: Sequence[str],
        sides: Sequence[Side],
        instrument_type: InstrumentType | None,
    ) -> str:
        return "|".join(
            [
                asset,
                str(notional),
                ",".join(venues),
                ",".join(sides),
                instrument_type or "",
            ]
        )

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
                error_message=f"{adapter.venue}: adapter startup did not complete",
            )
        try:
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
