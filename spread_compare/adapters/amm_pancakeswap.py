"""PancakeSwap v3 on BSC via on-chain QuoterV2 (WHI-804).

Quote leg is USDT on BSC. Single-venue semantics only — no 0x/1inch.
Phase 1: fixed v3 fee-tier probe (skip Smart Router / multi-hop).
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.adapters._amm_common import (
    PANCAKE_FEE_TIERS,
    AmmDexAdapter,
    QuoterResult,
    TokenInfo,
    probe_quoter_v2,
    to_raw,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

# QuoterV2 (BSC).
# Verified 2026-08-03 against PancakeSwap developer docs:
# https://developer.pancakeswap.finance/contracts/v3/addresses
# Matches WHI-800 §5.3.
_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

# Token addresses: WHI-798 §3.2 (BSC / PancakeSwap row), inventory date 2026-08-03.
# BTCB: https://bscscan.com/token/0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c
_BTCB = TokenInfo("0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c", 18, "BTCB")
# Bridged ETH: https://bscscan.com/token/0x2170Ed0880ac9A755fd29B2688956BD959F933F8
_ETH = TokenInfo("0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18, "ETH")
# USDT (BSC, 18 decimals): https://bscscan.com/token/0x55d398326f99059fF775485246999027B3197955
_USDT = TokenInfo("0x55d398326f99059fF775485246999027B3197955", 18, "USDT")


@register_adapter
class PancakeSwapBscAdapter(AmmDexAdapter):
    """PancakeSwap (BSC) QuoterV2 adapter — fee-tier probe, ExactIn/ExactOut."""

    venue: str = "pancakeswap_bsc"
    rpc_env: str = "BSC_RPC_URL"
    native_binance_symbol: str = "BNBUSDT"
    lp_fee_tiers: tuple[int, ...] = PANCAKE_FEE_TIERS

    def _base_token(self, asset: str) -> TokenInfo:
        if asset == "BTC":
            return _BTCB
        if asset == "ETH":
            return _ETH
        raise KeyError(asset)

    def _quote_token(self) -> TokenInfo:
        return _USDT

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
