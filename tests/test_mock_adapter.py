"""Mock adapter + registry acceptance checks (WHI-801 / WHI-823 async)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import spread_compare.adapters  # noqa: F401 — ensure self-registration
from spread_compare.adapters import get
from spread_compare.models import Quote, ReferenceMid

_MID = ReferenceMid(
    snapshot_id="snap-test",
    asset="BTC",
    mid=Decimal("100000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)


def test_registry_has_mock() -> None:
    adapter = get("mock")
    assert adapter.venue == "mock"


@pytest.mark.asyncio
async def test_mock_get_quote_buy_canonical() -> None:
    adapter = get("mock")
    quote = await adapter.get_quote("BTC", "buy", Decimal("10000"), mid=_MID)
    assert isinstance(quote, Quote)
    assert quote.status == "ok"
    assert quote.effective_price == Decimal("100044")
    assert quote.spread_bps == Decimal("4.4")
    assert quote.total_cost_bps == Decimal("14.4")
    assert quote.qty_base == Decimal("0.1")
    assert quote.fee_breakdown.explicit_fee_bps == Decimal("10")
    assert quote.snapshot_id == _MID.snapshot_id


@pytest.mark.asyncio
async def test_mock_get_quote_sell_canonical() -> None:
    adapter = get("mock")
    quote = await adapter.get_quote("BTC", "sell", Decimal("10000"), mid=_MID)
    assert quote.status == "ok"
    assert quote.effective_price == Decimal("99956")
    assert quote.spread_bps == Decimal("4.4")


@pytest.mark.asyncio
async def test_mock_orderbook_spread() -> None:
    adapter = get("mock")
    tob = await adapter.get_orderbook_spread("BTC", mid=_MID)
    assert tob is not None
    assert tob.best_bid == Decimal("99990")
    assert tob.best_ask == Decimal("100010")
