"""Shared prop-AMM adapter helpers (WHI-806).

Underscore-prefixed so adapter auto-discovery skips this module.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from spread_compare.adapters._amm_common import TokenInfo, from_raw, to_raw
from spread_compare.adapters.base import AdapterError, default_instrument_type
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
    "load_dotenv_once",
    "optional_env",
    "build_non_ok_quote",
    "build_ok_prop_quote",
    "prop_fee_schedule",
    "require_mid_match",
]

_DOTENV_LOADED = False


def load_dotenv_once() -> None:
    """Load repo-root ``.env`` into ``os.environ`` (idempotent)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    from dotenv import load_dotenv

    load_dotenv()
    _DOTENV_LOADED = True


def optional_env(name: str) -> str | None:
    """Return a non-empty env var, or None if unset/blank."""
    load_dotenv_once()
    value = os.environ.get(name, "").strip()
    return value or None


def require_mid_match(mid: ReferenceMid, asset: str) -> None:
    """Raise when mid asset does not match the requested asset."""
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
