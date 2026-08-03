"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Build the ASGI app. Endpoints beyond /health land in later M2 issues."""
    app = FastAPI(
        title="spread-comparison-tools",
        version="0.1.0",
        description="Cross-venue execution quality / spread comparison API",
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
