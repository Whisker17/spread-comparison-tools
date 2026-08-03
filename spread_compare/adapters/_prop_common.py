"""Shared prop-AMM adapter helpers (WHI-806).

Underscore-prefixed so adapter auto-discovery skips this module.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from spread_compare.adapters._amm_common import (
    TokenInfo,
    from_raw,
    load_dotenv_once,
    to_raw,
)
from spread_compare.adapters.base import (
    AdapterConfigError,
    AdapterError,
    default_instrument_type,
)
from spread_compare.costs import spread_bps as calc_spread_bps
from spread_compare.costs import total_cost_bps
from spread_compare.models import (
    FeeBreakdown,
    FeeSchedule,
    InstrumentType,
    QtyMethod,
    Quote,
    QuoteStatus,
    ReferenceMid,
    Side,
    VenueClass,
)

# Re-export token helpers for prop modules.
__all__ = [
    "TokenInfo",
    "from_raw",
    "to_raw",
    "optional_env",
    "build_non_ok_quote",
    "build_ok_prop_quote",
    "prop_fee_schedule",
    "require_mid_match",
    "PropFill",
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


def prop_fee_schedule(
    venue: str,
    asset: str | None = None,
    *,
    instrument_type: InstrumentType | None = None,
    venue_class: VenueClass = "prop_amm",
) -> FeeSchedule:
    """Static fee schedule for prop AMMs (fees embedded in quote price)."""
    itype: InstrumentType = instrument_type or default_instrument_type(venue_class)
    return FeeSchedule(
        venue=venue,
        asset=asset,
        instrument_type=itype,
        maker_bps=None,
        taker_bps=None,
        default_tier="embedded",
        funding_model="none",
        fee_embedded_in_quote=True,
        source_urls=[],
        updated_at=datetime.now(tz=UTC),
    )


def build_non_ok_quote(
    *,
    venue: str,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    status: QuoteStatus,
    error_code: str,
    error_message: str,
    venue_symbol: str | None = None,
    qty_method: QtyMethod | None = None,
) -> Quote:
    """Construct a non-ok Quote with WHI-799 §6.2 null invariants."""
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        venue_symbol=venue_symbol,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        effective_price=None,
        spread_bps=None,
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            fee_tier=None,
            trading_fee_bps=None,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=None,
        ),
        total_cost_bps=None,
        timestamp=datetime.now(tz=UTC),
        status=status,
        qty_base=None,
        qty_method=qty_method,
        error_code=error_code,
        error_message=error_message,
    )


def build_ok_prop_quote(
    *,
    venue: str,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    effective_price: Decimal,
    qty_base: Decimal,
    qty_method: QtyMethod,
    fee_tier: str,
    gas_usd: Decimal | None,
    gas_unknown: bool,
    venue_symbol: str | None,
) -> Quote:
    """Build an ok prop-AMM Quote (fees embedded; costs via shared formulas)."""
    sp = calc_spread_bps(side, effective_price, mid.mid)
    cost = total_cost_bps(
        sp,
        embedded_in_price=True,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=gas_unknown,
        gas_usd=gas_usd,
        notional_usd=notional_usd,
    )
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        venue_symbol=venue_symbol,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        effective_price=effective_price,
        spread_bps=sp,
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            fee_tier=fee_tier,
            trading_fee_bps=None,
            platform_fee_bps=Decimal("0"),
            gas_usd=gas_usd,
            gas_bps=cost.gas_bps,
            gas_unknown=gas_unknown,
            explicit_fee_bps=cost.explicit_fee_bps,
        ),
        total_cost_bps=cost.total_cost_bps,
        timestamp=datetime.now(tz=UTC),
        status="ok",
        qty_base=qty_base,
        qty_method=qty_method,
    )


@dataclass(frozen=True, slots=True)
class PropFill:
    """Raw ExactIn fill amounts from a prop quote provider."""

    amount_in: int
    amount_out: int
    gas_usd: Decimal | None = None


# Fetch callback: (token_in, token_out, amount_in) → PropFill.
# Raise AdapterConfigError for config misuse; raise a mapped business empty via
# returning through ``no_quote_exc`` type handled by the caller adapter.
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
    gas_unknown: bool,
    no_quote_exc: type[BaseException],
) -> Quote:
    """Shared ExactIn buy/sell quote shell for Jupiter and KyberSwap prop adapters.

    Sell: ExactIn base → quote. Buy: ExactIn quote → base
    (``qty_method=quote_exact_in_approx``; ExactOut is unverified on prop AMMs).
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
    except no_quote_exc as exc:
        code = getattr(exc, "code", "no_quote")
        return build_non_ok_quote(
            venue=venue,
            mid=mid,
            asset=asset,
            side=side,
            notional_usd=notional_usd,
            instrument_type=instrument_type,
            status="no_quote",
            error_code=str(code),
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

    return build_ok_prop_quote(
        venue=venue,
        mid=mid,
        asset=asset,
        side=side,
        notional_usd=notional_usd,
        instrument_type=instrument_type,
        effective_price=quote_amt / base_amt,
        qty_base=base_amt,
        qty_method=qty_method,
        fee_tier=fee_tier,
        gas_usd=fill.gas_usd,
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

# Base tokens (WHI-797 §7.4 / samples matrix footer).
# Addresses shared with Aerodrome adapter for the same chain assets.
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

# BSC tokens (WHI-797 §7.4 / WHI-798 matrix).
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
