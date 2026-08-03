"""Uniswap v3 on Ethereum via on-chain QuoterV2 (WHI-804).

Single-venue semantics only — never labels 0x/1inch aggregator routes as this venue.
Phase 1 probes single-hop ``quoteExactInputSingle`` / ``quoteExactOutputSingle`` across
fee tiers (WHI-800 §5.1); multi-hop ``quoteExactInput`` path encoding is out of scope
alongside Smart Router / multi-hop optimization.
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.adapters._amm_common import (
    UNISWAP_FEE_TIERS,
    AmmDexAdapter,
    QuoterResult,
    TokenInfo,
    probe_quoter_v2,
    to_raw,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

# QuoterV2 (Ethereum mainnet).
# Verified 2026-08-03 against Uniswap docs deployments (Ethereum):
# https://docs.uniswap.org/contracts/v3/reference/deployments/ethereum-deployments
# Address matches WHI-800 §5.1 and the official deployments page.
_QUOTER_V2 = "0x61fFE014bA17989E743c5F6cB21bF9697530B21e"

# Token addresses: WHI-798 §3.2 (Ethereum / Uniswap row), inventory date 2026-08-03.
# WBTC: https://etherscan.io/token/0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599
_WBTC = TokenInfo("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8, "WBTC")
# WETH: https://etherscan.io/token/0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2
_WETH = TokenInfo("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18, "WETH")
# USDC: https://etherscan.io/token/0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
_USDC = TokenInfo("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6, "USDC")


@register_adapter
class UniswapEthAdapter(AmmDexAdapter):
    """Uniswap (Ethereum) QuoterV2 adapter — fee-tier probe, ExactIn/ExactOut."""

    venue: str = "uniswap_eth"
    rpc_env: str = "ETH_RPC_URL"
    native_binance_symbol: str = "ETHUSDT"
    lp_fee_tiers: tuple[int, ...] = UNISWAP_FEE_TIERS

    def _base_token(self, asset: str) -> TokenInfo:
        if asset == "BTC":
            return _WBTC
        if asset == "ETH":
            return _WETH
        raise KeyError(asset)

    def _quote_token(self) -> TokenInfo:
        return _USDC

    async def _quote_best(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        mid: ReferenceMid,
    ) -> QuoterResult | None:
        base = self._base_token(asset)
        quote = self._quote_token()
        q_star = notional_usd / mid.mid
        amount_base = to_raw(q_star, base.decimals)
        return await probe_quoter_v2(
            self._require_rpc(),
            _QUOTER_V2,
            token_base=base.address,
            token_quote=quote.address,
            amount_base_raw=amount_base,
            fee_tiers=self.lp_fee_tiers,
            side=side,
        )
