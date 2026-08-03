"""FastAPI application factory with adapter lifecycle (WHI-823) and quotes API (WHI-807)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from spread_compare.adapters import aclose_all, initialized_count, startup_all
from spread_compare.aggregator import QuoteAggregator
from spread_compare.api.quotes import router as quotes_router
from spread_compare.mids import MidService
from spread_compare.settings import load_aggregator_settings, load_mid_settings


class HealthResponse(BaseModel):
    """Liveness payload for ``GET /health``."""

    status: str = Field(description="Always 'ok' when the process is serving.")
    adapters_initialized: int = Field(
        description="Adapters whose startup() completed successfully."
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start mid service + venue adapters on boot; close them on shutdown."""
    mid_settings = load_mid_settings()
    agg_settings = load_aggregator_settings()
    mid_service = MidService(mid_settings)
    aggregator = QuoteAggregator(
        mid_service,
        aggregator_settings=agg_settings,
        mid_settings=mid_settings,
    )
    app.state.mid_service = mid_service
    app.state.aggregator = aggregator
    try:
        await startup_all()
        yield
    finally:
        await aclose_all()
        await mid_service.aclose()


def create_app() -> FastAPI:
    """Build the ASGI app."""
    app = FastAPI(
        title="spread-comparison-tools",
        version="0.1.0",
        description="Cross-venue execution quality / spread comparison API",
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            adapters_initialized=initialized_count(),
        )

    app.include_router(quotes_router)
    return app
