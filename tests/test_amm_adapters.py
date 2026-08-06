"""Unit tests for AMM DEX adapters (WHI-804 / WHI-836 / WHI-842) — mocked eth_call."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from eth_abi import encode

import spread_compare.adapters  # noqa: F401 — ensure registration
from spread_compare.adapters import get, list_venues
from spread_compare.adapters._amm_common import (
    MULTICALL3_ADDRESS,
    UNISWAP_FEE_TIERS,
    JsonRpcError,
    RpcClient,
    clear_rpc_endpoint_state,
    decode_multicall3_aggregate3,
    decode_quoter_v2_result,
    encode_multicall3_aggregate3,
    encode_quote_exact_input_single,
    encode_quote_exact_output_single,
    fee_to_lp_bps,
    probe_quoter_v2,
    rpc_endpoint_label,
)
from spread_compare.adapters.amm_aerodrome import AerodromeBaseAdapter
from spread_compare.adapters.amm_pancakeswap import PancakeSwapBscAdapter
from spread_compare.adapters.amm_uniswap import UniswapEthAdapter
from spread_compare.models import Quote, ReferenceMid
from spread_compare.settings import RpcChainBudget

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
    """Scripted RpcClient stand-in with Multicall3-compatible eth_call_many."""

    def __init__(
        self,
        *,
        call_handler: Any,
        gas_price_wei: int | None = 30_000_000_000,
    ) -> None:
        self._call_handler = call_handler
        self._gas_price_wei = gas_price_wei
        self.eth_calls: list[tuple[str, bytes]] = []
        self.eth_call_many_count = 0
        self.gas_price_calls = 0

    async def eth_call(self, to: str, data: bytes) -> bytes:
        self.eth_calls.append((to, data))
        return await self._call_handler(to, data)

    async def eth_call_many(
        self, calls: list[tuple[str, bytes]]
    ) -> list[tuple[bool, bytes | None]]:
        """Simulate Multicall3: per-subcall revert stays local; transport aborts."""
        self.eth_call_many_count += 1
        out: list[tuple[bool, bytes | None]] = []
        for to, data in calls:
            try:
                raw = await self.eth_call(to, data)
            except JsonRpcError as exc:
                if not exc.revert:
                    raise
                out.append((False, None))
            else:
                out.append((True, raw))
        return out

    async def eth_gas_price(self) -> int:
        self.gas_price_calls += 1
        if self._gas_price_wei is None:
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


def test_pancakeswap_supports_stock_underlyings() -> None:
    """WHI-881 / WHI-891: PancakeSwap BSC lists underlyings; form maps to tickers."""
    adapter = get("pancakeswap_bsc")
    supported = set(adapter.supported_assets())
    assert {
        "BTC",
        "ETH",
        "QQQ",
        "SPCX",
        "NVDA",
        "SPY",
        "AAPL",
        "TSLA",
        "MSFT",
        "GOOGL",
        "META",
        "AMZN",
    } <= supported
    # Token addresses must stay aligned with BSC_TOKENS (single SSOT).
    from spread_compare.adapters._prop_common import (
        BSC_STOCK_FORM_TICKER,
        BSC_TOKENS,
    )
    from spread_compare.adapters.amm_pancakeswap import PancakeSwapBscAdapter

    pcs = PancakeSwapBscAdapter()
    assert pcs._base_token("QQQ", form="bstock").address == BSC_TOKENS["QQQB"].address
    assert pcs._base_token("SPCX", form="bstock").address == BSC_TOKENS["SPCXB"].address
    assert pcs._base_token("NVDA", form="bstock").address == BSC_TOKENS["NVDAB"].address
    assert pcs._base_token("NVDA", form="ondo").address == BSC_TOKENS["NVDAON"].address
    # WHI-890 Phase A addresses (survey §3.2).
    phase_a = {
        "SPY": ("bstock", "SPYB", "0x7138b48df7d98d7e3cc221bfe7192d0a178182d8"),
        "AAPL": ("bstock", "AAPLB", "0x431a3bee82e2ca41e49895cbece5bb0f76a89b7a"),
        "TSLA": ("bstock", "TSLAB", "0x5b1910eaad6450e50f816082aa078c41f10c292f"),
        "MSFT": ("bstock", "MSFTB", "0x80106cb3ead06659a5ad19df39d9b4733863b9b0"),
        "GOOGL": ("bstock", "GOOGLB", "0x3f53de71c126bdabae20f9cd64848d317f6c3238"),
        "META": ("bstock", "METAB", "0x7425889fe94f9d693e8daefe88bcced6acfef4c0"),
        "AMZN": ("bstock", "AMZNB", "0x1a4b499833a79a09ad7cf1d42d7dacf71e92eb00"),
    }
    for underlying, (form, ticker, address) in phase_a.items():
        assert BSC_STOCK_FORM_TICKER[(underlying, form)] == ticker
        tok = BSC_TOKENS[ticker]
        assert tok.address.lower() == address.lower()
        assert tok.decimals == 18
        assert pcs._base_token(underlying, form=form).address == tok.address


def test_tessera_bsc_stock_whitelist_unchanged() -> None:
    """WHI-890 Phase B: Tessera stays on the green quartet; no Phase-A fan-out."""
    adapter = get("tessera_bsc")
    supported = set(adapter.supported_assets())
    assert supported == {"BTC", "QQQ", "SPCX", "NVDA"}
    # Phase-A underlyings must not be advertised (no phantom Tessera rows).
    for asset in ("SPY", "AAPL", "TSLA", "MSFT", "GOOGL", "META", "AMZN"):
        assert asset not in supported


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
async def test_probe_quoter_v2_batches_fee_tiers_in_one_eth_call_many() -> None:
    """Fee tiers share one eth_call_many (WHI-842 Multicall3), not N HTTP posts."""

    class _BatchRpc:
        def __init__(self) -> None:
            self.many_count = 0
            self.call_count = 0

        async def eth_call(self, to: str, data: bytes) -> bytes:
            self.call_count += 1
            raise AssertionError("probe_quoter_v2 must use eth_call_many, not eth_call")

        async def eth_call_many(
            self, calls: list[tuple[str, bytes]]
        ) -> list[tuple[bool, bytes | None]]:
            self.many_count += 1
            assert len(calls) == len(UNISWAP_FEE_TIERS)
            out: list[tuple[bool, bytes | None]] = []
            for i, _ in enumerate(calls):
                amount = 990_000_000 + i
                out.append((True, _encode_quoter_result(amount, gas_estimate=150_000)))
            return out

    rpc = _BatchRpc()
    result = await probe_quoter_v2(
        rpc,  # type: ignore[arg-type]
        "0x0000000000000000000000000000000000000001",
        token_base="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        token_quote="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        amount_base_raw=10**18,
        fee_tiers=UNISWAP_FEE_TIERS,
        side="sell",
    )
    assert result is not None
    assert rpc.many_count == 1
    assert rpc.call_count == 0
    # Highest amount_out wins (last tier).
    assert result.amount_out == 990_000_000 + (len(UNISWAP_FEE_TIERS) - 1)


@pytest.mark.asyncio
async def test_probe_quoter_v2_single_tier_revert_does_not_poison_batch() -> None:
    """One reverting fee tier stays no_quote for that tier; others still quote."""

    class _PartialRpc:
        async def eth_call_many(
            self, calls: list[tuple[str, bytes]]
        ) -> list[tuple[bool, bytes | None]]:
            assert len(calls) == 3
            return [
                (False, None),  # fee tier 0 reverts
                (True, _encode_quoter_result(500_000_000, gas_estimate=100_000)),
                (True, _encode_quoter_result(400_000_000, gas_estimate=100_000)),
            ]

    result = await probe_quoter_v2(
        _PartialRpc(),  # type: ignore[arg-type]
        "0x0000000000000000000000000000000000000001",
        token_base="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        token_quote="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        amount_base_raw=10**18,
        fee_tiers=(100, 500, 3000),
        side="sell",
    )
    assert result is not None
    assert result.amount_out == 500_000_000
    assert result.fee_label == "pool_500"


@pytest.mark.asyncio
async def test_error_when_rpc_transport_fails(
    eth_rpc_env: None,
) -> None:
    adapter = UniswapEthAdapter()
    await adapter.startup()

    async def handler(to: str, data: bytes) -> bytes:
        raise JsonRpcError("eth_call transport failed: connect", transport=True)

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "error"
        assert quote.error_code == "adapter_error"
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
        raise JsonRpcError(
            "eth_call rate limited after retries",
            transport=True,
            rate_limited=True,
        )

    adapter._rpc = _FakeRpc(call_handler=handler)  # type: ignore[assignment]
    try:
        quote = await adapter.get_quote("ETH", "sell", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "rate_limited"
        assert quote.error_code == "rate_limited"
        assert quote.effective_price is None
    finally:
        await adapter.aclose()


def _rpc_budget(**overrides: Any) -> RpcChainBudget:
    base = {
        "rps": 50,
        "window_sec": 1.0,
        "max_attempts": 3,
        "backoff_start_sec": 0.5,
        "backoff_max_sec": 8.0,
        "retry_after_floor_sec": 0.05,
        "gas_price_cache_ttl_sec": 15.0,
    }
    base.update(overrides)
    return RpcChainBudget.model_validate(base)


@pytest.mark.asyncio
async def test_aerodrome_get_quote_one_http_request(
    eth_rpc_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aerodrome get_quote is one HTTP: Multicall3 + eth_gasPrice batch (WHI-842)."""
    clear_rpc_endpoint_state()
    request_count = 0
    fair_wei = int((Decimal("1000") / Decimal("3000")) * Decimal(10**18))
    weth_out = fair_wei * 99 // 100

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        import json

        payload = json.loads(request.read())
        # Cold path: JSON-RPC batch [eth_call Multicall3, eth_gasPrice].
        assert isinstance(payload, list)
        assert len(payload) == 2
        call_req = next(p for p in payload if p["method"] == "eth_call")
        gas_req = next(p for p in payload if p["method"] == "eth_gasPrice")
        to = call_req["params"][0]["to"].lower()
        assert to == MULTICALL3_ADDRESS.lower()
        calldata = bytes.fromhex(call_req["params"][0]["data"][2:])
        from eth_abi.abi import decode as abi_decode

        assert calldata[:4].hex() == "82ad56cb"  # aggregate3
        (calls,) = abi_decode(["(address,bool,bytes)[]"], calldata[4:])
        assert len(calls) == 8  # 4 CL + 2 V2 + 2 router
        results: list[tuple[bool, bytes]] = []
        for i in range(len(calls)):
            if i == 0:
                results.append(
                    (True, _encode_quoter_result(weth_out, gas_estimate=200_000))
                )
            else:
                results.append((False, b""))
        result_hex = "0x" + encode(["(bool,bytes)[]"], [results]).hex()
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": call_req["id"], "result": result_hex},
                {"jsonrpc": "2.0", "id": gas_req["id"], "result": "0x4a817c800"},
            ],
        )

    transport = httpx.MockTransport(handler)
    adapter = AerodromeBaseAdapter()
    await adapter.startup()
    await adapter.http.aclose()
    adapter._client = httpx.AsyncClient(transport=transport, timeout=5.0)
    adapter._rpc = RpcClient(
        adapter.http,
        "http://rpc.test/base",
        rpc_env="BASE_RPC_URL",
        budget=_rpc_budget(rps=100, max_attempts=1, gas_price_cache_ttl_sec=60.0),
    )

    async def fake_mid(http: Any, symbol: str) -> Decimal:
        return Decimal("3000")

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common.fetch_binance_mid",
        fake_mid,
    )

    try:
        quote = await adapter.get_quote("ETH", "buy", Decimal("1000"), mid=_MID_ETH)
        assert quote.status == "ok"
        assert quote.fee_breakdown.gas_unknown is False
        assert request_count == 1
    finally:
        await adapter.aclose()
        clear_rpc_endpoint_state()


