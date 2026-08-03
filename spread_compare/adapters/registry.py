"""Decorator-based adapter self-registration and lifecycle (WHI-823).

Each adapter lives in its own module and registers via ``@register_adapter`` so
parallel adapter PRs never edit a shared switchboard file. Discovery imports
those modules; this registry owns instances and startup/shutdown.
"""

from __future__ import annotations

import asyncio
import logging

from spread_compare.adapters.base import VenueAdapter
from spread_compare.venues import known_slugs

# Scaffold-only adapter slug (not a production venue in WHI-799 §6.5).
_EXTRA_ALLOWED_SLUGS: frozenset[str] = frozenset({"mock"})

_REGISTRY: dict[str, VenueAdapter] = {}
_INITIALIZED: set[str] = set()

logger = logging.getLogger(__name__)


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
    """Return the registered adapter for ``slug`` or raise KeyError."""
    try:
        return _REGISTRY[slug]
    except KeyError as exc:
        known = ", ".join(sorted(_REGISTRY)) or "(none)"
        raise KeyError(f"no adapter registered for {slug!r}; known: {known}") from exc


def list_venues() -> list[str]:
    """Sorted list of registered adapter slugs."""
    return sorted(_REGISTRY)


def initialized_count() -> int:
    """Number of adapters whose ``startup()`` completed successfully."""
    return len(_INITIALIZED)


async def startup_all() -> None:
    """Start every registered adapter concurrently.

    Per-adapter failures are logged and re-raised as an :class:`ExceptionGroup`
    so a venue that cannot initialize never appears as healthy.
    """
    items = list(_REGISTRY.items())
    if not items:
        return

    results = await asyncio.gather(
        *(adapter.startup() for _, adapter in items),
        return_exceptions=True,
    )

    failures: list[Exception] = []
    for (slug, _adapter), result in zip(items, results, strict=True):
        if isinstance(result, Exception):
            logger.error("adapter %r startup failed: %s", slug, result, exc_info=result)
            failures.append(result)
        elif isinstance(result, BaseException):
            # CancelledError / KeyboardInterrupt: re-raise immediately.
            raise result
        else:
            _INITIALIZED.add(slug)

    if failures:
        raise ExceptionGroup("one or more adapter startups failed", failures)


async def aclose_all() -> None:
    """Close every registered adapter concurrently; clear initialized set."""
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
