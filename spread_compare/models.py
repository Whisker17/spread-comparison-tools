"""Shared pydantic models transcribed from docs/research/WHI-799-spread-fee-data-model.md §6.

Field names, types, and Quote invariants (§6.2) are the SSOT — do not re-derive.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

QuoteStatus = Literal[
    "ok",
    "no_quote",
    "insufficient_liquidity",
    "unsupported_asset",
    "error",
    "rate_limited",  # WHI-844 / WHI-799 §6.1: wait would exceed quote budget
    "excessive_impact",  # WHI-845 / WHI-799 §6.1: price impact over config threshold
]
# Statuses that carry executable price fields (shown, but only "ok" is §5.2 best-eligible).
PRICED_QUOTE_STATUSES: Final[frozenset[str]] = frozenset({"ok", "excessive_impact"})
# /simulate row status (WHI-814):
# - not_supported: venue pre-filter (asset absent from supported_assets)
# - unsupported_asset: adapter returned that Quote status after a live call
SimulateRowStatus = QuoteStatus | Literal["not_supported"]
InstrumentType = Literal["spot", "perp", "amm_pool", "prop_amm"]
Side = Literal["buy", "sell"]
VenueClass = Literal["cex", "perp_dex", "amm_dex", "prop_amm"]
QtyMethod = Literal["base_from_mid", "quote_exact_in_approx"]
FundingModel = Literal["none", "perp_8h", "perp_continuous"]
# WHI-799 §3.2 / §3.3 closed vocabulary for ReferenceMid.mid_source / Quote.mid_source.
MidSource = Literal[
    "binance_usdm_index",
    "binance_spot_tob",
    "bybit_spot_tob",
    "pyth",
    "cex_tradfi_index",
    "proxy_perp_mark_median",
    "equity_ref_same_as_perp",
]

# WHI-799 §4.1 — fixed notional tiers (USD). Compare with Decimal equality.
NOTIONAL_TIERS_USD: Final[tuple[Decimal, ...]] = (
    Decimal("100"),
    Decimal("1000"),
    Decimal("10000"),
    Decimal("100000"),
    Decimal("1000000"),
)


class FeeTier(BaseModel):
    """One fee tier inside a FeeSchedule (WHI-799 §5.5)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    maker_bps: Decimal
    taker_bps: Decimal
    volume_requirement: str | None = None


class FeeSchedule(BaseModel):
    """Venue-level fee table shape (WHI-799 §5.5). Numbers filled by WHI-812."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    asset: str | None = None
    instrument_type: InstrumentType
    maker_bps: Decimal | None = None
    taker_bps: Decimal | None = None
    tiers: list[FeeTier] | None = None
    default_tier: str = "default_taker"
    lp_fee_tiers_bps: list[Decimal] | None = None
    gas_estimate_usd: Decimal | None = None
    funding_model: FundingModel = "none"
    fee_embedded_in_quote: bool = False
    source_urls: list[str] = Field(default_factory=list)
    updated_at: AwareDatetime


class FeeBreakdown(BaseModel):
    """Per-quote fee components (WHI-799 §5.4). bps fields are authoritative."""

    model_config = ConfigDict(extra="forbid")

    embedded_in_price: bool
    fee_tier: str | None = None
    trading_fee_bps: Decimal | None = None
    trading_fee_usd: Decimal | None = None
    platform_fee_bps: Decimal = Decimal("0")
    lp_fee_tier_bps: Decimal | None = None
    gas_usd: Decimal | None = None
    gas_bps: Decimal | None = None
    gas_unknown: bool = False
    funding_rate_8h: Decimal | None = None
    explicit_fee_bps: Decimal | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _gas_unknown_nulls(self) -> FeeBreakdown:
        """WHI-799 §5.2: gas_unknown ⇒ gas_bps and explicit_fee_bps are null."""
        if self.gas_unknown:
            if self.gas_bps is not None:
                raise ValueError(
                    "gas_unknown=true requires gas_bps is null (WHI-799 §5.2)"
                )
            if self.explicit_fee_bps is not None:
                raise ValueError(
                    "gas_unknown=true requires explicit_fee_bps is null (WHI-799 §5.2)"
                )
        return self


class ReferenceMid(BaseModel):
    """Snapshot-scoped reference mid shared by all venues (WHI-799 §3.5)."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    asset: str
    mid: Decimal
    mid_source: MidSource
    timestamp: AwareDatetime
    sources_detail: list[str] | None = None


