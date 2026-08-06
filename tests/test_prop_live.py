"""Live smoke tests for prop AMM adapters (WHI-806).

Requires ``--live`` and network. Skipped in CI by default (conftest).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

import spread_compare.adapters  # noqa: F401
from spread_compare.adapters import get
from spread_compare.models import ReferenceMid

_NOTIONALS = (Decimal("1000"), Decimal("10000"))

_SOLANA_SLUGS = ("humidifi", "tessera_solana", "bisonfi")


def _mid(asset: str, price: str) -> ReferenceMid:
    return ReferenceMid(
        snapshot_id="live-prop",
        asset=asset,
        mid=Decimal(price),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.parametrize("slug", _SOLANA_SLUGS)
async def test_live_jupiter_sol_usdc(slug: str) -> None:
    """Solana ×3: SOL/USDC at $1k and $10k returns invariant-passing Quote."""
    adapter = get(slug)
    await adapter.startup()
    try:
        mid = _mid("SOL", "150")
        ok_count = 0
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("SOL", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status == "no_quote":
                    assert quote.effective_price is None
                    continue
                ok_count += 1
                assert quote.effective_price is not None
                assert quote.spread_bps is not None
                assert quote.qty_base is not None
                assert quote.fee_breakdown.embedded_in_price is True
                assert quote.fee_breakdown.gas_unknown is False
                assert quote.total_cost_bps is not None
                assert quote.instrument_type == "prop_amm"
                if side == "buy":
                    assert quote.qty_method == "quote_exact_in_approx"
                else:
                    assert quote.qty_method == "base_from_mid"
        assert ok_count >= 1, f"{slug}: expected at least one ok SOL/USDC quote"
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_base_weth_usdc() -> None:
    adapter = get("tessera_base")
    await adapter.startup()
    try:
        mid = _mid("ETH", "3000")
        ok_count = 0
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("ETH", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status != "ok":
                    continue
                ok_count += 1
                assert quote.fee_breakdown.gas_unknown is False
                assert quote.fee_breakdown.gas_usd is not None
                assert quote.effective_price is not None
                assert quote.total_cost_bps is not None
        assert ok_count >= 1, "tessera_base: expected at least one ok WETH/USDC quote"
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_bsc_btcb_usdt() -> None:
    adapter = get("tessera_bsc")
    await adapter.startup()
    try:
        mid = _mid("BTC", "100000")
        ok_count = 0
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("BTC", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status != "ok":
                    continue
                ok_count += 1
                assert quote.venue_symbol == "BTCB/USDT"
                assert quote.effective_price is not None
        assert ok_count >= 1, "tessera_bsc: expected at least one ok BTCB/USDT quote"
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_bsc_qqq_bstock_usdt() -> None:
    adapter = get("tessera_bsc")
    await adapter.startup()
    try:
        mid = _mid("QQQ", "500")
        quote = await adapter.get_quote(
            "QQQ", "buy", Decimal("1000"), mid=mid, form="bstock"
        )
        assert quote.status == "ok", quote.error_message
        assert quote.form == "bstock"
        assert quote.qty_method == "quote_exact_in_approx"
        assert quote.effective_price is not None
        assert quote.fee_breakdown.gas_unknown is False
        assert quote.total_cost_bps is not None
    finally:
        await adapter.aclose()
