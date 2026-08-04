"""Venue adapters and registry.

Importing this package auto-discovers adapter modules so they self-register
(``@register_adapter``). New venue modules under this package need no edit here.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from spread_compare.adapters.base import AdapterError, BaseAdapter, VenueAdapter
from spread_compare.adapters.registry import (
    StartupReport,
    aclose_all,
    clear_disabled_venues,
    disabled_venues,
    expected_adapter_count,
    get,
    initialized_count,
    is_available,
    is_degradable_startup_error,
    is_degraded,
    is_initialized,
    list_venues,
    register_adapter,
    retry_uninitialized,
    run_startup_retry_loop,
    set_disabled_venues,
    startup_all,
    unavailable_venues,
)

# Infrastructure modules — not venue adapters. Spec WHI-823: skip base/registry/__init__.
_SKIP_MODULES: frozenset[str] = frozenset({"base", "registry", "__init__"})


def discover_adapters() -> None:
    """Import every adapter module in this package (except base/registry/__init__).

    Deterministic sorted order. Already-imported modules are not re-executed
    (``importlib`` cache), so re-running is safe for previously loaded adapters.
    Unknown or duplicate slugs still raise via ``register_adapter``.
    """
    package_dir = Path(__file__).resolve().parent
    module_infos = sorted(
        pkgutil.iter_modules([str(package_dir)]),
        key=lambda m: m.name,
    )
    for info in module_infos:
        if info.name in _SKIP_MODULES or info.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{info.name}")


discover_adapters()

__all__ = [
    "AdapterError",
    "BaseAdapter",
    "StartupReport",
    "VenueAdapter",
    "aclose_all",
    "clear_disabled_venues",
    "disabled_venues",
    "discover_adapters",
    "expected_adapter_count",
    "get",
    "initialized_count",
    "is_available",
    "is_degraded",
    "is_degradable_startup_error",
    "is_initialized",
    "list_venues",
    "register_adapter",
    "retry_uninitialized",
    "run_startup_retry_loop",
    "set_disabled_venues",
    "startup_all",
    "unavailable_venues",
]
