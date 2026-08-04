"""Trade simulation: pair + amount → per-venue expected output (WHI-814).

Reuses the M2 adapter fan-out shape (timeouts, per-venue degradation) without
tier snapping or response caching. **Never recomputes adapter bps** (WHI-799 §4.5).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from spread_compare.adapters.registry import get as registry_get
from spread_compare.adapters.registry import is_available, list_venues
from spread_compare.aggregator import (
    UnknownVenueError,
    apply_mid_stale,
    effective_instrument_type,
    not_initialized_quote,
    quote_with_timeout,
    resolve_mid_with_budget,
)
from spread_compare.assets import get_asset, is_usd_stable
from spread_compare.mids import MidService
from spread_compare.models import (
    FeeBreakdown,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    SimulateRowStatus,
)
from spread_compare.settings import AggregatorSettings, MidSettings, load_aggregator_settings

logger = logging.getLogger(__name__)

__all__ = [
    "InvalidSimulateAmountError",
    "InvalidSimulatePairError",
    "ResolvedPair",
    "SimulatePackage",
    "SimulateRow",
    "SimulateRowStatus",
    "SimulatorError",
    "TradeSimulator",
    "amount_to_notional_usd",
    "expected_output_from_quote",
    "rank_and_flag_best",
    "resolve_simulate_pair",
]


class SimulatorError(Exception):
    """Base simulator failure."""


class InvalidSimulatePairError(SimulatorError):
    """Request pair cannot be simulated (unknown asset or non-stable cross)."""

    def __init__(self, message: str, *, reason: Literal["unknown_asset", "cross_pair"]) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidSimulateAmountError(SimulatorError):
    """Amount is not a positive finite Decimal."""


@dataclass(frozen=True, slots=True)
class ResolvedPair:
    """Validated simulate pair mapped onto a single adapter (asset, side)."""

    sell_asset: str
    buy_asset: str
    asset: str
    side: Side
    stable_leg: str


@dataclass(frozen=True, slots=True)
class SimulateRow:
    """One venue's simulation outcome (ranked by expected_output)."""

    venue: str
    venue_symbol: str | None
    instrument_type: InstrumentType
    expected_output: Decimal | None
    effective_price: Decimal | None
    spread_bps: Decimal | None
    fee_breakdown: FeeBreakdown
    total_cost_bps: Decimal | None
    timestamp: datetime
    status: SimulateRowStatus
    best: bool = False
    error_code: str | None = None
    error_message: str | None = None
    mid_stale: bool = False


@dataclass(frozen=True, slots=True)
class SimulatePackage:
    """Full simulation snapshot for one pair + amount."""

    snapshot_id: str
    sell_asset: str
    buy_asset: str
    amount: Decimal
    asset: str
    side: Side
    notional_usd: Decimal
    mid: ReferenceMid
    rows: list[SimulateRow]


def resolve_simulate_pair(sell_asset: str, buy_asset: str) -> ResolvedPair:
    """Validate pair: exactly one USD stable, non-stable catalogued.

    Raises:
        InvalidSimulatePairError: unknown asset or unsupported cross pair.
    """
    sell = sell_asset.strip().upper()
    buy = buy_asset.strip().upper()
    if not sell or not buy:
        raise InvalidSimulatePairError(
            "sell_asset and buy_asset are required",
            reason="unknown_asset",
        )
    if sell == buy:
        raise InvalidSimulatePairError(
            f"sell_asset and buy_asset must differ (got {sell!r})",
            reason="cross_pair",
        )

    sell_stable = is_usd_stable(sell)
    buy_stable = is_usd_stable(buy)

    if sell_stable and buy_stable:
        raise InvalidSimulatePairError(
            f"both legs are USD stables ({sell}/{buy}); need one non-stable asset",
            reason="cross_pair",
        )

    # Neither leg is a USD stable → Phase 1 cannot simulate (no pair protocol).
    # Always classify as cross_pair so WETH→cbBTC is not confused with a catalog miss
    # (WHI-814 acceptance: distinguish cross pair vs unknown asset).
    if not sell_stable and not buy_stable:
        raise InvalidSimulatePairError(
            f"unsupported non-stable cross pair {sell} → {buy}; "
            "Phase 1 only supports pairs where exactly one leg is a USD stablecoin "
            "(USDC/USDT/USD)",
            reason="cross_pair",
        )

    non_stable = buy if sell_stable else sell
    stable = sell if sell_stable else buy
    if get_asset(non_stable) is None:
        raise InvalidSimulatePairError(
            f"unknown asset: {non_stable}",
            reason="unknown_asset",
        )

    side: Side = "buy" if sell_stable else "sell"
    return ResolvedPair(
        sell_asset=sell,
        buy_asset=buy,
        asset=non_stable,
        side=side,
        stable_leg=stable,
    )


