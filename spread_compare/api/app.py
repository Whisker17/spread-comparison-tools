"""FastAPI application factory with adapter lifecycle (WHI-823)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from spread_compare.adapters import aclose_all, initialized_count, startup_all


class HealthResponse(BaseModel):
    """Liveness payload for ``GET /health``."""

    status: str = Field(description="Always 'ok' when the process is serving.")
    adapters_initialized: int = Field(
        description="Adapters whose startup() completed successfully."
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start all venue adapters on boot; close them on shutdown."""
    try:
        await startup_all()
        yield
    finally:
        await aclose_all()


def create_app() -> FastAPI:
    """Build the ASGI app. Endpoints beyond /health land in later M2 issues."""
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

    return app
