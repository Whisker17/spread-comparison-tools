"""Unit tests for AMM DEX adapters (WHI-804 / WHI-836) — mocked eth_call, no network."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from eth_abi import encode

import spread_compare.adapters  # noqa: F401 — ensure registration
from spread_compare.adapters import get, list_venues
from spread_compare.adapters._amm_common import (
    UNISWAP_FEE_TIERS,
    decode_quoter_v2_result,
    encode_quote_exact_input_single,
    encode_quote_exact_output_single,
    fee_to_lp_bps,
    probe_quoter_v2,
)
from spread_compare.adapters.amm_aerodrome import AerodromeBaseAdapter
from spread_compare.adapters.amm_pancakeswap import PancakeSwapBscAdapter
from spread_compare.adapters.amm_uniswap import UniswapEthAdapter
from spread_compare.models import Quote, ReferenceMid

_MID_ETH = ReferenceMid(
    snapshot_id="snap-amm",
    asset="ETH",
    mid=Decimal("3000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)
_MID_BTC = ReferenceMid(
    snapshot_id="snap-amm",
    asset="BTC",
    mid=Decimal("100000"),
    mid_source="binance_usdm_index",
    timestamp=datetime(2026, 8, 3, tzinfo=UTC),
)


def _encode_quoter_result(
    amount: int,
    *,
    gas_estimate: int = 150_000,
) -> bytes:
    return encode(
        ["uint256", "uint160", "uint32", "uint256"],
        [amount, 1, 1, gas_estimate],
    )


def _encode_uint256(amount: int) -> bytes:
    return encode(["uint256"], [amount])


def _encode_amounts_out(amounts: list[int]) -> bytes:
    return encode(["uint256[]"], [amounts])


class _FakeRpc:
    """Scripted RpcClient stand-in."""

    def __init__(
        self,
        *,
        call_handler: Any,
        gas_price_wei: int | None = 30_000_000_000,
    ) -> None:
        self._call_handler = call_handler
        self._gas_price_wei = gas_price_wei
        self.eth_calls: list[tuple[str, bytes]] = []

    async def eth_call(self, to: str, data: bytes) -> bytes:
        self.eth_calls.append((to, data))
        return await self._call_handler(to, data)

    async def eth_gas_price(self) -> int:
        if self._gas_price_wei is None:
            from spread_compare.adapters._amm_common import JsonRpcError

            raise JsonRpcError("gas price unavailable")
        return self._gas_price_wei


@pytest.fixture
def eth_rpc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ETH_RPC_URL", "http://rpc.test/eth")
    monkeypatch.setenv("BASE_RPC_URL", "http://rpc.test/base")
    monkeypatch.setenv("BSC_RPC_URL", "http://rpc.test/bsc")


def test_adapters_registered() -> None:
    venues = list_venues()
    assert "uniswap_eth" in venues
    assert "aerodrome_base" in venues
    assert "pancakeswap_bsc" in venues


def test_pancakeswap_supports_bstocks() -> None:
    """WHI-826: P0-A tokenized stocks on PancakeSwap BSC."""
    adapter = get("pancakeswap_bsc")
    supported = set(adapter.supported_assets())
    assert {"BTC", "ETH", "QQQB", "SPCXB", "NVDAB", "NVDAON"} <= supported
    # Token addresses must stay aligned with Tessera BSC (single SSOT).
    from spread_compare.adapters._prop_common import BSC_TOKENS
    from spread_compare.adapters.amm_pancakeswap import PancakeSwapBscAdapter

    pcs = PancakeSwapBscAdapter()
    for asset in ("QQQB", "SPCXB", "NVDAB", "NVDAON"):
        assert pcs._base_token(asset).address == BSC_TOKENS[asset].address


def test_encode_decode_quoter_roundtrip() -> None:
    data = encode_quote_exact_input_single(
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        1_000_000_000,
        500,
    )
    assert data[:4].hex() == "c6a5026a"
    result = _encode_quoter_result(999_000_000, gas_estimate=120_000)
    amount, _, _, gas = decode_quoter_v2_result(result)
    assert amount == 999_000_000
    assert gas == 120_000
    assert fee_to_lp_bps(500) == Decimal("5")
    out_data = encode_quote_exact_output_single(
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        10**18,
        500,
    )
    assert out_data[:4].hex() == "bd21704a"


def test_no_aggregator_endpoints_in_amm_modules() -> None:
    adapters_dir = Path(__file__).resolve().parents[1] / "spread_compare" / "adapters"
    forbidden = ("api.0x.org", "api.1inch", "0x.org", "1inch.dev")
    for path in adapters_dir.glob("amm_*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} must not reference {needle}"
    common = adapters_dir / "_amm_common.py"
    text = common.read_text(encoding="utf-8")
    for needle in forbidden:
        assert needle not in text


@pytest.mark.asyncio
async def test_sol_unsupported_on_all_amm(eth_rpc_env: None) -> None:
    mid = ReferenceMid(
        snapshot_id="s",
        asset="SOL",
        mid=Decimal("150"),
        mid_source="binance_usdm_index",
        timestamp=datetime(2026, 8, 3, tzinfo=UTC),
    )
    for slug in ("uniswap_eth", "aerodrome_base", "pancakeswap_bsc"):
        adapter = get(slug)
        await adapter.startup()
        try:
            quote = await adapter.get_quote("SOL", "buy", Decimal("1000"), mid=mid)
            assert quote.status == "unsupported_asset"
            assert quote.effective_price is None
            assert quote.total_cost_bps is None
        finally:
            await adapter.aclose()


@pytest.mark.asyncio
async def test_orderbook_spread_is_none(eth_rpc_env: None) -> None:
    adapter = get("uniswap_eth")
    await adapter.startup()
    try:
        assert await adapter.get_orderbook_spread("ETH", mid=_MID_ETH) is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_uniswap_sell_ok_with_gas(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    # Sell 1000/3000 ETH → amount_in raw; return USDC amount_out slightly worse than mid.
    # mid=3000 → fair USDC for q_star = 1000; return 995 USDC (6 decimals) → price < mid for sell? 
    # sell spread = (mid - P)/mid; if P < mid, positive spread (worse).
    usdc_out = 995_000_000  # $995 for ~0.333 ETH → P = 995 / (1000/3000) = 2985

    async def handler(to: str, data: bytes) -> bytes:
        assert to.lower() == "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"
        # Prefer fee 500
        if data[:4].hex() == "c6a5026a":
            # decode fee from encoded params — just return for every tier
            return _encode_quoter_result(usdc_out, gas_estimate=180_000)
        raise AssertionError(f"unexpected selector {data[:4].hex()}")

    fake = _FakeRpc(call_handler=handler, gas_price_wei=20_000_000_000)
    adapter._rpc = fake  # type: ignore[assignment]

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        assert symbol == "ETHUSDT"
        return Decimal("3000")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )

    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert isinstance(quote, Quote)
        assert quote.status == "ok"
        assert quote.venue == "uniswap_eth"
        assert quote.fee_breakdown.embedded_in_price is True
        assert quote.qty_method == "base_from_mid"
        assert quote.qty_base == pytest.approx(Decimal("1000") / Decimal("3000"))
        assert quote.effective_price is not None
        assert quote.spread_bps is not None
        assert quote.fee_breakdown.gas_unknown is False
        assert quote.fee_breakdown.gas_usd is not None
        assert quote.fee_breakdown.gas_bps is not None
        assert quote.total_cost_bps is not None
        assert quote.fee_breakdown.lp_fee_tier_bps is not None
        # trading component must not include LP fee
        assert quote.fee_breakdown.trading_fee_bps is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_uniswap_buy_exact_out(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    # Buy ExactOut: amount_out = q_star base; amount_in = quote spent.
    # q_star = 1000/3000 ETH; return amount_in = 1005 USDC → P = 1005 / q_star
    usdc_in = 1_005_000_000

    async def handler(to: str, data: bytes) -> bytes:
        if data[:4].hex() == "bd21704a":
            return _encode_quoter_result(usdc_in, gas_estimate=160_000)
        raise AssertionError(f"buy must use ExactOut, got {data[:4].hex()}")

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        return Decimal("3000")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )
    try:
        quote = await adapter.get_quote("ETH", "buy", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "ok"
        assert quote.qty_method == "base_from_mid"
        assert quote.qty_base == pytest.approx(Decimal("1000") / Decimal("3000"))
        assert quote.fee_breakdown.gas_unknown is False
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_gas_unknown_when_gas_price_fails(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    async def handler(to: str, data: bytes) -> bytes:
        return _encode_quoter_result(995_000_000, gas_estimate=100_000)

    adapter._rpc = _FakeRpc(call_handler=handler, gas_price_wei=None)  # type: ignore[assignment]

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        return Decimal("3000")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "ok"
        assert quote.fee_breakdown.gas_unknown is True
        assert quote.fee_breakdown.gas_bps is None
        assert quote.fee_breakdown.explicit_fee_bps is None
        assert quote.total_cost_bps is None
        # invariants still hold via pydantic
        assert quote.effective_price is not None
        assert quote.spread_bps is not None
        assert quote.qty_base is not None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_aerodrome_buy_uses_quote_exact_in_approx(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AerodromeBaseAdapter()
    await adapter.startup()

    # ExactIn USDC amount = notional (6 decimals) = 1000e6
    # Return base WETH amount slightly below fair: fair = 1000/3000 ETH
    fair_wei = int((Decimal("1000") / Decimal("3000")) * Decimal(10**18))
    weth_out = fair_wei * 99 // 100  # 1% worse

    async def handler(to: str, data: bytes) -> bytes:
        sel = data[:4].hex()
        if sel == "891e50c6":  # V3 CL
            return _encode_quoter_result(weth_out, gas_estimate=200_000)
        if sel == "c550b186":  # V2
            return _encode_uint256(0)
        if sel == "5509a1ac":  # router getAmountsOut — no liquidity
            from spread_compare.adapters._amm_common import JsonRpcError

            raise JsonRpcError("execution reverted", transport=False, revert=True)
        raise AssertionError(f"unexpected selector {sel}")

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        return Decimal("3000")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )
    try:
        quote = await adapter.get_quote("ETH", "buy", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "ok"
        assert quote.qty_method == "quote_exact_in_approx"
        assert quote.qty_base is not None
        # actual base filled is less than mid-implied q_star
        assert quote.qty_base < Decimal("1000") / Decimal("3000")
        assert quote.effective_price is not None
        assert quote.effective_price > _MID_ETH.mid  # paid more than mid
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_aerodrome_router_fallback(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = AerodromeBaseAdapter()
    await adapter.startup()

    usdc_out = 995_000_000

    async def handler(to: str, data: bytes) -> bytes:
        from spread_compare.adapters._amm_common import JsonRpcError

        sel = data[:4].hex()
        if sel in ("891e50c6", "c550b186"):
            raise JsonRpcError("no pool", transport=False, revert=True)
        if sel == "5509a1ac":  # getAmountsOut
            return _encode_amounts_out([10**17, usdc_out])
        raise AssertionError(sel)

    adapter._rpc = _FakeRpc(call_handler=handler, gas_price_wei=None)  # type: ignore[assignment]

    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "ok"
        assert quote.fee_breakdown.fee_tier in (
            "router_volatile",
            "router_stable",
            "v2_volatile",
            "v2_stable",
        )
        # no gasEstimate on V2/router path → gas_unknown (not silently 0)
        assert quote.fee_breakdown.gas_unknown is True
        assert quote.total_cost_bps is None
        assert quote.fee_breakdown.lp_fee_tier_bps is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_pancake_btc_buy_exact_out(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = PancakeSwapBscAdapter()
    await adapter.startup()

    q_star = Decimal("1000") / Decimal("100000")
    # amount_out raw BTCB (18 dec)
    # amount_in USDT slightly above notional
    usdt_in = int(Decimal("1005") * Decimal(10**18))

    async def handler(to: str, data: bytes) -> bytes:
        assert to.lower() == "0xb048bbc1ee6b733fffcfb9e9cef7375518e25997"
        if data[:4].hex() == "bd21704a":
            return _encode_quoter_result(usdt_in, gas_estimate=140_000)
        raise AssertionError(data[:4].hex())

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        assert symbol == "BNBUSDT"
        return Decimal("600")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )
    try:
        quote = await adapter.get_quote("BTC", "buy", Decimal("1000"), mid=_MID_BTC)
        assert quote.status == "ok"
        assert quote.venue == "pancakeswap_bsc"
        assert quote.qty_method == "base_from_mid"
        assert quote.qty_base == pytest.approx(q_star)
        assert quote.fee_breakdown.gas_unknown is False
        assert quote.fee_breakdown.gas_usd is not None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_startup_fails_without_rpc_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ETH_RPC_URL", raising=False)
    # require_env loads .env once; force a re-check against cleared env only.
    import spread_compare.adapters._amm_common as amm_common

    monkeypatch.setattr(amm_common, "_DOTENV_LOADED", True)
    adapter = UniswapEthAdapter()
    with pytest.raises(RuntimeError, match="ETH_RPC_URL"):
        await adapter.startup()


def test_get_fees_are_venue_specific() -> None:
    uni = UniswapEthAdapter()
    pcs = PancakeSwapBscAdapter()
    aero = AerodromeBaseAdapter()
    assert uni.get_fees().lp_fee_tiers_bps == [
        Decimal("1"),
        Decimal("5"),
        Decimal("30"),
        Decimal("100"),
    ]
    assert pcs.get_fees().lp_fee_tiers_bps == [
        Decimal("1"),
        Decimal("5"),
        Decimal("25"),
        Decimal("100"),
    ]
    assert aero.get_fees().lp_fee_tiers_bps is None


@pytest.mark.asyncio
async def test_no_quote_when_all_tiers_revert(
    eth_rpc_env: None,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    async def handler(to: str, data: bytes) -> bytes:
        from spread_compare.adapters._amm_common import JsonRpcError

        raise JsonRpcError("execution reverted", transport=False, revert=True)

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "no_quote"
        assert quote.effective_price is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_probe_quoter_v2_issues_eth_calls_concurrently() -> None:
    """Fee-tier eth_calls run concurrently (WHI-836); peak in-flight == tier count."""
    in_flight = 0
    peak_in_flight = 0
    n_tiers = len(UNISWAP_FEE_TIERS)
    barrier = asyncio.Barrier(n_tiers)

    class _ConcurrentRpc:
        async def eth_call(self, to: str, data: bytes) -> bytes:
            nonlocal in_flight, peak_in_flight
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            await barrier.wait()
            in_flight -= 1
            # Distinct amount_out per call so prefer_quoter_result still picks one.
            amount = 990_000_000 + (data[-4] % 10)
            return _encode_quoter_result(amount, gas_estimate=150_000)

    result = await probe_quoter_v2(
        _ConcurrentRpc(),  # type: ignore[arg-type]
        "0x0000000000000000000000000000000000000001",
        token_base="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        token_quote="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        amount_base_raw=10**18,
        fee_tiers=UNISWAP_FEE_TIERS,
        side="sell",
    )
    assert result is not None
    assert peak_in_flight == n_tiers


@pytest.mark.asyncio
async def test_error_when_rpc_transport_fails(
    eth_rpc_env: None,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    async def handler(to: str, data: bytes) -> bytes:
        from spread_compare.adapters._amm_common import JsonRpcError

        raise JsonRpcError("eth_call transport failed: connect", transport=True)

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "error"
        assert quote.effective_price is None
    finally:
        await adapter.aclose()


@pytest.mark.asyncio
async def test_error_when_rpc_rate_limited(
    eth_rpc_env: None,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    async def handler(to: str, data: bytes) -> bytes:
        from spread_compare.adapters._amm_common import JsonRpcError

        # Infra error that is NOT an execution revert.
        raise JsonRpcError(
            "eth_call error: {'code': -32005, 'message': 'rate limited'}",
            transport=False,
            revert=False,
        )

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "error"
    finally:
        await adapter.aclose()
