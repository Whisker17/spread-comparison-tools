"""Aerodrome on Base via MixedQuoter + Router getAmountsOut fallback (WHI-804).

MixedQuoter has no ExactOut support — buy side uses ExactIn on the quote leg
with ``qty_method=quote_exact_in_approx`` (WHI-799 §4.4).
"""

from __future__ import annotations

from decimal import Decimal

from spread_compare.adapters._amm_common import (
    AERO_TICK_SPACINGS,
    AmmDexAdapter,
    JsonRpcError,
    QuoterResult,
    TokenInfo,
    decode_aero_v2_amount,
    decode_get_amounts_out,
    decode_quoter_v2_result,
    encode_aero_exact_in_v2,
    encode_aero_exact_in_v3,
    encode_get_amounts_out,
    to_raw,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

# MixedQuoter (Base) — covers volatile / stable / CL.
# Doc-sourced 2026-08-03 from https://aerodrome.finance/security
# (WHI-800 §5.2); ABI matches IMixedRouteQuoterV1 in aerodrome-finance/slipstream.
_MIXED_QUOTER = "0x0A5aA5D3a4d28014f967Bf0f29EAA3FF9807D5c6"

# Router (Base) — vAMM/sAMM getAmountsOut fallback.
# Doc-sourced 2026-08-03 from https://aerodrome.finance/security (WHI-800 §5.2).
_ROUTER = "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"

# PoolFactory (Base) — Route factory field for V2-style pools.
# Doc-sourced 2026-08-03 from WHI-800 §5.2 (security page / docs).
_POOL_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"

# Token addresses: WHI-798 §3.2 (Base / Aerodrome row).
# cbBTC: https://basescan.org/token/0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf
_CBBTC = TokenInfo("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8, "cbBTC")
# WETH (Base): https://basescan.org/token/0x4200000000000000000000000000000000000006
_WETH = TokenInfo("0x4200000000000000000000000000000000000006", 18, "WETH")
# USDC (Base native): https://basescan.org/token/0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
_USDC = TokenInfo("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, "USDC")

# Informational LP fee for V2 pools (not added to trading_component_bps).
_V2_VOLATILE_LP_BPS = Decimal("30")  # typical 0.30%
_V2_STABLE_LP_BPS = Decimal("5")  # typical 0.05%


@register_adapter
class AerodromeBaseAdapter(AmmDexAdapter):
    """Aerodrome (Base) MixedQuoter + Router fallback — ExactIn only."""

    venue: str = "aerodrome_base"
    rpc_env: str = "BASE_RPC_URL"
    native_binance_symbol: str = "ETHUSDT"

    def _base_token(self, asset: str) -> TokenInfo:
        if asset == "BTC":
            return _CBBTC
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

        if side == "sell":
            amount_in = to_raw(q_star, base.decimals)
            token_in, token_out = base.address, quote.address
        else:
            # Buy: ExactIn on quote leg ≈ notional (USDC ~ $1).
            # qty_method=quote_exact_in_approx set by AmmDexAdapter.
            amount_in = to_raw(notional_usd, quote.decimals)
            token_in, token_out = quote.address, base.address

        if amount_in <= 0:
            return None

        best = await self._probe_mixed_quoter(token_in, token_out, amount_in)
        if best is not None:
            return best
        return await self._probe_router(token_in, token_out, amount_in)

    async def _probe_mixed_quoter(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> QuoterResult | None:
        rpc = self._require_rpc()
        best: QuoterResult | None = None

        # CL pools via quoteExactInputSingleV3 (returns gasEstimate).
        for tick in AERO_TICK_SPACINGS:
            data = encode_aero_exact_in_v3(token_in, token_out, amount_in, tick)
            try:
                raw = await rpc.eth_call(_MIXED_QUOTER, data)
                amount_out, _, _, gas_est = decode_quoter_v2_result(raw)
            except (JsonRpcError, ValueError):
                continue
            if amount_out <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_in,
                amount_out=amount_out,
                gas_estimate=gas_est,
                fee_label=f"cl_tick_{tick}",
                lp_fee_tier_bps=None,
                exact_out=False,
            )
            if best is None or candidate.amount_out > best.amount_out:
                best = candidate

        # V2 volatile / stable via quoteExactInputSingleV2 (no gasEstimate).
        for stable, label, lp_bps in (
            (False, "v2_volatile", _V2_VOLATILE_LP_BPS),
            (True, "v2_stable", _V2_STABLE_LP_BPS),
        ):
            data = encode_aero_exact_in_v2(token_in, token_out, stable, amount_in)
            try:
                raw = await rpc.eth_call(_MIXED_QUOTER, data)
                amount_out = decode_aero_v2_amount(raw)
            except (JsonRpcError, ValueError):
                continue
            if amount_out <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_in,
                amount_out=amount_out,
                gas_estimate=None,  # V2 path has no gasEstimate → gas_unknown unless
                # we can still estimate via a default; leave None → gas_unknown.
                fee_label=label,
                lp_fee_tier_bps=lp_bps,
                exact_out=False,
            )
            if best is None or candidate.amount_out > best.amount_out:
                best = candidate

        return best

    async def _probe_router(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> QuoterResult | None:
        """Fallback: Router.getAmountsOut with V2 Route(from,to,stable,factory)."""
        rpc = self._require_rpc()
        best: QuoterResult | None = None
        for stable, label, lp_bps in (
            (False, "router_volatile", _V2_VOLATILE_LP_BPS),
            (True, "router_stable", _V2_STABLE_LP_BPS),
        ):
            data = encode_get_amounts_out(
                amount_in,
                [(token_in, token_out, stable, _POOL_FACTORY)],
            )
            try:
                raw = await rpc.eth_call(_ROUTER, data)
                amounts = decode_get_amounts_out(raw)
            except (JsonRpcError, ValueError):
                continue
            if len(amounts) < 2 or amounts[-1] <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_in,
                amount_out=amounts[-1],
                gas_estimate=None,
                fee_label=label,
                lp_fee_tier_bps=lp_bps,
                exact_out=False,
            )
            if best is None or candidate.amount_out > best.amount_out:
                best = candidate
        return best
