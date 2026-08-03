"""HTTP routes: ``GET /quotes``, ``GET /venues``, ``GET /assets``, ``GET /fees``."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

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
    """``GET /quotes`` payload."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    asset: str
    notional_usd: Decimal
    mid: ReferenceMid
    pairs: list[SizeQuotePair]


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
    return QuotesResponse(
        snapshot_id=package.snapshot_id,
        asset=package.asset,
        notional_usd=package.notional_usd,
        mid=package.mid,
        pairs=package.pairs,
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
        str,
        Query(
            description="USD notional; one of 1000 / 10000 / 100000 / 1000000 (WHI-799 §4.1)",
        ),
    ],
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
    """Fan out to adapters and return SizeQuotePair rows for one asset/notional."""
    try:
        notional_usd = Decimal(notional)
    except (InvalidOperation, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid notional: {notional!r}"
        ) from exc

    venue_list = (
        [v.strip() for v in venues.split(",") if v.strip()] if venues else None
    )

    aggregator = _get_aggregator(request)
    try:
        package = await aggregator.collect(
            asset,
            notional_usd,
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


@router.get("/venues", response_model=list[VenueResponse])
def get_venues() -> list[VenueResponse]:
    """Static venue registry + whether an adapter is currently registered."""
    registered = set(list_registered_adapters())
    rows: list[VenueResponse] = []
    for info in VENUES.values():
        rows.append(_venue_row(info, registered))
    # Scaffold-only adapters (e.g. mock) not in WHI-799 §6.5: use adapter.venue_class.
    for slug in sorted(registered - set(VENUES)):
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
