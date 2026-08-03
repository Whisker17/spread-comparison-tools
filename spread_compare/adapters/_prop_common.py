"""Shared prop-AMM adapter helpers (WHI-806).

Underscore-prefixed so adapter auto-discovery skips this module.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from spread_compare.adapters._amm_common import (
    TokenInfo,
    build_non_ok_quote,
    build_ok_quote,
    from_raw,
    load_dotenv_once,
    to_raw,
)
from spread_compare.adapters.base import (
    AdapterConfigError,
    AdapterError,
)
from spread_compare.models import (
    InstrumentType,
    QtyMethod,
    Quote,
    QuoteStatus,
    ReferenceMid,
    Side,
)

# Re-export shared builders/helpers so prop modules have one import site.
__all__ = [
    "TokenInfo",
    "from_raw",
    "to_raw",
    "optional_env",
    "build_non_ok_quote",
    "build_ok_quote",
    "require_mid_match",
    "PropFill",
    "PropNoQuoteError",
    "exact_in_prop_quote",
]

def optional_env(name: str) -> str | None:
    """Return a non-empty env var, or None if unset/blank."""
    load_dotenv_once()
    value = os.environ.get(name, "").strip()
    return value or None

def require_mid_match(mid: ReferenceMid, asset: str) -> None:
    """Raise when mid asset does not match the requested asset or mid is non-positive."""
    if mid.asset.upper() != asset.upper():
        raise AdapterError(f"mid.asset={mid.asset!r} does not match asset={asset!r}")
    if mid.mid <= 0:
        raise AdapterError(f"mid must be positive, got {mid.mid}")

@dataclass(frozen=True, slots=True)
class PropFill:
    """Raw ExactIn fill amounts from a prop quote provider."""

    amount_in: int
    amount_out: int
    gas_usd: Decimal | None = None

class PropNoQuoteError(Exception):
    """Business empty state from a prop quote provider (no route / no liquidity)."""

    def __init__(self, message: str, *, code: str = "no_quote") -> None:
        super().__init__(message)
        self.code = code

PropFetch = Callable[[str, str, int], Awaitable[PropFill]]

async def exact_in_prop_quote(
    *,
    venue: str,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    base: TokenInfo,
    quote_tok: TokenInfo,
    fee_tier: str,
    fetch: PropFetch,
    provider_label: str,
    gas_unknown_when_missing: bool,
) -> Quote:
    """Shared ExactIn buy/sell quote shell for Jupiter and KyberSwap prop adapters.

    Sell: ExactIn base → quote. Buy: ExactIn quote → base
    (``qty_method=quote_exact_in_approx``; ExactOut is unverified on prop AMMs).

    ``fetch`` raises :class:`PropNoQuoteError` for business-empty states and
    :class:`AdapterConfigError` for config misuse (must not become empty quotes).
    """
    venue_symbol = f"{base.symbol}/{quote_tok.symbol}"

    if side == "sell":
        qty_base = notional_usd / mid.mid
        amount_in = to_raw(qty_base, base.decimals)
        token_in, token_out = base.address, quote_tok.address
        qty_method: QtyMethod = "base_from_mid"
    else:
        amount_in = to_raw(notional_usd, quote_tok.decimals)
        token_in, token_out = quote_tok.address, base.address
        qty_method = "quote_exact_in_approx"

    if amount_in <= 0:
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status="no_quote",
            error_code="no_quote",
            error_message="computed input amount is zero",
            venue_symbol=venue_symbol,
            qty_method=qty_method,
        )

    try:
        fill = await fetch(token_in, token_out, amount_in)
    except PropNoQuoteError as exc:
        # WHI-799 §4.4: 4000 (token not in source set) → unsupported_asset.
        status: QuoteStatus = (
            "unsupported_asset" if exc.code == "4000" else "no_quote"
        )
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status=status,
            error_code=exc.code,
            error_message=str(exc),
            venue_symbol=venue_symbol,
            qty_method=qty_method,
        )
    except AdapterConfigError:
        raise
    except AdapterError as exc:
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status="error",
            error_code="adapter_error",
            error_message=str(exc),
            venue_symbol=venue_symbol,
            qty_method=qty_method,
        )

    if fill.amount_in <= 0 or fill.amount_out <= 0:
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status="no_quote",
            error_code="no_quote",
            error_message=f"{provider_label} returned zero amounts",
            venue_symbol=venue_symbol,
            qty_method=qty_method,
        )

    if side == "sell":
        base_amt = from_raw(fill.amount_in, base.decimals)
        quote_amt = from_raw(fill.amount_out, quote_tok.decimals)
    else:
        quote_amt = from_raw(fill.amount_in, quote_tok.decimals)
        base_amt = from_raw(fill.amount_out, base.decimals)

    if base_amt <= 0 or quote_amt <= 0:
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status="no_quote",
            error_code="no_quote",
            error_message="zero base/quote after scaling",
            venue_symbol=venue_symbol,
            qty_method=qty_method,
        )

    gas_usd = fill.gas_usd
    if gas_unknown_when_missing:
        gas_unknown = gas_usd is None
    else:
        # Jupiter path: Solana fees fixed at 0 (WHI-799 §8) — never unknown.
        # gas_usd may stay None → total_cost_bps treats it as 0 gas bps.
        gas_unknown = False

    return build_ok_quote(
        venue=venue,
        mid=mid,
        asset=asset,
        side=side,
        notional_usd=notional_usd,
        instrument_type=instrument_type,
        effective_price=quote_amt / base_amt,
        qty_base=base_amt,
        qty_method=qty_method,
        fee_label=fee_tier,
        lp_fee_tier_bps=None,
        gas_usd=gas_usd,
        gas_unknown=gas_unknown,
        venue_symbol=venue_symbol,
    )

# Solana mint table (WHI-797 §6.2) — initial asset surface only.
SOL_MINTS: Final[dict[str, TokenInfo]] = {
    "SOL": TokenInfo(
        "So11111111111111111111111111111111111111112", 9, "wSOL"
    ),
    "USDC": TokenInfo(
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 6, "USDC"
    ),
    "BTC": TokenInfo(
        "cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij", 8, "cbBTC"
    ),
    "ETH": TokenInfo(
        "7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs", 8, "WETH"
    ),
}

# Base / BSC token tables (WHI-797 §7.4). Addresses match amm_aerodrome / amm_pancakeswap
# for shared blue chips; prop-only assets (AERO, stocks, …) live only here.
BASE_TOKENS: Final[dict[str, TokenInfo]] = {
    "ETH": TokenInfo(
        "0x4200000000000000000000000000000000000006", 18, "WETH"
    ),
    "USDC": TokenInfo(
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", 6, "USDC"
    ),
    "BTC": TokenInfo(
        "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8, "cbBTC"
    ),
    "AERO": TokenInfo(
        "0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18, "AERO"
    ),
    "VIRTUAL": TokenInfo(
        "0x0b3e328455c4059EEB9e3f84b5543F74E24e7E1b", 18, "VIRTUAL"
    ),
    "EURC": TokenInfo(
        "0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42", 6, "EURC"
    ),
}

BSC_TOKENS: Final[dict[str, TokenInfo]] = {
    "BTC": TokenInfo(
        "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c", 18, "BTCB"
    ),
    "USDT": TokenInfo(
        "0x55d398326f99059fF775485246999027B3197955", 18, "USDT"
    ),
    "QQQB": TokenInfo(
        "0x205812cdbed920aff76c6580abd681a46d11efc7", 18, "QQQB"
    ),
    "SPCXB": TokenInfo(
        "0xbe9d156892e55e7154bcd3cb0fea677f9d3103e1", 18, "SPCXB"
    ),
    "NVDAB": TokenInfo(
        "0x02fca66c1d1afb4e2a7884261eb00f63598a7436", 18, "NVDAB"
    ),
    "NVDAON": TokenInfo(
        "0xa9ee28c80f960b889dfbd1902055218cba016f75", 18, "NVDAon"
    ),
}
