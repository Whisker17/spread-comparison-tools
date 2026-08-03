"""PancakeSwap v3 on BSC via on-chain QuoterV2 (WHI-804).

Quote leg is USDT on BSC. Single-venue semantics only — no 0x/1inch.
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.adapters._amm_common import (
    PANCAKE_FEE_TIERS,
    AmmDexAdapter,
    JsonRpcError,
    QuoterResult,
    TokenInfo,
    decode_quoter_v2_result,
    encode_quote_exact_input_single,
    encode_quote_exact_output_single,
    fee_to_lp_bps,
    to_raw,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

# QuoterV2 (BSC).
# Verified 2026-08-03 against PancakeSwap developer docs:
# https://developer.pancakeswap.finance/contracts/v3/addresses
# Matches WHI-800 §5.3.
_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

# Token addresses: WHI-798 §3.2 (BSC / PancakeSwap row).
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
        rpc = self._require_rpc()
        base = self._base_token(asset)
        quote = self._quote_token()
        q_star = notional_usd / mid.mid

        best: QuoterResult | None = None

        if side == "sell":
            amount_in = to_raw(q_star, base.decimals)
            if amount_in <= 0:
                return None
            for fee in PANCAKE_FEE_TIERS:
                data = encode_quote_exact_input_single(
                    base.address, quote.address, amount_in, fee
                )
                try:
                    raw = await rpc.eth_call(_QUOTER_V2, data)
                    amount_out, _, _, gas_est = decode_quoter_v2_result(raw)
                except (JsonRpcError, ValueError):
                    continue
                if amount_out <= 0:
                    continue
                candidate = QuoterResult(
                    amount_in=amount_in,
                    amount_out=amount_out,
                    gas_estimate=gas_est,
                    fee_label=f"pool_{fee}",
                    lp_fee_tier_bps=fee_to_lp_bps(fee),
                    exact_out=False,
                )
                if best is None or candidate.amount_out > best.amount_out:
                    best = candidate
            return best

        # Buy: ExactOut base = q_star.
        amount_out = to_raw(q_star, base.decimals)
        if amount_out <= 0:
            return None
        for fee in PANCAKE_FEE_TIERS:
            data = encode_quote_exact_output_single(
                quote.address, base.address, amount_out, fee
            )
            try:
                raw = await rpc.eth_call(_QUOTER_V2, data)
                amount_in, _, _, gas_est = decode_quoter_v2_result(raw)
            except (JsonRpcError, ValueError):
                continue
            if amount_in <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_in,
                amount_out=amount_out,
                gas_estimate=gas_est,
                fee_label=f"pool_{fee}",
                lp_fee_tier_bps=fee_to_lp_bps(fee),
                exact_out=True,
            )
            if best is None or candidate.amount_in < best.amount_in:
                best = candidate
        return best
