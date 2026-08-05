"""FastAPI application factory with adapter lifecycle (WHI-823 / WHI-840 / WHI-819)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from spread_compare.api.stream import router as stream_router
from spread_compare.fees import get_fee_catalog
from spread_compare.mids import MidService
from spread_compare.monitor import EngineHealthView, EngineMonitor
from spread_compare.poller import PullQuotePoller
from spread_compare.quote_store import default_quote_store
from spread_compare.settings import (
    load_aggregator_settings,
    load_api_settings,
    load_impact_settings,
    load_mid_settings,
    load_monitor_settings,
    load_orderbook_cache_settings,
    load_poller_settings,
    load_stream_settings,
    load_venue_settings,
    load_ws_settings,
)
from spread_compare.simulator import TradeSimulator
from spread_compare.stream import QuoteStreamHub
from spread_compare.ws_bootstrap import start_ws_ingest, stop_ws_ingest

logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    """Liveness payload for ``GET /health`` (WHI-840 / WHI-819).

    Always HTTP 200 while the process is serving — including when degraded or
    when engine data is stale. Load balancers must not kill a process that is
    still serving the majority of venues. Use ``GET /health/data`` for the
    data-freshness probe that fails on stale-only serving.
    """

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
    engine: EngineHealthView | None = Field(
        default=None,
        description="Real-time engine signals (streams, sweeps, mid, alerts).",
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
    poller_settings = load_poller_settings()
    stream_settings = load_stream_settings()
    ws_settings = load_ws_settings()
    monitor_settings = load_monitor_settings()
    load_impact_settings()
    load_orderbook_cache_settings()
    get_fee_catalog()
    set_disabled_venues(venue_settings.disabled)

    quote_store = default_quote_store()
    mid_service = MidService(mid_settings)
    aggregator = QuoteAggregator(
        mid_service,
        aggregator_settings=agg_settings,
        mid_settings=mid_settings,
        poller_settings=poller_settings,
        quote_store=quote_store,
    )
    simulator = TradeSimulator(
        mid_service,
        aggregator_settings=agg_settings,
        mid_settings=mid_settings,
    )
    poller = PullQuotePoller(
        mid_service,
        store=quote_store,
        settings=poller_settings,
        aggregator_settings=agg_settings,
    )
    stream_hub = QuoteStreamHub(
        aggregator,
        stream_settings,
        cors_origins=api_settings.cors_origins,
    )
    engine_monitor = EngineMonitor(
        settings=monitor_settings,
        poller=poller,
        mid_service=mid_service,
        started_mono=time.monotonic(),
    )
    app.state.mid_service = mid_service
    app.state.aggregator = aggregator
    app.state.simulator = simulator
    app.state.quote_store = quote_store
    app.state.poller = poller
    app.state.stream_hub = stream_hub
    app.state.engine_monitor = engine_monitor
    app.state.simulate_rate_guard = build_simulate_rate_guard(api_settings)
    app.state.ws_feed_manager = None
    app.state.fast_mid_poller = None

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
        # WS books after adapter startup so symbol maps / meta are warm (WHI-847).
        # Connect failure degrades that stream only; REST remains the fallback.
        ws_manager, mid_poller = await start_ws_ingest(
            mid_service, settings=ws_settings
        )
        app.state.ws_feed_manager = ws_manager
        app.state.fast_mid_poller = mid_poller
        engine_monitor.bind(ws_manager=ws_manager)
        # Start after adapter startup so supported_assets / clients are warm
        # (WHI-846). A failed venue simply yields not_initialized store rows.
        await poller.start()
        await stream_hub.start()
        await engine_monitor.start()
        yield
    finally:
        await engine_monitor.stop()
        await stream_hub.stop()
        await poller.stop()
        await stop_ws_ingest(
            getattr(app.state, "ws_feed_manager", None),
            getattr(app.state, "fast_mid_poller", None),
        )
        retry_stop.set()
        if retry_task is not None:
            retry_task.cancel()
            try:
                await retry_task
            except asyncio.CancelledError:
                # Expected after cancel(); do not re-raise so aclose still runs.
                pass
            except Exception:  # noqa: BLE001 — never skip aclose
                logger.exception("adapter startup retry task failed during shutdown")
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
    def health(request: Request) -> HealthResponse:
        """Process liveness — always 200 while serving (including degraded)."""
        engine: EngineHealthView | None = None
        monitor = getattr(request.app.state, "engine_monitor", None)
        if isinstance(monitor, EngineMonitor):
            try:
                # Prefer last background evaluation — liveness must stay cheap
                # and must not re-run alert evaluation on every LB poll.
                engine = monitor.snapshot(force=False).to_view()
            except Exception:  # noqa: BLE001 — never fail liveness
                logger.exception("engine health snapshot failed")
        return HealthResponse(
            status="ok",
            adapters_initialized=initialized_count(),
            adapters_expected=expected_adapter_count(),
            degraded=is_degraded(),
            unavailable_venues=unavailable_venues(),
            engine=engine,
        )

    @app.get("/health/data", response_model=EngineHealthView)
    def health_data(request: Request) -> Response:
        """Data-freshness probe: 200 when engine data is ok, else 503.

        Distinguishes "process up" from "serving only stale rows" (WHI-819).
        External uptime monitors should hit this endpoint in addition to
        ``GET /health``.
        """
        monitor = getattr(request.app.state, "engine_monitor", None)
        if not isinstance(monitor, EngineMonitor):
            view = EngineHealthView(
                data_ok=False,
                data_failures=["engine monitor not initialized"],
                mid_age_sec=None,
                mid_probe_asset="",
                uptime_sec=0.0,
                in_startup_grace=False,
            )
            return JSONResponse(
                status_code=503, content=view.model_dump(mode="json")
            )
        snap = monitor.snapshot(force=True)
        body = snap.to_view().model_dump(mode="json")
        status = 200 if snap.data_ok else 503
        return JSONResponse(status_code=status, content=body)

    app.include_router(quotes_router)
    app.include_router(simulate_router)
    app.include_router(stream_router)
    return app
