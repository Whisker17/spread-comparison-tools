"""Live smoke tests for AMM DEX adapters (WHI-804).

Requires ``--live`` and RPC env vars. Skipped in CI by default (conftest).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest

import spread_compare.adapters  # noqa: F401
from spread_compare.adapters import get
from spread_compare.models import ReferenceMid

# WHI-799 §4.1 tiers; $1M may hit insufficient depth on thin pairs — still exercise.
_NOTIONALS = (
    Decimal("1000"),
    Decimal("10000"),
    Decimal("100000"),
    Decimal("1000000"),
)


def _require(name: str) -> str:
    from spread_compare.adapters._amm_common import load_dotenv_once

    load_dotenv_once()
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.fail(f"live test requires {name}")
    return value


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_uniswap_eth_usdc() -> None:
    _require("ETH_RPC_URL")
    mid = ReferenceMid(
        snapshot_id="live-uni",
        asset="ETH",
        mid=Decimal("3000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    adapter = get("uniswap_eth")
    await adapter.startup()
    try:
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("ETH", side, n, mid=mid)
                assert quote.status in ("ok", "no_quote"), quote.error_message
                if n >= Decimal("1000000") and quote.status == "no_quote":
                    continue  # deep size may lack liquidity
                assert quote.status == "ok", quote.error_message
                assert quote.fee_breakdown.gas_usd is not None
                assert quote.fee_breakdown.gas_bps is not None
                assert quote.fee_breakdown.gas_unknown is False
                assert quote.total_cost_bps is not None
                assert quote.effective_price is not None
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_aerodrome_eth_usdc() -> None:
    _require("BASE_RPC_URL")
    mid = ReferenceMid(
        snapshot_id="live-aero",
        asset="ETH",
        mid=Decimal("3000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    adapter = get("aerodrome_base")
    await adapter.startup()
    try:
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("ETH", side, n, mid=mid)
                if n >= Decimal("1000000") and quote.status == "no_quote":
                    continue
                assert quote.status == "ok", quote.error_message
                assert quote.effective_price is not None
                assert quote.qty_base is not None
                if side == "buy":
                    assert quote.qty_method == "quote_exact_in_approx"
                if not quote.fee_breakdown.gas_unknown:
                    assert quote.fee_breakdown.gas_usd is not None
                    assert quote.fee_breakdown.gas_bps is not None
                    assert quote.total_cost_bps is not None
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_pancake_btcb_usdt() -> None:
    _require("BSC_RPC_URL")
    mid = ReferenceMid(
        snapshot_id="live-pcs",
        asset="BTC",
        mid=Decimal("100000"),
        mid_source="binance_usdm_index",
        timestamp=datetime.now(tz=UTC),
    )
    adapter = get("pancakeswap_bsc")
    await adapter.startup()
    try:
        for n in _NOTIONALS:
            for side in ("buy", "sell"):
                quote = await adapter.get_quote("BTC", side, n, mid=mid)
                if n >= Decimal("1000000") and quote.status == "no_quote":
                    continue
                assert quote.status == "ok", quote.error_message
                assert quote.fee_breakdown.gas_usd is not None
                assert quote.fee_breakdown.gas_bps is not None
                assert quote.fee_breakdown.gas_unknown is False
                assert quote.total_cost_bps is not None
    finally:
        await adapter.aclose()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_pancake_phase_a_bstock_spy() -> None:
    """WHI-891: thickest Phase-A bStock (SPYB) quotes at $1k both sides."""
    _require("BSC_RPC_URL")
    mid = ReferenceMid(
        snapshot_id="live-pcs-spy",
        asset="SPY",
        mid=Decimal("600"),
        mid_source="proxy_perp_mark_median",
        timestamp=datetime.now(tz=UTC),
    )
    adapter = get("pancakeswap_bsc")
    await adapter.startup()
    try:
        n = Decimal("1000")
        for side in ("buy", "sell"):
            quote = await adapter.get_quote(
                "SPY", side, n, mid=mid, form="bstock"
            )
            assert quote.status == "ok", quote.error_message
            assert quote.effective_price is not None
            assert quote.qty_base is not None
            assert quote.venue_symbol is not None and "SPYB" in quote.venue_symbol
    finally:
        await adapter.aclose()
