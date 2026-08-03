"""Venue adapters and registry.

Importing this package loads built-in adapters so they self-register.
"""

from __future__ import annotations

from spread_compare.adapters import mock as _mock  # noqa: F401
from spread_compare.adapters.base import AdapterError, VenueAdapter
from spread_compare.adapters.registry import get, list_venues, register_adapter

__all__ = [
    "AdapterError",
    "VenueAdapter",
    "get",
    "list_venues",
    "register_adapter",
]