def amount_to_notional_usd(
    amount: Decimal,
    *,
    pair: ResolvedPair,
    mid: Decimal,
) -> Decimal:
    """Convert sell-asset units to adapter notional_usd (free-form, no tier snap).

    Selling the non-stable leg: ``notional_usd = amount × mid``.
    Selling the stable leg: ``notional_usd ≈ amount``.
    """
    if amount <= 0:
        raise InvalidSimulateAmountError(f"amount must be positive, got {amount}")
    if pair.side == "sell":
        return amount * mid
    return amount


def expected_output_from_quote(quote: Quote, *, side: Side) -> Decimal | None:
    """Derive expected buy-leg units from an ok Quote (WHI-814 direction convention).

    * ``side=sell`` (selling non-stable): stablecoin out = ``qty_base × effective_price``
    * ``side=buy`` (buying non-stable): base out = ``notional_usd / effective_price``

    Buy uses notional/price (not mid-sized ``qty_base``) so orderbook venues with
    ``qty_method=base_from_mid`` still differentiate on execution price when ranked.

    Ranking uses this gross output as the headline number (WHI-814); fee embedding
    differences across venue classes are not adjusted here — never recompute bps.
    ``best`` still requires §5.2 eligibility (``total_cost_bps is not null``).

    Non-priced quotes return None. bps are never recomputed here.
    ``excessive_impact`` keeps price fields readable (WHI-845) so expected_output
    is still derived; ranking still requires status=ok for ``best``.
    """
    from spread_compare.models import PRICED_QUOTE_STATUSES

    if quote.status not in PRICED_QUOTE_STATUSES:
        return None
    if quote.effective_price is None or quote.effective_price <= 0:
        return None
    if side == "sell":
        if quote.qty_base is None:
            return None
        return quote.qty_base * quote.effective_price
    return quote.notional_usd / quote.effective_price


def _empty_fee_breakdown() -> FeeBreakdown:
    return FeeBreakdown(embedded_in_price=False)


def _row_from_quote(quote: Quote, *, side: Side, best: bool = False) -> SimulateRow:
    # QuoteStatus ⊆ SimulateRowStatus (extra value is not_supported only).
    status: SimulateRowStatus = quote.status
    return SimulateRow(
        venue=quote.venue,
        venue_symbol=quote.venue_symbol,
        instrument_type=quote.instrument_type,
        expected_output=expected_output_from_quote(quote, side=side),
        effective_price=quote.effective_price,
        spread_bps=quote.spread_bps,
        fee_breakdown=quote.fee_breakdown,
        total_cost_bps=quote.total_cost_bps,
        timestamp=quote.timestamp,
        status=status,
        best=best,
        error_code=quote.error_code,
        error_message=quote.error_message,
        mid_stale=quote.mid_stale,
    )


def _not_supported_row(
    *,
    venue: str,
    asset: str,
    instrument_type: InstrumentType,
) -> SimulateRow:
    now = datetime.now(tz=UTC)
    return SimulateRow(
        venue=venue,
        venue_symbol=None,
        instrument_type=instrument_type,
        expected_output=None,
        effective_price=None,
        spread_bps=None,
        fee_breakdown=_empty_fee_breakdown(),
        total_cost_bps=None,
        timestamp=now,
        status="not_supported",
        best=False,
        error_code="not_supported",
        error_message=f"{asset} not supported by {venue}",
        mid_stale=False,
    )