@pytest.mark.asyncio
async def test_rpc_client_retries_429_then_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Injected HTTP 429 is retried; exhausted budget → rate_limited JsonRpcError."""
    clear_rpc_endpoint_state()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(
        "spread_compare.adapters._amm_common._async_sleep",
        fake_sleep,
    )

    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "0.1", "x-ratelimit-remaining": "0"},
            json={"error": "too many requests"},
        )

    transport = httpx.MockTransport(handler)
    budget = _rpc_budget(max_attempts=3, backoff_start_sec=0.5, gas_price_cache_ttl_sec=0)
    async with httpx.AsyncClient(transport=transport) as client:
        rpc = RpcClient(
            client,
            "https://example.invalid/v2/SECRET_KEY_SHOULD_NOT_LOG",
            rpc_env="BASE_RPC_URL",
            budget=budget,
        )
        with pytest.raises(JsonRpcError) as ei:
            await rpc.call("eth_blockNumber", [])
        err = ei.value
        assert err.rate_limited is True
        assert err.transport is True
        assert "SECRET_KEY" not in str(err)
        assert attempts == 3
        assert len(sleeps) == 2  # sleep between attempts, not after last
        assert all(s == 0.1 for s in sleeps)  # Retry-After honoured
    clear_rpc_endpoint_state()


@pytest.mark.asyncio
async def test_eth_gas_price_cached_per_endpoint() -> None:
    """eth_gasPrice is fetched at most once within the cache TTL (WHI-842)."""
    clear_rpc_endpoint_state()
    gas_posts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal gas_posts
        import json

        payload = json.loads(request.read())
        assert payload["method"] == "eth_gasPrice"
        gas_posts += 1
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": payload["id"], "result": "0x3b9aca00"},
        )

    budget = _rpc_budget(max_attempts=1, gas_price_cache_ttl_sec=30.0)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        rpc = RpcClient(
            client,
            "http://rpc.test/shared",
            rpc_env="ETH_RPC_URL",
            budget=budget,
        )
        a = await rpc.eth_gas_price()
        b = await rpc.eth_gas_price()
        # Second client on same URL shares the endpoint cache.
        rpc2 = RpcClient(
            client,
            "http://rpc.test/shared",
            rpc_env="ETH_RPC_URL",
            budget=budget,
        )
        c = await rpc2.eth_gas_price()
        assert a == b == c == 1_000_000_000
        assert gas_posts == 1
    clear_rpc_endpoint_state()


def test_multicall3_encode_decode_roundtrip() -> None:
    calls = [
        ("0x0000000000000000000000000000000000000001", b"\x11\x22"),
        ("0x0000000000000000000000000000000000000002", b"\x33"),
    ]
    encoded = encode_multicall3_aggregate3(calls)
    assert encoded[:4].hex() == "82ad56cb"
    # Simulate aggregate3 return for two successes.
    ret = encode(
        ["(bool,bytes)[]"],
        [[(True, b"\xaa"), (False, b"")]],
    )
    decoded = decode_multicall3_aggregate3(ret)
    assert decoded == [(True, b"\xaa"), (False, b"")]


def test_rpc_endpoint_label_strips_secrets() -> None:
    label = rpc_endpoint_label("https://base-mainnet.g.alchemy.com/v2/super-secret-key")
    assert label == "base-mainnet.g.alchemy.com"
    assert "secret" not in label


def test_multicall3_address_has_verification_comment() -> None:
    """Acceptance: Multicall3 address carries verification source + date comment."""
    common = Path(__file__).resolve().parents[1] / "spread_compare" / "adapters" / "_amm_common.py"
    text = common.read_text(encoding="utf-8")
    assert "0xcA11bde05977b3631167028862bE2a173976CA11" in text
    assert "Verified 2026-08-04" in text
    assert "multicall3.com" in text
