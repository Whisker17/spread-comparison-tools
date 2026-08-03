"""Decorator-based adapter self-registration.

Each adapter lives in its own module and registers via ``@register_adapter`` so
parallel adapter PRs never edit a shared switchboard file.
"""

from __future__ import annotations

from spread_compare.adapters.base import VenueAdapter

_REGISTRY: dict[str, VenueAdapter] = {}


def register_adapter[T: VenueAdapter](cls: type[T]) -> type[T]:
    """Instantiate ``cls`` and register it under ``instance.venue``."""
    instance = cls()
    slug = instance.venue
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
