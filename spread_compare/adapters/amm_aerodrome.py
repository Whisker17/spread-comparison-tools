"""Aerodrome on Base via MixedQuoter + Router getAmountsOut fallback (WHI-804).

MixedQuoter has no ExactOut support — buy side uses ExactIn on the quote leg
with ``qty_method=quote_exact_in_approx`` (WHI-799 §4.4).

CL candidates (with gasEstimate) are preferred over V2/router paths when they
produce a quote, so ``total_cost_bps`` can be filled whenever CL liquidity exists.

WHI-842: all probe paths (CL tick spacings + V2 + router) are issued as one
Multicall3.aggregate3 eth_call so a page load does not burst the Base RPC.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from spread_compare.adapters._amm_common import (
    AERO_TICK_SPACINGS,
    AmmDexAdapter,
    JsonRpcError,
    ProbeOutcome,
    QuoterResult,
    TokenInfo,
    decode_aero_v2_amount,
    decode_get_amounts_out,
    decode_quoter_v2_result,
    encode_aero_exact_in_v2,
    encode_aero_exact_in_v3,
    encode_get_amounts_out,
    reduce_probe_outcomes,
    to_raw,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

logger = logging.getLogger(__name__)

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

# Token addresses: WHI-798 §3.2 (Base / Aerodrome row), inventory date 2026-08-03.
# cbBTC: https://basescan.org/token/0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf
_CBBTC = TokenInfo("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8, "cbBTC")
# WETH (Base): https://basescan.org/token/0x4200000000000000000000000000000000000006
_WETH = TokenInfo("0x4200000000000000000000000000000000000006", 18, "WETH")
# USDC (Base native): https://basescan.org/token/0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
_USDC = TokenInfo("0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, "USDC")


def _outcome_cl(
    amount_in: int,
    tick: int,
    *,
    success: bool,
    raw: bytes | None,
) -> ProbeOutcome:
    if not success:
        return "revert", None
    if raw is None or raw == b"":
        return "ok", None
    try:
        amount_out, _, _, gas_est = decode_quoter_v2_result(raw)
    except ValueError:
        return "ok", None
    if amount_out <= 0:
        return "ok", None
    return "ok", QuoterResult(
        amount_in=amount_in,
        amount_out=amount_out,
        gas_estimate=gas_est,
        fee_label=f"cl_tick_{tick}",
        # Actual CL fee is per-pool; leave null rather than invent (WHI-812).
        lp_fee_tier_bps=None,
        exact_out=False,
    )


def _outcome_v2(
    amount_in: int,
    label: str,
    *,
    success: bool,
    raw: bytes | None,
) -> ProbeOutcome:
    if not success:
        return "revert", None
    if raw is None or raw == b"":
        return "ok", None
    try:
        amount_out = decode_aero_v2_amount(raw)
    except ValueError:
        return "ok", None
    if amount_out <= 0:
        return "ok", None
    return "ok", QuoterResult(
        amount_in=amount_in,
        amount_out=amount_out,
        gas_estimate=None,
        fee_label=label,
        lp_fee_tier_bps=None,
        exact_out=False,
    )


def _outcome_router(
    amount_in: int,
    label: str,
    *,
    success: bool,
    raw: bytes | None,
) -> ProbeOutcome:
    if not success:
        return "revert", None
    if raw is None or raw == b"":
        return "ok", None
    try:
        amounts = decode_get_amounts_out(raw)
    except ValueError:
        return "ok", None
    if len(amounts) < 2 or amounts[-1] <= 0:
        return "ok", None
    return "ok", QuoterResult(
        amount_in=amount_in,
        amount_out=amounts[-1],
        gas_estimate=None,
        fee_label=label,
        lp_fee_tier_bps=None,
        exact_out=False,
    )


@register_adapter
class AerodromeBaseAdapter(AmmDexAdapter):
    """Aerodrome (Base) MixedQuoter + Router fallback — ExactIn only."""

    venue: str = "aerodrome_base"
    rpc_env: str = "BASE_RPC_URL"
    native_binance_symbol: str = "ETHUSDT"
    # No Uniswap-style fee tiers; CL tick spacing ≠ fixed fee table (WHI-800 §5.2).
    lp_fee_tiers: tuple[int, ...] = ()

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
            amount_in = to_raw(notional_usd, quote.decimals)
            token_in, token_out = quote.address, base.address

        if amount_in <= 0:
            return None

        # Probe CL + V2 + router; best by amount_out, gasEstimate as tiebreak only.
        return await self._probe_all(token_in, token_out, amount_in)

    async def _probe_all(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> QuoterResult | None:
        """Probe CL + V2 + router paths in one Multicall3 batch (WHI-842)."""
        rpc = self._require_rpc()

        calls: list[tuple[str, bytes]] = []
        # Order: CL ticks, V2 volatile/stable, router volatile/stable.
        for tick in AERO_TICK_SPACINGS:
            calls.append(
                (
                    _MIXED_QUOTER,
                    encode_aero_exact_in_v3(token_in, token_out, amount_in, tick),
                )
            )
        calls.append(
            (
                _MIXED_QUOTER,
                encode_aero_exact_in_v2(token_in, token_out, False, amount_in),
            )
        )
        calls.append(
            (
                _MIXED_QUOTER,
                encode_aero_exact_in_v2(token_in, token_out, True, amount_in),
            )
        )
        calls.append(
            (
                _ROUTER,
                encode_get_amounts_out(
                    amount_in,
                    [(token_in, token_out, False, _POOL_FACTORY)],
                ),
            )
        )
        calls.append(
            (
                _ROUTER,
                encode_get_amounts_out(
                    amount_in,
                    [(token_in, token_out, True, _POOL_FACTORY)],
                ),
            )
        )

        try:
            results = await rpc.eth_call_many(calls)
        except JsonRpcError as exc:
            if exc.rate_limited:
                raise
            n = len(calls)
            return reduce_probe_outcomes(
                [("transport", None)] * n,
                prefer_min_in=False,
                error_label="Aerodrome quote paths",
            )

        if len(results) != len(calls):
            logger.warning(
                "Aerodrome multicall length mismatch: got %s expected %s",
                len(results),
                len(calls),
            )
            return reduce_probe_outcomes(
                [("transport", None)] * len(calls),
                prefer_min_in=False,
                error_label="Aerodrome quote paths",
            )

        outcomes: list[ProbeOutcome] = []
        idx = 0
        for tick in AERO_TICK_SPACINGS:
            success, raw = results[idx]
            idx += 1
            outcomes.append(
                _outcome_cl(amount_in, tick, success=success, raw=raw)
            )
        for label in ("v2_volatile", "v2_stable"):
            success, raw = results[idx]
            idx += 1
            outcomes.append(
                _outcome_v2(amount_in, label, success=success, raw=raw)
            )
        for label in ("router_volatile", "router_stable"):
            success, raw = results[idx]
            idx += 1
            outcomes.append(
                _outcome_router(amount_in, label, success=success, raw=raw)
            )

        return reduce_probe_outcomes(
            outcomes,
            prefer_min_in=False,
            error_label="Aerodrome quote paths",
        )
