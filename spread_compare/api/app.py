"""FastAPI application factory with adapter lifecycle (WHI-823 / WHI-840)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from spread_compare.adapters import (
    aclose_all,
    clear_disabled_venues,
    expected_adapter_count,
    initialized_count,
    is_degraded,
    run_startup_retry_loop,
    set_disabled_venues,
    startup_all,
    unavailable_venues,
)
from spread_compare.aggregator import QuoteAggregator
from spread_compare.api.quotes import router as quotes_router
from spread_compare.api.simulate import build_simulate_rate_guard
from spread_compare.api.simulate import router as simulate_router
from spread_compare.fees import get_fee_catalog
from spread_compare.mids import MidService
from spread_compare.settings import (
    load_aggregator_settings,
    load_api_settings,
    load_mid_settings,
    load_venue_settings,
)
from spread_compare.simulator import TradeSimulator

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Liveness payload for ``GET /health`` (WHI-840: degradation without flap)."""

    status: str = Field(description="Always 'ok' when the process is serving.")
    adapters_initialized: int = Field(
        description="Adapters whose startup() completed successfully."
    )
    adapters_expected: int = Field(
        description="Enabled adapters that should be started (excludes config-disabled)."
    )
    degraded: bool = Field(
        description="True when at least one enabled adapter is not initialized."
    )
    unavailable_venues: list[str] = Field(
        description="Enabled venue slugs that failed or have not completed startup."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start mid service + venue adapters on boot; close them on shutdown.

    Transient adapter startup failures degrade those venues only (WHI-840);
    configuration errors still refuse to boot.
    """
    # Fail-fast typed config before any network work (AGENTS.md / WHI-812 / WHI-840).
    mid_settings = load_mid_settings()
    agg_settings = load_aggregator_settings()
    api_settings = load_api_settings()
    venue_settings = load_venue_settings()
    get_fee_catalog()
    set_disabled_venues(venue_settings.disabled)

    mid_service = MidService(mid_settings)
    aggregator = QuoteAggregator(
        mid_service,
        aggregator_settings=agg_settings,
        mid_settings=mid_settings,
    )
    simulator = TradeSimulator(
        mid_service,
        aggregator_settings=agg_settings,
        mid_settings=mid_settings,
    )
    app.state.mid_service = mid_service
    app.state.aggregator = aggregator
    app.state.simulator = simulator
    app.state.simulate_rate_guard = build_simulate_rate_guard(api_settings)

    retry_stop = asyncio.Event()
    retry_task: asyncio.Task[None] | None = None
    try:
        report = await startup_all()
        if report.degraded:
            for slug, exc in sorted(report.degraded.items()):
                logger.error(
                    "venue %r degraded at startup (will retry in background): %s",
                    slug,
                    exc,
                )
        if venue_settings.startup_retry_interval_sec > 0:
            retry_task = asyncio.create_task(
                run_startup_retry_loop(
                    interval_sec=venue_settings.startup_retry_interval_sec,
                    backoff_multiplier=venue_settings.startup_retry_backoff_multiplier,
                    max_interval_sec=venue_settings.startup_retry_max_interval_sec,
                    stop_event=retry_stop,
                ),
                name="adapter-startup-retry",
            )
        yield
    finally:
        retry_stop.set()
        if retry_task is not None:
            retry_task.cancel()
            try:
                await retry_task
            except asyncio.CancelledError:
                pass
        await aclose_all()
        clear_disabled_venues()
        await mid_service.aclose()


def create_app() -> FastAPI:
    """Build the ASGI app."""
    app = FastAPI(
        title="spread-comparison-tools",
        version="0.1.0",
        description="Cross-venue execution quality / spread comparison API",
        lifespan=lifespan,
    )
    api_settings = load_api_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api_settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            adapters_initialized=initialized_count(),
            adapters_expected=expected_adapter_count(),
            degraded=is_degraded(),
            unavailable_venues=unavailable_venues(),
        )

    app.include_router(quotes_router)
    app.include_router(simulate_router)
    return app
