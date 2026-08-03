"""Adapter lifecycle, registry startup, and BaseAdapter invariants (WHI-823)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest

from spread_compare.adapters.base import BaseAdapter
from spread_compare.adapters.registry import (
    _INITIALIZED,
    _REGISTRY,
    aclose_all,
    get,
    initialized_count,
    list_venues,
    startup_all,
)
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)


@pytest.mark.asyncio
async def test_base_adapter_startup_idempotent() -> None:
    adapter = BaseAdapter()
    await adapter.startup()
    assert adapter._started is True
    await adapter.startup()
    assert adapter._started is True
    await adapter.aclose()
    assert adapter._started is False


@pytest.mark.asyncio
async def test_base_adapter_aclose_without_startup() -> None:
    adapter = BaseAdapter()
    await adapter.aclose()  # must not raise


@pytest.mark.asyncio
async def test_base_adapter_lazy_http_client() -> None:
    # trust_env=False avoids requiring socksio when the host has a SOCKS proxy env.
    adapter = BaseAdapter(trust_env=False)
    assert adapter._client is None
    client = adapter.http
    assert adapter.http is client
    await adapter.aclose()
    assert adapter._client is None


@pytest.mark.asyncio
async def test_startup_all_initializes_mock() -> None:
    _INITIALIZED.clear()
    await aclose_all()
    assert initialized_count() == 0
    await startup_all()
    try:
        assert initialized_count() >= 1
        assert "mock" in _INITIALIZED
    finally:
        await aclose_all()
        assert initialized_count() == 0


@pytest.mark.asyncio
async def test_startup_all_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venue whose startup raises must fail the group, not register as healthy."""

    class BoomAdapter(BaseAdapter):
        venue: str = "binance"
        venue_class: VenueClass = "cex"

        async def startup(self) -> None:
            raise RuntimeError("simulated init failure")

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
            raise NotImplementedError

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

    boom = BoomAdapter()
    monkeypatch.setitem(_REGISTRY, "binance", boom)
    _INITIALIZED.discard("binance")

    with pytest.raises(ExceptionGroup) as exc_info:
        await startup_all()

    assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)
    assert "binance" not in _INITIALIZED

    # Cleanup: drop boom and close real adapters if any started.
    _REGISTRY.pop("binance", None)
    await aclose_all()


@pytest.mark.asyncio
async def test_mock_still_registered() -> None:
    assert "mock" in list_venues()
    assert get("mock").venue == "mock"
