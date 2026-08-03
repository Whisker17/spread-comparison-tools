"""Adapter auto-discovery: new modules register without editing existing files."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import spread_compare.adapters as adapters_pkg
from spread_compare.adapters import discover_adapters, list_venues
from spread_compare.adapters.registry import _REGISTRY


def test_new_adapter_module_auto_registers() -> None:
    """Drop a throwaway module under adapters/; no other file edit required."""
    package_dir = Path(adapters_pkg.__file__).resolve().parent
    module_name = "throwaway_whi823_discovery"
    full_name = f"spread_compare.adapters.{module_name}"
    path = package_dir / f"{module_name}.py"
    slug = "bybit"  # known WHI-799 §6.5 slug, unused by mock

    assert slug not in list_venues()
    source = textwrap.dedent(
        f"""\
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
        from decimal import Decimal
        from typing import Literal


        @register_adapter
        class ThrowawayAdapter(BaseAdapter):
            venue: str = {slug!r}
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
            ) -> Quote:
                raise NotImplementedError

            async def get_orderbook_spread(
                self,
                asset: str,
                *,
                mid: ReferenceMid,
                instrument_type: Literal["spot", "perp"] | None = None,
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

    path.write_text(source, encoding="utf-8")
    try:
        discover_adapters()
        assert slug in list_venues()
    finally:
        path.unlink(missing_ok=True)
        _REGISTRY.pop(slug, None)
        sys.modules.pop(full_name, None)
        # Drop bytecode cache if present.
        for pyc in package_dir.glob(f"{module_name}*.pyc"):
            pyc.unlink(missing_ok=True)
        cache_dir = package_dir / "__pycache__"
        if cache_dir.is_dir():
            for pyc in cache_dir.glob(f"{module_name}*.pyc"):
                pyc.unlink(missing_ok=True)


def test_discover_adapters_is_idempotent() -> None:
    """Re-running discovery must not re-register already-loaded adapters."""
    before = list_venues()
    discover_adapters()
    assert list_venues() == before
