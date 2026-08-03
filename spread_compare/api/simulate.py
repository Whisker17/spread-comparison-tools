"""HTTP routes: ``POST /simulate`` (WHI-814), ``GET /simulate/pairs`` (WHI-833)."""

from __future__ import annotations

import time
from collections.abc import Callable
from decimal import Decimal
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from spread_compare.aggregator import UnknownVenueError
from spread_compare.assets import list_simulate_pair_assets, list_tradeable_usd_stables
from spread_compare.mids import MidResolutionError
from spread_compare.models import (
    FeeBreakdown,
    InstrumentType,
    ReferenceMid,
    Side,
    SimulateRowStatus,
)
from spread_compare.settings import ApiSettings, load_api_settings
from spread_compare.simulator import (
    InvalidSimulateAmountError,
    InvalidSimulatePairError,
    SimulatePackage,
    SimulateRow,
    TradeSimulator,
)

router = APIRouter(tags=["simulate"])


class SimulateRequest(BaseModel):
    """``POST /simulate`` body: sell/buy assets and amount in sell-asset units."""

    model_config = ConfigDict(extra="forbid")

    sell_asset: str = Field(min_length=1, description="Asset the user sells, e.g. SOL or USDC")
    buy_asset: str = Field(min_length=1, description="Asset the user receives, e.g. USDC or SOL")
    amount: Decimal = Field(
        description="Quantity of sell_asset (free-form; not snapped to notional tiers)",
        gt=0,
    )
    venues: list[str] | None = Field(
        default=None,
        description="Optional venue slug filter; default = all registered adapters",
    )
    instrument_type: InstrumentType | None = Field(
        default=None,
        description="Override adapter default instrument type when the class supports it",
    )

    @field_validator("sell_asset", "buy_asset", mode="before")
    @classmethod
    def _strip_assets(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class SimulateRowResponse(BaseModel):
    """One ranked venue row in the simulate response."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    venue_symbol: str | None = None
    instrument_type: InstrumentType
    expected_output: Decimal | None = None
    effective_price: Decimal | None = None
    spread_bps: Decimal | None = None
    fee_breakdown: FeeBreakdown
    total_cost_bps: Decimal | None = None
    timestamp: AwareDatetime
    status: SimulateRowStatus
    best: bool = False
    error_code: str | None = None
    error_message: str | None = None
    mid_stale: bool = False


class SimulateResponse(BaseModel):
    """``POST /simulate`` payload — contract for WHI-815."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    sell_asset: str
    buy_asset: str
    amount: Decimal
    asset: str = Field(description="Non-stable leg passed to adapters")
    side: Side = Field(description="Adapter side: sell when selling non-stable, buy otherwise")
    notional_usd: Decimal
    mid: ReferenceMid
    rows: list[SimulateRowResponse]


class SimulatePairErrorDetail(BaseModel):
    """Structured 422 body for pair validation failures (WHI-814 / WHI-815 client)."""

    model_config = ConfigDict(extra="forbid")

    message: str
    reason: Literal["unknown_asset", "cross_pair"]


class SimulatePairsResponse(BaseModel):
    """``GET /simulate/pairs`` — valid legs for building a simulate pair (WHI-833).

    Contract for WHI-815: clients form pairs as (one of ``stables``) ×
    (one of ``assets``), either direction. Exactly one leg must be a tradeable
    stable; ``USD`` is never listed (peg-only, not tradeable).
    """

    model_config = ConfigDict(extra="forbid")

    stables: list[str] = Field(
        description="Tradeable USD stablecoin symbols accepted as a pair leg (no USD).",
    )
    assets: list[str] = Field(
        description="Catalogued non-stable logical assets for the other leg.",
    )


def _row_to_response(row: SimulateRow) -> SimulateRowResponse:
    return SimulateRowResponse(
        venue=row.venue,
        venue_symbol=row.venue_symbol,
        instrument_type=row.instrument_type,
        expected_output=row.expected_output,
        effective_price=row.effective_price,
        spread_bps=row.spread_bps,
        fee_breakdown=row.fee_breakdown,
        total_cost_bps=row.total_cost_bps,
        timestamp=row.timestamp,
        status=row.status,
        best=row.best,
        error_code=row.error_code,
        error_message=row.error_message,
        mid_stale=row.mid_stale,
    )


def _package_to_response(package: SimulatePackage) -> SimulateResponse:
    return SimulateResponse(
        snapshot_id=package.snapshot_id,
        sell_asset=package.sell_asset,
        buy_asset=package.buy_asset,
        amount=package.amount,
        asset=package.asset,
        side=package.side,
        notional_usd=package.notional_usd,
        mid=package.mid,
        rows=[_row_to_response(r) for r in package.rows],
    )


def _get_simulator(request: Request) -> TradeSimulator:
    sim = getattr(request.app.state, "simulator", None)
    if sim is None:
        raise HTTPException(status_code=503, detail="simulator not initialized")
    return sim  # type: ignore[no-any-return]


class ClientRateGuard:
    """Simple per-client min-interval gate (protects Jupiter keyless ~0.5 RPS budget)."""

    def __init__(
        self,
        min_interval_sec: float,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._min_interval = min_interval_sec
        self._clock = clock or time.monotonic
        self._last: dict[str, float] = {}
        self._lock = Lock()

    def check(self, client_key: str) -> float | None:
        """Return None if allowed; otherwise seconds until the client may retry."""
        if self._min_interval <= 0:
            return None
        now = self._clock()
        with self._lock:
            prev = self._last.get(client_key)
            if prev is not None:
                wait = self._min_interval - (now - prev)
                if wait > 0:
                    return wait
            self._last[client_key] = now
            # Bound memory for long-lived processes.
            if len(self._last) > 10_000:
                cutoff = now - self._min_interval * 2
                self._last = {k: t for k, t in self._last.items() if t >= cutoff}
            return None


def _client_key(request: Request) -> str:
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _get_rate_guard(request: Request) -> ClientRateGuard:
    guard = getattr(request.app.state, "simulate_rate_guard", None)
    if guard is None:
        raise HTTPException(status_code=503, detail="simulate rate guard not initialized")
    return guard  # type: ignore[no-any-return]


@router.get(
    "/simulate/pairs",
    response_model=SimulatePairsResponse,
    summary="List valid simulate pair legs",
)
def get_simulate_pairs() -> SimulatePairsResponse:
    """Return tradeable stables and catalogued assets for pair construction.

    Discovery only — does not change ``POST /simulate`` validation. Clients
    should not hardcode USDC/USDT; this list is the SSOT (WHI-833).
    """
    return SimulatePairsResponse(
        stables=list_tradeable_usd_stables(),
        assets=list_simulate_pair_assets(),
    )


@router.post(
    "/simulate",
    response_model=SimulateResponse,
    responses={
        422: {
            "description": (
                "Pair validation or request body error. Pair failures use "
                "SimulatePairErrorDetail ({message, reason}); pydantic body "
                "validation uses the default HTTPValidationError shape."
            ),
            "model": SimulatePairErrorDetail,
        },
        429: {"description": "Per-client rate limit for on-demand simulation"},
        503: {"description": "Reference mid unavailable or simulator not initialized"},
    },
)
async def post_simulate(request: Request, body: SimulateRequest) -> SimulateResponse:
    """Fan out a free-form pair trade to adapters; rank by expected output."""
    guard = _get_rate_guard(request)
    wait = guard.check(_client_key(request))
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail=f"rate limit: retry after {wait:.2f}s",
            headers={"Retry-After": str(max(1, int(wait) + 1))},
        )

    simulator = _get_simulator(request)
    try:
        package = await simulator.simulate(
            body.sell_asset,
            body.buy_asset,
            body.amount,
            venues=body.venues,
            instrument_type=body.instrument_type,
        )
    except InvalidSimulatePairError as exc:
        # Structured detail so clients can branch without prose-matching (WHI-814).
        raise HTTPException(
            status_code=422,
            detail={"message": str(exc), "reason": exc.reason},
        ) from exc
    except InvalidSimulateAmountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UnknownVenueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MidResolutionError as exc:
        raise HTTPException(
            status_code=503, detail=f"reference mid unavailable: {exc}"
        ) from exc

    return _package_to_response(package)


def build_simulate_rate_guard(settings: ApiSettings | None = None) -> ClientRateGuard:
    """Factory used by app lifespan."""
    cfg = settings if settings is not None else load_api_settings()
    return ClientRateGuard(cfg.simulate_min_interval_sec)