class Quote(BaseModel):
    """Single venue quote at a notional size (WHI-799 §6.2)."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    venue: str
    asset: str
    venue_symbol: str | None = None
    instrument_type: InstrumentType
    side: Side
    notional_usd: Decimal

    mid: Decimal
    mid_source: MidSource
    mid_timestamp: AwareDatetime
    mid_stale: bool = False
    effective_price: Decimal | None = None
    spread_bps: Decimal | None = None

    fee_breakdown: FeeBreakdown
    total_cost_bps: Decimal | None = None

    timestamp: AwareDatetime
    status: QuoteStatus
    qty_base: Decimal | None = None
    qty_method: QtyMethod | None = None
    venue_mark: Decimal | None = None
    basis_bps: Decimal | None = None
    raw_ref: str | None = None

    error_code: str | None = None
    error_message: str | None = None
    # Diagnostic mid/pool impact in bps when known (WHI-845). Null when upstream
    # does not report and no mid-relative derivation was applied.
    price_impact_bps: Decimal | None = None

    @model_validator(mode="after")
    def _enforce_status_invariants(self) -> Quote:
        """WHI-799 §6.2 invariants 1–2 (WHI-845: excessive_impact keeps prices)."""
        fb = self.fee_breakdown
        if self.status in PRICED_QUOTE_STATUSES:
            missing = [
                name
                for name, value in (
                    ("effective_price", self.effective_price),
                    ("spread_bps", self.spread_bps),
                    ("qty_base", self.qty_base),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"status={self.status!r} requires non-null "
                    f"{', '.join(missing)} (WHI-799 §6.2)"
                )
            if fb.gas_unknown:
                if self.total_cost_bps is not None:
                    raise ValueError(
                        f"status={self.status!r} and gas_unknown=true requires "
                        "total_cost_bps is null (WHI-799 §6.2)"
                    )
            elif self.total_cost_bps is None:
                raise ValueError(
                    f"status={self.status!r} and gas_unknown=false requires "
                    "total_cost_bps non-null (WHI-799 §6.2)"
                )
            if self.status == "excessive_impact" and self.price_impact_bps is None:
                raise ValueError(
                    "status=excessive_impact requires price_impact_bps non-null "
                    "(WHI-799 §6.2 / WHI-845)"
                )
        else:
            non_null = [
                name
                for name, value in (
                    ("effective_price", self.effective_price),
                    ("spread_bps", self.spread_bps),
                    ("total_cost_bps", self.total_cost_bps),
                    ("qty_base", self.qty_base),
                    ("fee_breakdown.explicit_fee_bps", fb.explicit_fee_bps),
                )
                if value is not None
            ]
            if non_null:
                raise ValueError(
                    f"status!='ok'/'excessive_impact' (got {self.status!r}) requires null "
                    f"{', '.join(non_null)} (WHI-799 §6.2)"
                )
        return self


class TopOfBook(BaseModel):
    """Orderbook top-of-book snapshot (WHI-799 §6.3). AMM/Prop never produce this."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    venue: str
    asset: str
    instrument_type: Literal["spot", "perp"]
    best_bid: Decimal
    best_ask: Decimal
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    mid_local: Decimal
    mid_ref: Decimal
    mid_timestamp: AwareDatetime
    spread_bps: Decimal
    spread_bps_local: Decimal
    timestamp: AwareDatetime


class SizeQuotePair(BaseModel):
    """Buy+sell pair at one size for one venue (WHI-799 §6.4; aggregator synthesizes)."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    venue: str
    asset: str
    instrument_type: InstrumentType
    notional_usd: Decimal
    buy: Quote | None = None
    sell: Quote | None = None
    round_trip_spread_bps: Decimal | None = None
    half_spread_bps: Decimal | None = None
    round_trip_total_cost_bps: Decimal | None = None
    top_of_book: TopOfBook | None = None

    @model_validator(mode="after")
    def _enforce_pair_identity(self) -> SizeQuotePair:
        """Legs and TOB must share the pair's identity key (WHI-799 §4.6 / §6.4)."""
        for leg_name, leg in (("buy", self.buy), ("sell", self.sell)):
            if leg is None:
                continue
            if leg.side != leg_name:
                raise ValueError(f"{leg_name} leg has side={leg.side!r}")
            mismatches = [
                field
                for field in (
                    "snapshot_id",
                    "venue",
                    "asset",
                    "instrument_type",
                    "notional_usd",
                )
                if getattr(leg, field) != getattr(self, field)
            ]
            if mismatches:
                raise ValueError(
                    f"{leg_name} leg mismatches pair on {', '.join(mismatches)} "
                    "(WHI-799 §4.6)"
                )
        if self.top_of_book is not None:
            tob = self.top_of_book
            if tob.instrument_type != self.instrument_type:
                raise ValueError(
                    "top_of_book.instrument_type must match pair "
                    f"(got {tob.instrument_type!r}, pair {self.instrument_type!r}; "
                    "WHI-799 §6.4)"
                )
            for field in ("snapshot_id", "venue", "asset"):
                if getattr(tob, field) != getattr(self, field):
                    raise ValueError(
                        f"top_of_book.{field} must match pair (WHI-799 §6.4)"
                    )
        return self
