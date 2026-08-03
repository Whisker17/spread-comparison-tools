"""Adapter lifecycle, registry startup, and BaseAdapter invariants (WHI-823)."""

from __future__ import annotations

from typing import Any

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
from tests.adapter_fakes import StubAdapter


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
async def test_base_adapter_lazy_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Any] = []

    class FakeClient:
        async def aclose(self) -> None:
            return None

    def fake_async_client(**kwargs: object) -> FakeClient:
        client = FakeClient()
        created.append((client, kwargs))
        return client

    monkeypatch.setattr(
        "spread_compare.adapters.base.httpx.AsyncClient",
        fake_async_client,
    )
    adapter = BaseAdapter(timeout=3.5)
    assert adapter._client is None
    client = adapter.http
    assert adapter.http is client
    assert len(created) == 1
    assert created[0][1] == {"timeout": 3.5}
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
        # Second call is safe (per-adapter startup is idempotent).
        count_after_first = initialized_count()
        await startup_all()
        assert initialized_count() == count_after_first
    finally:
        await aclose_all()
        assert initialized_count() == 0


@pytest.mark.asyncio
async def test_startup_all_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    """A venue whose startup raises must fail the group, not register as healthy."""

    class BoomAdapter(StubAdapter):
        venue: str = "binance"

        async def startup(self) -> None:
            raise RuntimeError("simulated init failure")

    boom = BoomAdapter()
    monkeypatch.setitem(_REGISTRY, "binance", boom)
    _INITIALIZED.discard("binance")

    with pytest.raises(ExceptionGroup) as exc_info:
        await startup_all()

    assert any(isinstance(e, RuntimeError) for e in exc_info.value.exceptions)
    assert "binance" not in _INITIALIZED

    await aclose_all()


@pytest.mark.asyncio
async def test_aclose_all_clears_even_when_one_aclose_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One aclose failure is logged; _INITIALIZED is still fully cleared."""

    class BoomCloseAdapter(StubAdapter):
        venue: str = "binance"

        async def aclose(self) -> None:
            raise RuntimeError("simulated close failure")

    boom = BoomCloseAdapter()
    monkeypatch.setitem(_REGISTRY, "binance", boom)
    _INITIALIZED.add("binance")
    _INITIALIZED.add("mock")

    await aclose_all()
    assert initialized_count() == 0


@pytest.mark.asyncio
async def test_mock_still_registered() -> None:
    assert "mock" in list_venues()
    assert get("mock").venue == "mock"
