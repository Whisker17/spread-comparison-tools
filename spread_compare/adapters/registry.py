"""Decorator-based adapter self-registration and lifecycle (WHI-823 / WHI-840).

Each adapter lives in its own module and registers via ``@register_adapter`` so
parallel adapter PRs never edit a shared switchboard file. Discovery imports
those modules; this registry owns instances, startup/shutdown, and degraded
startup recovery.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field

from spread_compare.adapters.base import (
    AdapterFetchError,
    AdapterTimeoutError,
    VenueAdapter,
)
from spread_compare.venues import known_slugs

# Scaffold/test-only slugs (not production venues in WHI-799 §6.5).
# ``_test_discovery`` is reserved for tests/test_adapter_discovery.py so that
# test never claims a real venue slug (WHI-802 landmine fix).
_EXTRA_ALLOWED_SLUGS: frozenset[str] = frozenset({"mock", "_test_discovery"})

_REGISTRY: dict[str, VenueAdapter] = {}
_INITIALIZED: set[str] = set()
_DISABLED: set[str] = set()
# Venues whose last startup attempt failed transiently (eligible for background retry).
_DEGRADED: set[str] = set()
# True after :func:`startup_all` has run at least once in this process lifecycle
# (cleared by :func:`aclose_all`). Used so unit tests that never boot adapters
# still call ``get_quote`` without a not_initialized guard.
_STARTUP_COMPLETED: bool = False

logger = logging.getLogger(__name__)

# Transient upstream failures: degrade the venue, keep serving the rest (WHI-840).
_DEGRADABLE_STARTUP_ERRORS: tuple[type[BaseException], ...] = (
    AdapterFetchError,
    AdapterTimeoutError,
)


@dataclass(frozen=True, slots=True)
class StartupReport:
    """Per-boot outcome of :func:`startup_all` (WHI-840)."""

    succeeded: tuple[str, ...] = ()
    degraded: dict[str, Exception] = field(default_factory=dict)

    @property
    def degraded_slugs(self) -> tuple[str, ...]:
        return tuple(sorted(self.degraded))


def is_degradable_startup_error(exc: BaseException) -> bool:
    """Return True for transient upstream failures that must not refuse boot."""
    return isinstance(exc, _DEGRADABLE_STARTUP_ERRORS)


def register_adapter[T: VenueAdapter](cls: type[T]) -> type[T]:
    """Instantiate ``cls`` and register it under ``instance.venue``."""
    instance = cls()
    slug = instance.venue
    allowed = known_slugs() | _EXTRA_ALLOWED_SLUGS
    if slug not in allowed:
        raise ValueError(
            f"adapter slug {slug!r} is not in the WHI-799 §6.5 venue registry "
            f"(and not in {_EXTRA_ALLOWED_SLUGS}); refusing to register {cls.__name__}"
        )
    if slug in _REGISTRY:
        existing = type(_REGISTRY[slug]).__name__
        raise ValueError(
            f"adapter slug {slug!r} already registered by {existing}; "
            f"refusing to register {cls.__name__}"
        )
    _REGISTRY[slug] = instance
    return cls


def get(slug: str) -> VenueAdapter:
    """Return the registered adapter for ``slug`` or raise KeyError.

    Disabled venues raise KeyError so callers treat them as unknown.
    """
    if slug in _DISABLED:
        known = ", ".join(list_venues()) or "(none)"
        raise KeyError(
            f"no adapter registered for {slug!r} (disabled by config); known: {known}"
        )
    try:
        return _REGISTRY[slug]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"no adapter registered for {slug!r}; known: {known}") from exc


def list_venues() -> list[str]:
    """Sorted list of enabled registered adapter slugs."""
    return sorted(slug for slug in _REGISTRY if slug not in _DISABLED)


def set_disabled_venues(slugs: Iterable[str]) -> None:
    """Mark venues as disabled for this process lifecycle (WHI-840).

    Disabled venues are excluded from :func:`list_venues`, :func:`startup_all`,
    and :func:`get`. Registration is preserved so re-enable (clear) works without
    re-importing adapter modules.
    """
    _DISABLED.clear()
    for raw in slugs:
        slug = str(raw).strip()
        if slug:
            _DISABLED.add(slug)
    # A venue that is no longer eligible must not count as healthy / retried.
    _INITIALIZED.difference_update(_DISABLED)
    _DEGRADED.difference_update(_DISABLED)
    if _DISABLED:
        logger.info("venues disabled by config: %s", ", ".join(sorted(_DISABLED)))


def disabled_venues() -> frozenset[str]:
    """Return the current disabled-venue set."""
    return frozenset(_DISABLED)


def clear_disabled_venues() -> None:
    """Clear the disabled-venue set (tests / shutdown)."""
    _DISABLED.clear()


def initialized_count() -> int:
    """Number of adapters whose ``startup()`` completed successfully."""
    return len(_INITIALIZED)


def expected_adapter_count() -> int:
    """Number of enabled registered adapters that should be started."""
    return len(list_venues())


def is_initialized(slug: str) -> bool:
    """Return True when ``slug`` completed ``startup()`` successfully."""
    return slug in _INITIALIZED


def is_available(slug: str) -> bool:
    """Return True when the venue may be quoted without a not_initialized error.

    Before the first :func:`startup_all` (unit tests that never boot the app),
    every registered venue is treated as available so fixture-level adapters work.
    After boot, only venues in ``_INITIALIZED`` are available.
    """
    if not _STARTUP_COMPLETED:
        return True
    return slug in _INITIALIZED and slug not in _DISABLED


def unavailable_venues() -> list[str]:
    """Enabled venues that have not completed startup (sorted).

    After a full boot this is the degraded set. Before boot (or after aclose)
    it is empty so ``/health`` does not flap outside a running lifespan.
    """
    if not _STARTUP_COMPLETED:
        return []
    return sorted(slug for slug in list_venues() if slug not in _INITIALIZED)


def is_degraded() -> bool:
    """True when at least one enabled venue has not completed startup."""
    return bool(unavailable_venues())


async def startup_all(
    slugs: Sequence[str] | None = None,
) -> StartupReport:
    """Start registered adapters concurrently.

    Transient failures (:class:`AdapterFetchError` / :class:`AdapterTimeoutError`)
    degrade that venue only and are returned in :class:`StartupReport.degraded`.
    Configuration / programmer errors re-raise as :class:`ExceptionGroup` so the
    process refuses to boot (AGENTS.md fail-fast). Failed venues stay out of
    ``_INITIALIZED`` (WHI-823 / WHI-840).
    """
    global _STARTUP_COMPLETED

    if slugs is None:
        items = [(slug, _REGISTRY[slug]) for slug in list_venues()]
    else:
        items = []
        for slug in slugs:
            if slug in _DISABLED:
                continue
            adapter = _REGISTRY.get(slug)
            if adapter is None:
                raise KeyError(f"no adapter registered for {slug!r}")
            items.append((slug, adapter))

    if not items:
        _STARTUP_COMPLETED = True
        return StartupReport()

    results = await asyncio.gather(
        *(adapter.startup() for _, adapter in items),
        return_exceptions=True,
    )

    succeeded: list[str] = []
    degraded: dict[str, Exception] = {}
    fatal: list[Exception] = []

    for (slug, _adapter), result in zip(items, results, strict=True):
        if isinstance(result, Exception):
            logger.error("adapter %r startup failed: %s", slug, result, exc_info=result)
            _INITIALIZED.discard(slug)
            if is_degradable_startup_error(result):
                degraded[slug] = result
                _DEGRADED.add(slug)
            else:
                fatal.append(result)
                _DEGRADED.discard(slug)
        elif isinstance(result, BaseException):
            # CancelledError / KeyboardInterrupt: re-raise immediately.
            raise result
        else:
            _INITIALIZED.add(slug)
            _DEGRADED.discard(slug)
            succeeded.append(slug)

    _STARTUP_COMPLETED = True

    logger.info(
        "adapter startup summary: up=%s down=%s",
        sorted(succeeded) if succeeded else "[]",
        sorted(degraded) if degraded else "[]",
    )

    if fatal:
        raise ExceptionGroup("one or more adapter startups failed fatally", fatal)

    return StartupReport(
        succeeded=tuple(sorted(succeeded)),
        degraded=degraded,
    )


async def retry_uninitialized() -> list[str]:
    """Retry ``startup()`` for venues that failed transiently (``_DEGRADED``).

    Returns the list of slugs that recovered on this attempt. Permanent config
    failures are logged and left out of ``_INITIALIZED`` (no tight loop of
    fatals — callers own the sleep/backoff schedule). Disabled venues are
    never retried.
    """
    pending = [
        (slug, _REGISTRY[slug])
        for slug in sorted(_DEGRADED)
        if slug not in _DISABLED and slug in _REGISTRY
    ]
    if not pending:
        return []

    recovered: list[str] = []
    for slug, adapter in pending:
        try:
            await adapter.startup()
        except Exception as exc:
            if is_degradable_startup_error(exc):
                logger.warning(
                    "adapter %r startup retry still failing (transient): %s",
                    slug,
                    exc,
                )
            else:
                logger.error(
                    "adapter %r startup retry hit non-transient error: %s",
                    slug,
                    exc,
                    exc_info=exc,
                )
                # Config/programmer errors are not retriable.
                _DEGRADED.discard(slug)
            _INITIALIZED.discard(slug)
            continue
        _INITIALIZED.add(slug)
        _DEGRADED.discard(slug)
        recovered.append(slug)
        logger.info("adapter %r recovered after startup retry", slug)

    if recovered:
        logger.info(
            "adapter startup retry recovered: %s (still down: %s)",
            recovered,
            sorted(_DEGRADED),
        )
    return recovered


async def run_startup_retry_loop(
    *,
    interval_sec: float,
    backoff_multiplier: float,
    max_interval_sec: float,
    stop_event: asyncio.Event,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """Background loop: retry degraded venues with exponential backoff (WHI-840).

    ``interval_sec <= 0`` disables the loop immediately. Respects ``stop_event``
    between sleeps so shutdown is prompt. Never busy-loops.
    """
    if interval_sec <= 0:
        return

    sleep_fn = sleep or asyncio.sleep
    current = interval_sec

    while not stop_event.is_set():
        try:
            await sleep_fn(current)
        except asyncio.CancelledError:
            raise

        if stop_event.is_set():
            break

        if not _DEGRADED:
            current = interval_sec
            continue

        recovered = await retry_uninitialized()
        if recovered and not _DEGRADED:
            current = interval_sec
        elif recovered:
            # Partial recovery — keep probing remaining failures at base interval.
            current = interval_sec
        else:
            current = min(current * backoff_multiplier, max_interval_sec)


async def aclose_all() -> None:
    """Close every registered adapter concurrently; clear initialized set."""
    global _STARTUP_COMPLETED
    items = list(_REGISTRY.items())
    if items:
        results = await asyncio.gather(
            *(adapter.aclose() for _, adapter in items),
            return_exceptions=True,
        )
        for (slug, _adapter), result in zip(items, results, strict=True):
            if isinstance(result, BaseException):
                logger.error("adapter %r aclose failed: %s", slug, result, exc_info=result)
    _INITIALIZED.clear()
    _DEGRADED.clear()
    _STARTUP_COMPLETED = False
