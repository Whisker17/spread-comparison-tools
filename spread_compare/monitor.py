"""Real-time engine health snapshot + alert evaluation (WHI-819).

Exposes the signals a monitor needs (stream state, ages, rate-limits) and
evaluates them against ``config/monitor.yaml``. Delivery is a generic HTTPS
webhook (ADR 0003) — optional when ``ALERT_WEBHOOK_URL`` is unset.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from spread_compare.local_book import BookHealth
from spread_compare.mids import MidService
from spread_compare.models import PRICED_QUOTE_STATUSES
from spread_compare.poller import PullQuotePoller
from spread_compare.quote_store import QuoteStore, default_quote_store
from spread_compare.settings import (
    MonitorSettings,
    PollerSettings,
    WsSettings,
    load_monitor_settings,
    load_poller_settings,
    load_ws_settings,
)
from spread_compare.upstream_events import (
    RATE_LIMIT_SOURCES,
    RollingEventCounter,
    default_rate_limit_counter,
)
from spread_compare.ws_feeds import WsFeedManager
from spread_compare.ws_registry import WsBookRegistry, default_ws_registry

logger = logging.getLogger(__name__)

AlertCode = Literal[
    "ws_disconnected",
    "book_stale",
    "book_desync",
    "book_resync_failed",
    "sweep_stale",
    "mid_stale",
    "rate_limited",
    "data_stale",
]

AlertSeverity = Literal["warning", "critical"]


class StreamHealthView(BaseModel):
    """Per-stream (multiplexed WS) health for ``GET /health``."""

    stream_id: str
    connected: bool
    disconnected_age_sec: float | None = None
    books_total: int = 0
    books_healthy: int = 0
    books_resyncing: int = 0
    books_disconnected: int = 0
    max_book_age_sec: float | None = None
    resync_ok_window: int = 0
    resync_fail_window: int = 0


class SweepHealthView(BaseModel):
    """Per poller-group last-completed-sweep age."""

    group: str
    interval_sec: float
    age_sec: float | None = None
    last_completed_at: datetime | None = None
    sweep_count: int = 0
    stale: bool = False


class AlertView(BaseModel):
    """One evaluated alert (open condition)."""

    code: AlertCode
    severity: AlertSeverity
    target: str = Field(description="stream_id, group, source, or 'engine'")
    message: str
    value: float | None = None
    threshold: float | None = None


class EngineHealthView(BaseModel):
    """Detail payload nested under ``GET /health`` (WHI-819)."""

    data_ok: bool
    data_failures: list[str] = Field(default_factory=list)
    mid_age_sec: float | None = None
    mid_probe_asset: str
    uptime_sec: float
    in_startup_grace: bool
    sweeps: list[SweepHealthView] = Field(default_factory=list)
    streams: list[StreamHealthView] = Field(default_factory=list)
    rate_limits: dict[str, int] = Field(default_factory=dict)
    alerts: list[AlertView] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _OpenAlert:
    code: AlertCode
    severity: AlertSeverity
    target: str
    message: str
    value: float | None = None
    threshold: float | None = None

    @property
    def key(self) -> str:
        return f"{self.code}:{self.target}"

    def to_view(self) -> AlertView:
        return AlertView(
            code=self.code,
            severity=self.severity,
            target=self.target,
            message=self.message,
            value=self.value,
            threshold=self.threshold,
        )


@dataclass
class EngineSnapshot:
    """Immutable-ish collection of live signals used by the evaluator."""

    now_mono: float
    uptime_sec: float
    in_startup_grace: bool
    mid_age_sec: float | None
    mid_probe_asset: str
    sweeps: list[SweepHealthView]
    streams: list[StreamHealthView]
    rate_limits: dict[str, int]
    fresh_store_quotes: int
    healthy_books: int
    data_failures: list[str] = field(default_factory=list)
    data_ok: bool = True
    alerts: list[_OpenAlert] = field(default_factory=list)

    def to_view(self) -> EngineHealthView:
        return EngineHealthView(
            data_ok=self.data_ok,
            data_failures=list(self.data_failures),
            mid_age_sec=self.mid_age_sec,
            mid_probe_asset=self.mid_probe_asset,
            uptime_sec=self.uptime_sec,
            in_startup_grace=self.in_startup_grace,
            sweeps=list(self.sweeps),
            streams=list(self.streams),
            rate_limits=dict(self.rate_limits),
            alerts=[a.to_view() for a in self.alerts],
        )


def collect_engine_snapshot(
    *,
    settings: MonitorSettings | None = None,
    poller: PullQuotePoller | None = None,
    mid_service: MidService | None = None,
    ws_manager: WsFeedManager | None = None,
    registry: WsBookRegistry | None = None,
    quote_store: QuoteStore | None = None,
    rate_limits: RollingEventCounter | None = None,
    poller_settings: PollerSettings | None = None,
    ws_settings: WsSettings | None = None,
    started_mono: float | None = None,
    clock: Callable[[], float] | None = None,
) -> EngineSnapshot:
    """Gather live signals; pure enough to unit-test with fakes."""
    cfg = settings if settings is not None else load_monitor_settings()
    pcfg = poller_settings if poller_settings is not None else load_poller_settings()
    wcfg = ws_settings if ws_settings is not None else load_ws_settings()
    mono = clock or time.monotonic
    now = mono()
    boot = started_mono if started_mono is not None else now
    uptime = max(0.0, now - boot)
    in_grace = uptime < cfg.startup_grace_sec

    reg = registry if registry is not None else default_ws_registry()
    store = quote_store if quote_store is not None else default_quote_store()
    rl = rate_limits if rate_limits is not None else default_rate_limit_counter()

    # Probe-asset only — do not fall back to another asset's fresher mid
    # (that would mask a missing BTC mid with a fresh SOL entry).
    mid_age: float | None = None
    if mid_service is not None:
        mid_age = mid_service.cache_age_sec(cfg.probe_asset)

    sweeps = _collect_sweeps(poller=poller, poller_settings=pcfg, cfg=cfg, now=now)
    streams = _collect_streams(
        ws_manager=ws_manager, registry=reg, cfg=cfg, ws_enabled=wcfg.enabled, now=now
    )
    rate_counts = rl.counts(RATE_LIMIT_SOURCES, window_sec=cfg.rate_limit_window_sec)

    fresh_store = _count_fresh_store_quotes(
        store,
        asset=cfg.probe_asset,
        max_age_sec=cfg.probe_max_quote_age_sec,
        now=now,
    )
    # Books are partitioned by stream — sum is exact.
    healthy_books = sum(s.books_healthy for s in streams)

    data_failures = _data_probe_failures(
        cfg=cfg,
        mid_age=mid_age,
        fresh_store=fresh_store,
        healthy_books=healthy_books,
        ws_enabled=wcfg.enabled,
        poller_enabled=pcfg.enabled,
        in_grace=in_grace,
    )
    data_ok = not data_failures

    snap = EngineSnapshot(
        now_mono=now,
        uptime_sec=uptime,
        in_startup_grace=in_grace,
        mid_age_sec=mid_age,
        mid_probe_asset=cfg.probe_asset,
        sweeps=sweeps,
        streams=streams,
        rate_limits=rate_counts,
        fresh_store_quotes=fresh_store,
        healthy_books=healthy_books,
        data_failures=data_failures,
        data_ok=data_ok,
    )
    snap.alerts = evaluate_alerts(snap, cfg)
    return snap


def evaluate_alerts(
    snap: EngineSnapshot, cfg: MonitorSettings
) -> list[_OpenAlert]:
    """Map a snapshot to open alerts (idempotent pure function)."""
    alerts: list[_OpenAlert] = []

    for stream in snap.streams:
        if not stream.connected:
            age = stream.disconnected_age_sec
            if age is not None and age >= cfg.ws_disconnected_alert_sec:
                alerts.append(
                    _OpenAlert(
                        code="ws_disconnected",
                        severity="critical",
                        target=stream.stream_id,
                        message=(
                            f"WebSocket stream {stream.stream_id!r} disconnected "
                            f"for {age:.1f}s (threshold {cfg.ws_disconnected_alert_sec}s)"
                        ),
                        value=age,
                        threshold=cfg.ws_disconnected_alert_sec,
                    )
                )
        elif (
            stream.max_book_age_sec is not None
            and stream.max_book_age_sec > cfg.ws_max_book_age_sec
            and stream.books_total > 0
        ):
            alerts.append(
                _OpenAlert(
                    code="book_stale",
                    severity="warning",
                    target=stream.stream_id,
                    message=(
                        f"Stream {stream.stream_id!r} max book age "
                        f"{stream.max_book_age_sec:.1f}s exceeds "
                        f"{cfg.ws_max_book_age_sec}s"
                    ),
                    value=stream.max_book_age_sec,
                    threshold=cfg.ws_max_book_age_sec,
                )
            )

        total_resync = stream.resync_ok_window + stream.resync_fail_window
        if total_resync >= cfg.ws_resync_count_threshold:
            alerts.append(
                _OpenAlert(
                    code="book_desync",
                    severity="critical",
                    target=stream.stream_id,
                    message=(
                        f"Stream {stream.stream_id!r} resynced {total_resync} times "
                        f"in {cfg.ws_resync_window_sec}s "
                        f"(threshold {cfg.ws_resync_count_threshold})"
                    ),
                    value=float(total_resync),
                    threshold=float(cfg.ws_resync_count_threshold),
                )
            )
        if stream.resync_fail_window >= cfg.ws_failed_resync_threshold:
            alerts.append(
                _OpenAlert(
                    code="book_resync_failed",
                    severity="critical",
                    target=stream.stream_id,
                    message=(
                        f"Stream {stream.stream_id!r} failed resync "
                        f"{stream.resync_fail_window} times in "
                        f"{cfg.ws_resync_window_sec}s"
                    ),
                    value=float(stream.resync_fail_window),
                    threshold=float(cfg.ws_failed_resync_threshold),
                )
            )

    if not snap.in_startup_grace:
        for sweep in snap.sweeps:
            if sweep.stale:
                alerts.append(
                    _OpenAlert(
                        code="sweep_stale",
                        severity="critical",
                        target=sweep.group,
                        message=(
                            f"Poller sweep group {sweep.group!r} last completed "
                            + (
                                "never"
                                if sweep.age_sec is None
                                else f"{sweep.age_sec:.1f}s ago"
                            )
                            + f" (interval {sweep.interval_sec}s × "
                            f"{cfg.sweep_stale_multiplier})"
                        ),
                        value=sweep.age_sec,
                        threshold=sweep.interval_sec * cfg.sweep_stale_multiplier,
                    )
                )

        if snap.mid_age_sec is None or snap.mid_age_sec > cfg.mid_max_age_sec:
            alerts.append(
                _OpenAlert(
                    code="mid_stale",
                    severity="critical",
                    target="mid",
                    message=(
                        f"Reference mid for {snap.mid_probe_asset} is "
                        + (
                            "missing"
                            if snap.mid_age_sec is None
                            else f"{snap.mid_age_sec:.1f}s old"
                        )
                        + f" (threshold {cfg.mid_max_age_sec}s)"
                    ),
                    value=snap.mid_age_sec,
                    threshold=cfg.mid_max_age_sec,
                )
            )

        if not snap.data_ok:
            alerts.append(
                _OpenAlert(
                    code="data_stale",
                    severity="critical",
                    target="engine",
                    message="Data probe failed: " + "; ".join(snap.data_failures),
                )
            )

    for source, count in snap.rate_limits.items():
        if count >= cfg.rate_limit_count_threshold:
            alerts.append(
                _OpenAlert(
                    code="rate_limited",
                    severity="warning",
                    target=source,
                    message=(
                        f"Sustained upstream rate limiting on {source}: "
                        f"{count} events in {cfg.rate_limit_window_sec}s "
                        f"(threshold {cfg.rate_limit_count_threshold})"
                    ),
                    value=float(count),
                    threshold=float(cfg.rate_limit_count_threshold),
                )
            )

    return alerts


def _collect_sweeps(
    *,
    poller: PullQuotePoller | None,
    poller_settings: PollerSettings,
    cfg: MonitorSettings,
    now: float,
) -> list[SweepHealthView]:
    if not poller_settings.enabled:
        return []
    views: list[SweepHealthView] = []
    for group, gcfg in sorted(poller_settings.groups.items()):
        age: float | None = None
        last_at: datetime | None = None
        count = 0
        if poller is not None:
            count = poller.sweep_counts.get(group, 0)
            last_mono = poller.last_sweep_completed_mono.get(group)
            if last_mono is not None:
                age = max(0.0, now - last_mono)
            last_at = poller.last_sweep_completed_at.get(group)
        threshold = gcfg.interval_sec * cfg.sweep_stale_multiplier
        stale = age is None or age > threshold
        # Before any sweep has run, still mark stale (after grace the alert fires).
        views.append(
            SweepHealthView(
                group=group,
                interval_sec=gcfg.interval_sec,
                age_sec=age,
                last_completed_at=last_at,
                sweep_count=count,
                stale=stale,
            )
        )
    return views


def _collect_streams(
    *,
    ws_manager: WsFeedManager | None,
    registry: WsBookRegistry,
    cfg: MonitorSettings,
    ws_enabled: bool,
    now: float,
) -> list[StreamHealthView]:
    if not ws_enabled:
        return []

    books = registry.list_books()
    # Group books by stream: stream_id convention is venue_instrument or venue
    # names from WsFeedManager (binance_spot, bybit_linear, hyperliquid, …).
    # Books only have venue + instrument_type — map via known rules.
    by_stream: dict[str, list[Any]] = {}
    for book in books:
        sid = _stream_id_for_book(book.venue, book.instrument_type)
        by_stream.setdefault(sid, []).append(book)

    stream_ids: set[str] = set(by_stream)
    if ws_manager is not None:
        stream_ids.update(ws_manager.known_stream_ids())

    views: list[StreamHealthView] = []
    for sid in sorted(stream_ids):
        connected = True
        disc_age: float | None = None
        resync_ok = 0
        resync_fail = 0
        if ws_manager is not None:
            connected = ws_manager.stream_connected(sid)
            disc_age = ws_manager.stream_disconnected_age_sec(sid, now=now)
            resync_ok, resync_fail = ws_manager.resync_counts(
                sid, window_sec=cfg.ws_resync_window_sec, now=now
            )
        else:
            # Registry-only: connection map.
            connected = registry.connection_count(sid) > 0

        stream_books = by_stream.get(sid, [])
        healthy = sum(1 for b in stream_books if b.health is BookHealth.HEALTHY)
        resyncing = sum(1 for b in stream_books if b.health is BookHealth.RESYNCING)
        disconnected = sum(
            1 for b in stream_books if b.health is BookHealth.DISCONNECTED
        )
        ages = [a for a in (b.age_sec(now_mono=now) for b in stream_books) if a is not None]
        max_age = max(ages) if ages else None

        views.append(
            StreamHealthView(
                stream_id=sid,
                connected=connected,
                disconnected_age_sec=disc_age,
                books_total=len(stream_books),
                books_healthy=healthy,
                books_resyncing=resyncing,
                books_disconnected=disconnected,
                max_book_age_sec=max_age,
                resync_ok_window=resync_ok,
                resync_fail_window=resync_fail,
            )
        )
    return views


def _stream_id_for_book(venue: str, instrument_type: str) -> str:
    """Map book venue/instrument to WsFeedManager stream_id."""
    v = venue.lower()
    it = instrument_type.lower()
    if v == "binance" and it == "spot":
        return "binance_spot"
    if v == "binance" and it == "perp":
        return "binance_futures"
    if v == "bybit" and it == "spot":
        return "bybit_spot"
    if v == "bybit" and it == "perp":
        return "bybit_linear"
    if v == "hyperliquid":
        return "hyperliquid"
    if v == "lighter":
        return "lighter"
    if v == "apex":
        return "apex"
    return f"{v}_{it}"


def _count_fresh_store_quotes(
    store: QuoteStore,
    *,
    asset: str,
    max_age_sec: float,
    now: float,
) -> int:
    asset_key = asset.upper()
    n = 0
    for key in store.keys():
        if key.asset.upper() != asset_key:
            continue
        entry = store.get(key)
        if entry is None:
            continue
        if entry.quote.status not in PRICED_QUOTE_STATUSES:
            continue
        age = now - entry.observed_mono
        if age <= max_age_sec:
            n += 1
    return n


def _data_probe_failures(
    *,
    cfg: MonitorSettings,
    mid_age: float | None,
    fresh_store: int,
    healthy_books: int,
    ws_enabled: bool,
    poller_enabled: bool,
    in_grace: bool,
) -> list[str]:
    if in_grace:
        return []
    failures: list[str] = []
    if mid_age is None:
        failures.append(f"no mid cached for {cfg.probe_asset}")
    elif mid_age > cfg.mid_max_age_sec:
        failures.append(
            f"mid age {mid_age:.1f}s > {cfg.mid_max_age_sec}s for {cfg.probe_asset}"
        )
    if poller_enabled and cfg.probe_min_fresh_store_quotes > 0:
        if fresh_store < cfg.probe_min_fresh_store_quotes:
            failures.append(
                f"fresh store quotes for {cfg.probe_asset}: "
                f"{fresh_store} < {cfg.probe_min_fresh_store_quotes}"
            )
    if ws_enabled and cfg.probe_min_healthy_books > 0:
        if healthy_books < cfg.probe_min_healthy_books:
            failures.append(
                f"healthy WS books: {healthy_books} < {cfg.probe_min_healthy_books}"
            )
    return failures


class WebhookAlerter:
    """POST open/resolved alerts to ``ALERT_WEBHOOK_URL`` (Discord-compatible)."""

    def __init__(
        self,
        *,
        webhook_url: str | None = None,
        settings: MonitorSettings | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._url = (
            webhook_url
            if webhook_url is not None
            else os.environ.get("ALERT_WEBHOOK_URL", "").strip() or None
        )
        self._settings = settings if settings is not None else load_monitor_settings()
        self._client = client
        self._owns_client = client is None
        self._clock = clock or time.monotonic
        # key → last fired mono
        self._last_sent: dict[str, float] = {}
        self._open_keys: set[str] = set()
        # Last-cycle payloads only (tests assert delivery shape; not a log).
        self.last_cycle_payloads: list[dict[str, Any]] = []

    @property
    def configured(self) -> bool:
        return bool(self._url)

    @property
    def sent_payloads(self) -> list[dict[str, Any]]:
        """Alias for tests that read the last cycle's attempted deliveries."""
        return self.last_cycle_payloads

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._settings.webhook_timeout_sec
            )
        return self._client

    async def process(self, alerts: Sequence[_OpenAlert]) -> list[dict[str, Any]]:
        """Fire/cooldown/resolve. Returns payloads attempted this cycle."""
        now = self._clock()
        current = {a.key: a for a in alerts}
        current_keys = set(current)
        payloads: list[dict[str, Any]] = []
        self.last_cycle_payloads = []

        # Newly open or cooled-down re-fire.
        for key, alert in current.items():
            last = self._last_sent.get(key)
            if last is not None and (now - last) < self._settings.alert_cooldown_sec:
                continue
            payload = self._build_payload(alert, status="firing")
            payloads.append(payload)
            await self._deliver(payload)
            self._last_sent[key] = now

        # Resolutions for alerts that cleared.
        resolved = self._open_keys - current_keys
        for key in sorted(resolved):
            code, _, target = key.partition(":")
            payload = {
                "status": "resolved",
                "code": code,
                "target": target,
                "content": f"✅ RESOLVED {code} on {target}",
                "text": f"RESOLVED {code} on {target}",
                "timestamp": datetime.now(tz=UTC).isoformat(),
            }
            payloads.append(payload)
            await self._deliver(payload)
            self._last_sent.pop(key, None)

        self._open_keys = current_keys
        return payloads

    def _build_payload(self, alert: _OpenAlert, *, status: str) -> dict[str, Any]:
        icon = "🚨" if alert.severity == "critical" else "⚠️"
        content = f"{icon} [{alert.severity}] {alert.code} @ {alert.target}: {alert.message}"
        return {
            "status": status,
            "code": alert.code,
            "severity": alert.severity,
            "target": alert.target,
            "message": alert.message,
            "value": alert.value,
            "threshold": alert.threshold,
            # Discord-compatible field; Slack-ish "text" for generic hooks.
            "content": content,
            "text": content,
            "timestamp": datetime.now(tz=UTC).isoformat(),
        }

    async def _deliver(self, payload: dict[str, Any]) -> None:
        self.last_cycle_payloads.append(payload)
        if not self._url:
            logger.warning(
                "alert %s (no ALERT_WEBHOOK_URL): %s",
                payload.get("status"),
                payload.get("content") or payload.get("message"),
            )
            return
        try:
            resp = await self._http().post(self._url, json=payload)
            if resp.status_code >= 400:
                logger.error(
                    "alert webhook HTTP %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
            else:
                logger.info(
                    "alert webhook delivered status=%s code=%s target=%s",
                    payload.get("status"),
                    payload.get("code"),
                    payload.get("target"),
                )
        except Exception:  # noqa: BLE001 — never crash the monitor loop
            logger.exception("alert webhook delivery failed")


class EngineMonitor:
    """Background evaluator: snapshot → alerts → webhook."""

    def __init__(
        self,
        *,
        settings: MonitorSettings | None = None,
        poller: PullQuotePoller | None = None,
        mid_service: MidService | None = None,
        ws_manager: WsFeedManager | None = None,
        alerter: WebhookAlerter | None = None,
        started_mono: float | None = None,
    ) -> None:
        self._settings = settings if settings is not None else load_monitor_settings()
        self._poller = poller
        self._mids = mid_service
        self._ws = ws_manager
        self._alerter = alerter if alerter is not None else WebhookAlerter(
            settings=self._settings
        )
        self._started_mono = (
            started_mono if started_mono is not None else time.monotonic()
        )
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.last_snapshot: EngineSnapshot | None = None

    @property
    def settings(self) -> MonitorSettings:
        return self._settings

    @property
    def alerter(self) -> WebhookAlerter:
        return self._alerter

    def bind(
        self,
        *,
        poller: PullQuotePoller | None = None,
        mid_service: MidService | None = None,
        ws_manager: WsFeedManager | None = None,
    ) -> None:
        """Update live dependencies after lifespan starts subsystems."""
        if poller is not None:
            self._poller = poller
        if mid_service is not None:
            self._mids = mid_service
        if ws_manager is not None:
            self._ws = ws_manager

    def snapshot(self) -> EngineSnapshot:
        snap = collect_engine_snapshot(
            settings=self._settings,
            poller=self._poller,
            mid_service=self._mids,
            ws_manager=self._ws,
            started_mono=self._started_mono,
        )
        self.last_snapshot = snap
        return snap

    async def evaluate_once(self) -> EngineSnapshot:
        snap = self.snapshot()
        if self._settings.enabled:
            await self._alerter.process(snap.alerts)
        return snap

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self._settings.enabled:
            logger.info("engine monitor disabled (config/monitor.yaml enabled=false)")
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="engine-monitor")
        logger.info(
            "engine monitor started interval=%ss webhook=%s",
            self._settings.eval_interval_sec,
            "configured" if self._alerter.configured else "log-only",
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._alerter.aclose()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.evaluate_once()
            except Exception:  # noqa: BLE001
                logger.exception("engine monitor evaluation failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self._settings.eval_interval_sec
                )
                break
            except TimeoutError:
                continue