def rank_and_flag_best(rows: list[SimulateRow]) -> list[SimulateRow]:
    """Sort by expected_output desc (nulls last); flag at most one §5.2-eligible best.

    Eligibility (WHI-799 §5.2): ``status == ok`` **and** ``total_cost_bps is not null``.
    A ``gas_unknown`` row may lead on output but must never be ``best``.
    """

    def sort_key(row: SimulateRow) -> tuple[int, Decimal]:
        if row.expected_output is None:
            return (1, Decimal("0"))
        return (0, -row.expected_output)

    ordered = sorted(rows, key=sort_key)
    best_idx: int | None = None
    for i, row in enumerate(ordered):
        if row.status == "ok" and row.total_cost_bps is not None:
            best_idx = i
            break

    return [
        replace(row, best=(best_idx is not None and i == best_idx))
        for i, row in enumerate(ordered)
    ]


class TradeSimulator:
    """Fan-out simulator. Does not own adapter lifecycle (registry/lifespan does)."""

    def __init__(
        self,
        mid_service: MidService,
        *,
        aggregator_settings: AggregatorSettings | None = None,
        mid_settings: MidSettings | None = None,
    ) -> None:
        self._mids = mid_service
        self._agg = (
            aggregator_settings
            if aggregator_settings is not None
            else load_aggregator_settings()
        )
        self._mid_settings = mid_settings if mid_settings is not None else mid_service.settings

    @property
    def mid_service(self) -> MidService:
        return self._mids

    async def simulate(
        self,
        sell_asset: str,
        buy_asset: str,
        amount: Decimal,
        *,
        venues: Sequence[str] | None = None,
        instrument_type: InstrumentType | None = None,
        snapshot_id: str | None = None,
    ) -> SimulatePackage:
        """Simulate a trade across registered venues.

        Raises:
            InvalidSimulatePairError: pair validation failed.
            InvalidSimulateAmountError: non-positive amount.
            UnknownVenueError: filter names an unregistered adapter.
            MidResolutionError: mid unavailable (caller maps to HTTP 503).
        """
        pair = resolve_simulate_pair(sell_asset, buy_asset)
        amount_d = Decimal(amount)
        venue_slugs = self._resolve_venues(venues)
        snap = snapshot_id or str(uuid.uuid4())
        mid = await resolve_mid_with_budget(
            self._mids,
            pair.asset,
            snapshot_id=snap,
            venue_timeout_sec=self._agg.venue_timeout_sec,
        )
        # amount_to_notional_usd enforces amount > 0 (InvalidSimulateAmountError).
        notional = amount_to_notional_usd(amount_d, pair=pair, mid=mid.mid)

        raw_rows = await asyncio.gather(
            *(
                self._simulate_venue(
                    slug,
                    pair=pair,
                    notional_usd=notional,
                    mid=mid,
                    instrument_type=instrument_type,
                )
                for slug in venue_slugs
            )
        )
        rows = rank_and_flag_best(list(raw_rows))
        return SimulatePackage(
            snapshot_id=snap,
            sell_asset=pair.sell_asset,
            buy_asset=pair.buy_asset,
            amount=amount_d,
            asset=pair.asset,
            side=pair.side,
            notional_usd=notional,
            mid=mid,
            rows=rows,
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

    async def _simulate_venue(
        self,
        slug: str,
        *,
        pair: ResolvedPair,
        notional_usd: Decimal,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None,
    ) -> SimulateRow:
        adapter = registry_get(slug)
        itype = effective_instrument_type(adapter.venue_class, instrument_type)
        # WHI-840: failed startup must not collapse to not_supported via empty
        # warm-up caches (HL meta / lighter markets / apex symbols).
        if not is_available(slug):
            quote = not_initialized_quote(
                mid=mid,
                venue=slug,
                asset=pair.asset,
                side=pair.side,
                notional_usd=notional_usd,
                instrument_type=itype,
            )
            quote = apply_mid_stale(
                quote, stale_threshold_sec=self._mid_settings.stale_threshold_sec
            )
            return _row_from_quote(quote, side=pair.side)

        supported = {a.upper() for a in adapter.supported_assets(instrument_type=itype)}
        if pair.asset not in supported:
            return _not_supported_row(
                venue=slug,
                asset=pair.asset,
                instrument_type=itype,
            )

        quote = await quote_with_timeout(
            adapter,
            asset=pair.asset,
            side=pair.side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=itype,
            timeout=self._agg.timeout_for(adapter.venue_class),
            log_tag="[simulate]",
        )
        quote = apply_mid_stale(quote, stale_threshold_sec=self._mid_settings.stale_threshold_sec)
        return _row_from_quote(quote, side=pair.side)
