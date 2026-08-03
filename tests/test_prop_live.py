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
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("SOL", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status == "no_quote":
                    # Transient empty market is acceptable; still must pass invariants.
                    assert quote.effective_price is None
                    continue
                assert quote.status == "ok"
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
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_base_weth_usdc() -> None:
    adapter = get("tessera_base")
    await adapter.startup()
    try:
        mid = _mid("ETH", "3000")
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("ETH", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status != "ok":
                    continue
                assert quote.fee_breakdown.gas_usd is not None or quote.fee_breakdown.gas_unknown
                assert quote.effective_price is not None
                assert quote.total_cost_bps is not None or quote.fee_breakdown.gas_unknown
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_bsc_btcb_usdt() -> None:
    adapter = get("tessera_bsc")
    await adapter.startup()
    try:
        mid = _mid("BTC", "100000")
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("BTC", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if quote.status != "ok":
                    continue
                assert quote.venue_symbol == "BTCB/USDT"
                assert quote.effective_price is not None
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_tessera_bsc_qqqb_usdt() -> None:
    adapter = get("tessera_bsc")
    await adapter.startup()
    try:
        mid = _mid("QQQB", "500")
        quote = await adapter.get_quote("QQQB", "buy", Decimal("1000"), mid=mid)
        assert quote.status in ("ok", "no_quote"), quote.error_message
        if quote.status == "ok":
            assert quote.qty_method == "quote_exact_in_approx"
            assert quote.effective_price is not None
            assert quote.total_cost_bps is not None or quote.fee_breakdown.gas_unknown
    finally:
        await adapter.aclose()
