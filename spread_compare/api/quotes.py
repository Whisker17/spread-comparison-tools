"""HTTP routes: ``GET /quotes``, ``GET /venues``, ``GET /assets``, ``GET /fees``."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from spread_compare.adapters.registry import disabled_venues
from spread_compare.adapters.registry import get as registry_get
from spread_compare.adapters.registry import list_venues as list_registered_adapters
from spread_compare.aggregator import (
    InvalidNotionalError,
    QuoteAggregator,
    QuotesPackage,
    UnknownVenueError,
)
from spread_compare.assets import list_assets
from spread_compare.fees import list_fee_schedules
from spread_compare.mids import MidResolutionError
from spread_compare.models import (
    NOTIONAL_TIERS_USD,
    FeeSchedule,
    InstrumentType,
    ReferenceMid,
    Side,
    SizeQuotePair,
    VenueClass,
)
from spread_compare.venues import VENUES, VenueInfo

router = APIRouter(tags=["quotes"])


class QuotesResponse(BaseModel):
    """``GET /quotes`` payload.

    Single-tier calls set ``notional_usd`` to that tier and ``notionals`` to a
    one-element list. Multi-tier calls (``?notionals=…``) return every tier's
    pairs under one ``snapshot_id`` / mid; ``notional_usd`` is the first
    (sorted) tier for back-compat (WHI-843).
    """

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    asset: str
    notional_usd: Decimal
    mid: ReferenceMid
    pairs: list[SizeQuotePair]
    notionals: list[Decimal] = Field(
        min_length=1,
        description="Requested notional tiers (USD); always non-empty.",
    )


class VenueResponse(BaseModel):
    """One row of ``GET /venues``."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    display_name: str
    venue_class: VenueClass
    chain: str | None = None
    adapter_registered: bool = False


class AssetResponse(BaseModel):
    """One row of ``GET /assets``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    representations: dict[str, str] = Field(
        description="Venue slug → representation label (WHI-798 §3.3)."
    )


def _package_to_response(package: QuotesPackage) -> QuotesResponse:
    notionals = (
        list(package.notionals)
        if package.notionals
        else [package.notional_usd]
    )
    return QuotesResponse(
        snapshot_id=package.snapshot_id,
        asset=package.asset,
        notional_usd=package.notional_usd,
        mid=package.mid,
        pairs=package.pairs,
        notionals=notionals,
    )


def _get_aggregator(request: Request) -> QuoteAggregator:
    agg = getattr(request.app.state, "aggregator", None)
    if agg is None:
        raise HTTPException(status_code=503, detail="aggregator not initialized")
    return agg  # type: ignore[no-any-return]


@router.get("/quotes", response_model=QuotesResponse)
async def get_quotes(
    request: Request,
    asset: Annotated[str, Query(min_length=1, description="Logical asset id, e.g. BTC")],
    notional: Annotated[
        str | None,
        Query(
            description=(
                "Single USD notional; one of "
                + " / ".join(str(t) for t in NOTIONAL_TIERS_USD)
                + " (WHI-799 §4.1). Mutually exclusive with ``notionals``."
            ),
        ),
    ] = None,
    notionals: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated USD notionals (multi-tier package, WHI-843); "
                "each must be a §4.1 tier. Mutually exclusive with ``notional``."
            ),
        ),
    ] = None,
    venues: Annotated[
        str | None,
        Query(description="Comma-separated venue slugs; default = all registered adapters"),
    ] = None,
    side: Annotated[Side | None, Query(description="If set, only that leg is fetched")] = None,
    instrument_type: Annotated[
        InstrumentType | None,
        Query(description="Override adapter default instrument type"),
    ] = None,
) -> QuotesResponse:
    """Fan out to adapters; one asset, one or many notional tiers (WHI-843)."""
    try:
        notional_arg = _parse_notional_params(notional=notional, notionals=notionals)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    venue_list = (
        [v.strip() for v in venues.split(",") if v.strip()] if venues else None
    )

    aggregator = _get_aggregator(request)
    try:
        package = await aggregator.collect(
            asset,
            notional_arg,
            venues=venue_list,
            side=side,
            instrument_type=instrument_type,
        )
    except InvalidNotionalError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownVenueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MidResolutionError as exc:
        raise HTTPException(
            status_code=503, detail=f"reference mid unavailable: {exc}"
        ) from exc

    return _package_to_response(package)


def _parse_notional_params(
    *,
    notional: str | None,
    notionals: str | None,
) -> Decimal | list[Decimal]:
    """Resolve ``notional`` XOR ``notionals`` query params into aggregator input."""
    has_single = notional is not None and notional != ""
    has_multi = notionals is not None and notionals != ""
    if has_single and has_multi:
        raise ValueError("pass either notional or notionals, not both")
    if not has_single and not has_multi:
        raise ValueError("notional or notionals is required")

    if has_single:
        assert notional is not None
        try:
            return Decimal(notional)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid notional: {notional!r}") from exc

    assert notionals is not None
    parts = [p.strip() for p in notionals.split(",") if p.strip()]
    if not parts:
        raise ValueError("notionals must list at least one tier")
    out: list[Decimal] = []
    for part in parts:
        try:
            out.append(Decimal(part))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid notional: {part!r}") from exc
    return out


@router.get("/venues", response_model=list[VenueResponse])
def get_venues() -> list[VenueResponse]:
    """Static venue registry + whether an adapter is currently registered.

    Venues disabled in ``config/venues.yaml`` are omitted entirely (WHI-840) so
    they do not appear as quote targets and consume no fan-out budget.
    """
    registered = set(list_registered_adapters())
    disabled = disabled_venues()
    rows: list[VenueResponse] = []
    for info in VENUES.values():
        if info.slug in disabled:
            continue
        rows.append(_venue_row(info, registered))
    # Scaffold-only adapters (e.g. mock) not in WHI-799 §6.5: use adapter.venue_class.
    for slug in sorted(registered - set(VENUES)):
        if slug in disabled:
            continue
        adapter = registry_get(slug)
        rows.append(
            VenueResponse(
                slug=slug,
                display_name=slug,
                venue_class=adapter.venue_class,
                chain=None,
                adapter_registered=True,
            )
        )
    return rows


@router.get("/assets", response_model=list[AssetResponse])
def get_assets() -> list[AssetResponse]:
    """Logical assets + per-venue representation labels (WHI-798 §3.3)."""
    return [
        AssetResponse(
            id=a.id,
            category=a.category,
            representations=dict(a.representations),
        )
        for a in list_assets()
    ]


@router.get("/fees", response_model=list[FeeSchedule])
def get_fees() -> list[FeeSchedule]:
    """All validated venue fee schedules (WHI-812; frontend contract for WHI-813)."""
    return list_fee_schedules()


def _venue_row(info: VenueInfo, registered: set[str]) -> VenueResponse:
    return VenueResponse(
        slug=info.slug,
        display_name=info.display_name,
        venue_class=info.venue_class,
        chain=info.chain,
        adapter_registered=info.slug in registered,
    )
