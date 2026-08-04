"""Shared perp-DEX adapter helpers (quote shell, fees, rate limiting).

Not a venue module — leading underscore keeps auto-discovery from importing it
as an adapter. Perp adapters import from here; walk/bps math stay in
``bookwalk`` / ``costs`` only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    AdapterRateLimitedError,
    AdapterTimeoutError,
)
from spread_compare.bookwalk import scale_book_to_canonical, walk_book
from spread_compare.budget import would_exceed_budget
from spread_compare.costs import (
    basis_bps,
    spread_bps,
    top_of_book_spread_bps,
    total_cost_bps,
)
from spread_compare.models import (
    FeeBreakdown,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
)
from spread_compare.ratelimit import (
    AsyncRateLimiter,
    RollingWindowRateLimiter,
    acquire_within_budget,
)

# Rate/depth defaults trace to docs/research/WHI-800-venue-api-survey.md §4
# until DESIGN.md §2 exists (see docs/DEFERRED_ISSUES.md).
DEFAULT_FEE_TIER: str = "default_taker"

OrderbookLevels = list[tuple[Decimal, Decimal]]


def parse_levels(raw: Sequence[Sequence[object]]) -> OrderbookLevels:
    """Parse ``[[price, size], ...]`` string/number rows into Decimal levels."""
    levels: OrderbookLevels = []
    for row in raw:
        if len(row) < 2:
            raise AdapterError(f"orderbook level has <2 fields: {row!r}")
        try:
            price = Decimal(str(row[0]))
            size = Decimal(str(row[1]))
        except (ArithmeticError, ValueError) as exc:
            raise AdapterError(f"orderbook level not numeric: {row!r}") from exc
        if size < 0:
            raise AdapterError(f"negative level size: {size}")
        levels.append((price, size))
    return levels


def require_mid_asset(mid: ReferenceMid, asset: str) -> None:
    """Raise AdapterError when ``mid.asset`` does not match the requested asset."""
    if mid.asset.upper() != asset.upper():
        raise AdapterError(f"mid.asset={mid.asset!r} does not match asset={asset!r}")


def aggregate_orders_by_price(
    orders: Sequence[dict[str, object]],
    *,
    price_key: str = "price",
    size_key: str = "remaining_base_amount",
    descending: bool = False,
) -> OrderbookLevels:
    """Aggregate per-order book rows into price levels (Lighter shape).

    Use ``descending=False`` for asks (best ask first) and ``descending=True``
    for bids (best bid first).
    """
    buckets: dict[Decimal, Decimal] = {}
    for order in orders:
        try:
            price = Decimal(str(order[price_key]))
            size = Decimal(str(order[size_key]))
        except (KeyError, TypeError, ArithmeticError) as exc:
            raise AdapterError(f"order row parse failed: {order!r}") from exc
        if size < 0:
            raise AdapterError(f"negative order size: {size}")
        if size == 0:
            continue
        buckets[price] = buckets.get(price, Decimal("0")) + size

    prices = sorted(buckets.keys(), reverse=descending)
    return [(px, buckets[px]) for px in prices]


def non_ok_fees(*, fee_tier: str) -> FeeBreakdown:
    return FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=None,
    )


def build_quote_from_book(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    venue_symbol: str,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    fee_tier: str = DEFAULT_FEE_TIER,
    trading_fee_bps: Decimal,
    funding_rate_8h: Decimal | None = None,
    venue_mark: Decimal | None = None,
    timestamp: datetime | None = None,
    multiplier: Decimal = Decimal(1),
) -> Quote:
    """Walk the book and assemble a ``Quote`` (shared perp path).

    ``multiplier`` scales venue contract units to 1× canonical before walk/bps
    (e.g. HL ``kPEPE`` / CEX ``1000PEPE`` — WHI-826).
    """
    now = timestamp or datetime.now(tz=UTC)
    fees = non_ok_fees(fee_tier=fee_tier)
    if mid.mid <= 0:
        raise AdapterError(f"mid must be positive, got {mid.mid}")
    bids = scale_book_to_canonical(bids, multiplier)
    asks = scale_book_to_canonical(asks, multiplier)
    mark = venue_mark
    if mark is not None and multiplier != 1:
        mark = mark / multiplier
    q_star = notional_usd / mid.mid
    levels = asks if side == "buy" else bids
    p_star = walk_book(levels, q_star)

    basis: Decimal | None = None
    if mark is not None:
        basis = basis_bps(mark, mid.mid)

    if p_star is None:
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
            fee_breakdown=fees,
            timestamp=now,
            status="insufficient_liquidity",
            qty_method="base_from_mid",
            venue_mark=mark,
            basis_bps=basis,
            error_code="insufficient_liquidity",
            error_message=f"depth < q_star={q_star}",
        )

    sp = spread_bps(side, p_star, mid.mid)
    cost = total_cost_bps(
        sp,
        embedded_in_price=False,
        trading_fee_bps=trading_fee_bps,
        platform_fee_bps=Decimal("0"),
        gas_unknown=False,
        gas_usd=None,
        notional_usd=notional_usd,
    )
    ok_fees = FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=trading_fee_bps,
        platform_fee_bps=Decimal("0"),
        gas_usd=None,
        gas_bps=cost.gas_bps,  # explicit 0 when gas_usd is None
        gas_unknown=False,
        funding_rate_8h=funding_rate_8h if instrument_type == "perp" else None,
        explicit_fee_bps=cost.explicit_fee_bps,
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
        effective_price=p_star,
        spread_bps=sp,
        fee_breakdown=ok_fees,
        total_cost_bps=cost.total_cost_bps,
        timestamp=now,
        status="ok",
        qty_base=q_star,
        qty_method="base_from_mid",
        venue_mark=mark,
        basis_bps=basis,
    )


def build_unsupported_quote(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    message: str,
    fee_tier: str = DEFAULT_FEE_TIER,
) -> Quote:
    now = datetime.now(tz=UTC)
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        side=side,
        notional_usd=notional_usd,
        mid=mid.mid,
        mid_source=mid.mid_source,
        mid_timestamp=mid.timestamp,
        fee_breakdown=non_ok_fees(fee_tier=fee_tier),
        timestamp=now,
        status="unsupported_asset",
        error_code="unsupported_asset",
        error_message=message,
    )


def build_top_of_book(
    *,
    venue: str,
    asset: str,
    mid: ReferenceMid,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    instrument_type: Literal["spot", "perp"] = "perp",
    timestamp: datetime | None = None,
    multiplier: Decimal = Decimal(1),
) -> TopOfBook:
    bids = scale_book_to_canonical(bids, multiplier)
    asks = scale_book_to_canonical(asks, multiplier)
    if not bids or not asks:
        raise AdapterError(f"{venue}: empty bids or asks for TOB")
    best_bid, bid_size = bids[0]
    best_ask, ask_size = asks[0]
    mid_local = (best_bid + best_ask) / Decimal("2")
    now = timestamp or datetime.now(tz=UTC)
    return TopOfBook(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        instrument_type=instrument_type,
        best_bid=best_bid,
        best_ask=best_ask,
        bid_size=bid_size,
        ask_size=ask_size,
        mid_local=mid_local,
        mid_ref=mid.mid,
        mid_timestamp=mid.timestamp,
        spread_bps=top_of_book_spread_bps(best_bid, best_ask, mid.mid),
        spread_bps_local=top_of_book_spread_bps(best_bid, best_ask, mid_local),
        timestamp=now,
    )


def resolve_perp_instrument(
    instrument_type: InstrumentType | None,
    *,
    venue_class_default: InstrumentType = "perp",
) -> InstrumentType:
    """Map optional instrument_type; perp DEX default is ``perp`` (WHI-799 §7)."""
    itype = instrument_type or venue_class_default
    if itype != "perp":
        raise AdapterError(
            f"perp DEX adapters only support instrument_type=perp, got {itype!r}"
        )
    return itype


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    venue: str,
    limiter: AsyncRateLimiter | RollingWindowRateLimiter,
    params: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    retry_statuses: frozenset[int] = frozenset({429}),
    max_retries: int = 4,
    backoff_start_s: float = 0.5,
    ok_codes: frozenset[int | None] | None = None,
) -> Any:
    """Shared GET/POST JSON helper with rate-limit backoff for perp adapters."""
    delay = backoff_start_s
    last_error: Exception | None = None
    for attempt in range(max_retries):
        await acquire_within_budget(limiter, venue=venue)
        try:
            resp = await client.request(method, url, params=params, json=json_body)
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(f"{venue} timeout: {url}") from exc
        except httpx.HTTPError as exc:
            raise AdapterFetchError(f"{venue} HTTP error: {exc}") from exc

        if resp.status_code in retry_statuses:
            last_error = AdapterRateLimitedError(
                f"{venue} rate limited (HTTP {resp.status_code}) attempt={attempt + 1}",
                retry_after_s=delay,
            )
            if would_exceed_budget(delay):
                raise AdapterRateLimitedError(
                    f"{venue} rate limited; backoff {delay:.2f}s exceeds "
                    f"remaining quote budget",
                    retry_after_s=delay,
                )
            await asyncio.sleep(delay)
            delay *= 2
            continue

        if resp.status_code >= 400:
            raise AdapterFetchError(
                f"{venue} HTTP {resp.status_code}: {resp.text[:200]}"
            )

        try:
            payload = resp.json()
        except ValueError as exc:
            raise AdapterFetchError(f"{venue} response is not JSON") from exc

        if ok_codes is not None and isinstance(payload, dict):
            code = payload.get("code")
            if code not in ok_codes:
                raise AdapterFetchError(
                    f"{venue} code={code} body={str(payload)[:200]}"
                )
        return payload

    assert last_error is not None
    raise last_error
