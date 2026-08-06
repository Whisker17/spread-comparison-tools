"""Adapter auto-discovery: new modules register without editing existing files."""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

import spread_compare.adapters as adapters_pkg
from spread_compare.adapters import discover_adapters, list_venues
from spread_compare.adapters.registry import _REGISTRY

_MODULE_NAME = "throwaway_whi823_discovery"
# Test-only slug in registry._EXTRA_ALLOWED_SLUGS — never a production venue
# (WHI-802: registering real bybit would break this test if it claimed "bybit").
_SLUG = "_test_discovery"


def _package_dir() -> Path:
    return Path(adapters_pkg.__file__).resolve().parent


def _module_path() -> Path:
    return _package_dir() / f"{_MODULE_NAME}.py"


def _purge_throwaway() -> None:
    """Best-effort cleanup so a killed test cannot poison later imports."""
    path = _module_path()
    path.unlink(missing_ok=True)
    _REGISTRY.pop(_SLUG, None)
    sys.modules.pop(f"spread_compare.adapters.{_MODULE_NAME}", None)
    package_dir = _package_dir()
    for pyc in package_dir.glob(f"{_MODULE_NAME}*.pyc"):
        pyc.unlink(missing_ok=True)
    cache_dir = package_dir / "__pycache__"
    if cache_dir.is_dir():
        for pyc in cache_dir.glob(f"{_MODULE_NAME}*.pyc"):
            pyc.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def _clean_throwaway_module() -> Iterator[None]:
    _purge_throwaway()
    yield
    _purge_throwaway()


def test_new_adapter_module_auto_registers() -> None:
    """Drop a throwaway module under adapters/; no other file edit required."""
    assert _SLUG not in list_venues()
    # Spec requires a real module under the package (not a tmp_path package).
    source = textwrap.dedent(
        f"""\
        from decimal import Decimal
        from typing import Literal

        from spread_compare.adapters.base import BaseAdapter
        from spread_compare.adapters.registry import register_adapter
        from spread_compare.models import (
            FeeSchedule,
            InstrumentType,
            Quote,
            ReferenceMid,
            Side,
            TopOfBook,
            VenueClass,
        )


        @register_adapter
        class ThrowawayAdapter(BaseAdapter):
            venue: str = {_SLUG!r}
            venue_class: VenueClass = "cex"

            async def get_quote(
                self,
                asset: str,
                side: Side,
                notional_usd: Decimal,
                *,
                mid: ReferenceMid,
                instrument_type: InstrumentType | None = None,
                fee_tier: str | None = None,
            form: str | None = None,
            ) -> Quote:
                raise NotImplementedError

            async def get_orderbook_spread(
                self,
                asset: str,
                *,
                mid: ReferenceMid,
                instrument_type: Literal["spot", "perp"] | None = None,
            form: str | None = None,
            ) -> TopOfBook | None:
                return None

            def get_fees(
                self,
                asset: str | None = None,
                *,
                instrument_type: InstrumentType | None = None,
            ) -> FeeSchedule:
                raise NotImplementedError

            def supported_assets(
                self,
                *,
                instrument_type: InstrumentType | None = None,
            ) -> list[str]:
                return []
        """
    )
    _module_path().write_text(source, encoding="utf-8")
    discover_adapters()
    assert _SLUG in list_venues()


def test_discover_adapters_is_idempotent() -> None:
    """Re-running discovery must not re-register already-loaded adapters."""
    before = list_venues()
    discover_adapters()
    assert list_venues() == before
