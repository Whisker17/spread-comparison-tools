"""Shared CEX adapter base + quote helpers (WHI-802).

Not a venue module — leading underscore keeps auto-discovery from treating it
as an adapter. Binance and Bybit subclass :class:`CexBaseAdapter` and only
own URL/parse/rate-limit details. Walk/bps math stays in ``bookwalk`` / ``costs``.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Hashable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import httpx

from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    AdapterRateLimitedError,
    AdapterTimeoutError,
    BaseAdapter,
    UnsupportedAssetError,
    default_instrument_type,
    require_taker_bps,
)
from spread_compare.bookwalk import scale_book_to_canonical, walk_book
from spread_compare.budget import acquire_within_budget, sleep_within_budget
from spread_compare.cex_symbols import (
    resolve_cex_multiplier,
    resolve_cex_symbol,
    supported_cex_assets,
)
from spread_compare.costs import spread_bps, top_of_book_spread_bps, total_cost_bps
from spread_compare.models import (
    FeeBreakdown,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.orderbook_cache import (
    BookSnapshot,
    OrderbookSnapshotCache,
    book_cache_key,
    default_orderbook_cache,
)
from spread_compare.ratelimit import AsyncRateLimiter
from spread_compare.ws_registry import WsBookRegistry, default_ws_registry
from spread_compare.ws_serve import (
    LocalBookUnavailable,
    stamp_ws_quote_fields,
    try_local_book,
)

logger = logging.getLogger(__name__)

DEFAULT_FEE_TIER: str = "default_taker"

CexBookSide = Literal["spot", "perp"]
OrderbookLevels = list[tuple[Decimal, Decimal]]


def parse_levels(raw: Sequence[Sequence[object]]) -> OrderbookLevels:
    """Parse ``[[price, size], ...]`` string/number rows into Decimal levels."""
    levels: OrderbookLevels = []
    for row in raw:
        if len(row) < 2:
            raise AdapterError(f"orderbook level has <2 fields: {row!r}")
        price = Decimal(str(row[0]))
        size = Decimal(str(row[1]))
        if size < 0:
            raise AdapterError(f"negative level size: {size}")
        levels.append((price, size))
    return levels


def non_ok_fees(*, fee_tier: str) -> FeeBreakdown:
    """FeeBreakdown for non-ok quotes; CEX gas is explicit zero (WHI-799 §5)."""
    return FeeBreakdown(
        embedded_in_price=False,
        fee_tier=fee_tier,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_bps=Decimal("0"),
        gas_unknown=False,
        explicit_fee_bps=None,
    )


def resolve_cex_instrument(instrument_type: InstrumentType) -> CexBookSide | None:
    """Map a resolved instrument_type to spot|perp; ``None`` if not a CEX book."""
    if instrument_type in ("spot", "perp"):
        return instrument_type
    return None


def build_quote_from_book(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: CexBookSide,
    venue_symbol: str,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    trading_fee_bps: Decimal,
    fee_tier: str = DEFAULT_FEE_TIER,
    timestamp: datetime | None = None,
    multiplier: Decimal = Decimal(1),
    from_ws: bool = False,
    book_age_sec: float | None = None,
    form: str | None = None,
) -> Quote:
    """Walk the book and assemble a ``Quote`` (shared CEX path).

    When ``multiplier`` ≠ 1, levels are normalized to 1× canonical units before
    the walk so ``spread_bps`` compares against a 1× mid (WHI-826).
    """
    now = timestamp or datetime.now(tz=UTC)
    bids = scale_book_to_canonical(bids, multiplier)
    asks = scale_book_to_canonical(asks, multiplier)
    q_star = notional_usd / mid.mid
    levels = asks if side == "buy" else bids
    p_star = walk_book(levels, q_star)
    ws_extra: dict[str, object] = {}
    if from_ws and book_age_sec is not None:
        ws_extra = stamp_ws_quote_fields(mid=mid, book_age_sec=book_age_sec, quote_timestamp=now)
    if p_star is None:
        return Quote(
            snapshot_id=mid.snapshot_id,
            venue=venue,
            asset=asset,
            form=form,
            venue_symbol=venue_symbol,
            instrument_type=instrument_type,
            side=side,
            notional_usd=notional_usd,
            mid=mid.mid,
            mid_source=mid.mid_source,
            mid_timestamp=mid.timestamp,
            fee_breakdown=non_ok_fees(fee_tier=fee_tier),
            timestamp=now,
            status="insufficient_liquidity",
            qty_method="base_from_mid",
            error_code="insufficient_liquidity",
            error_message=f"depth < q_star={q_star}",
            **ws_extra,
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
        # funding_rate_8h left null (WHI-802: cheap path only; see DEFERRED_ISSUES).
        funding_rate_8h=None,
        explicit_fee_bps=cost.explicit_fee_bps,
    )
    return Quote(
        snapshot_id=mid.snapshot_id,
        venue=venue,
        asset=asset,
        form=form,
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
        **ws_extra,
    )


def build_error_quote(
    *,
    venue: str,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    mid: ReferenceMid,
    instrument_type: InstrumentType,
    error_code: str,
    message: str,
    fee_tier: str = DEFAULT_FEE_TIER,
    venue_symbol: str | None = None,
    status: Literal["unsupported_asset", "error"] = "error",
) -> Quote:
    now = datetime.now(tz=UTC)
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
        fee_breakdown=non_ok_fees(fee_tier=fee_tier),
        timestamp=now,
        status=status,
        error_code=error_code,
        error_message=message,
    )


def build_top_of_book(
    *,
    venue: str,
    asset: str,
    instrument_type: CexBookSide,
    mid: ReferenceMid,
    bids: OrderbookLevels,
    asks: OrderbookLevels,
    timestamp: datetime | None = None,
    multiplier: Decimal = Decimal(1),
    form: str | None = None,
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
        form=form,
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


class CexBaseAdapter(BaseAdapter, ABC):
    """Shared get_quote / TOB / fees / HTTP retry for orderbook CEX venues.

    Subclasses implement :meth:`_fetch_book` and tune rate-limit headers /
    retryable statuses / payload checks.
    """

    venue: str
    venue_class: VenueClass = "cex"
    # Tunables stay module-level until DESIGN.md §2 + config YAML land
    # (see docs/DEFERRED_ISSUES.md — CEX rate-limit / HTTP config).
    _min_interval_s: float = 0.2
    _max_retries: int = 4
    _backoff_start_s: float = 0.5
    _retry_http_statuses: frozenset[int] = frozenset({429})
    # Only true throttle codes become status=rate_limited (WHI-844). Other
    # retryable statuses (e.g. Bybit 403 WAF) stay AdapterFetchError.
    _rate_limit_http_statuses: frozenset[int] = frozenset({429})
    # Primary + optional alternate response headers to log for rate-limit hygiene.
    _rate_limit_log_headers: tuple[str, ...] = ()

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        book_cache: OrderbookSnapshotCache | None = None,
        ws_registry: WsBookRegistry | None = None,
    ) -> None:
        super().__init__(timeout=timeout)
        self._limiter = AsyncRateLimiter(self._min_interval_s)
        # Shared process cache by default so multi-tier + TOB reuse one HTTP hit.
        self._book_cache = (
            book_cache if book_cache is not None else default_orderbook_cache()
        )
        # Optional inject for tests; production uses the process WS registry.
        self._ws_registry = ws_registry

    def _registry(self) -> WsBookRegistry:
        return self._ws_registry if self._ws_registry is not None else default_ws_registry()

    async def _resolve_book(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        side: Side | None = None,
        q_star: Decimal | None = None,
    ) -> tuple[OrderbookLevels, OrderbookLevels, bool, float | None]:
        """Prefer local WS book; fall back to REST. Returns ``(bids, asks, from_ws, age)``."""
        local = try_local_book(
            self.venue, symbol, book_side, registry=self._registry()
        )
        # LocalBookUnavailable propagates (typed) so callers map book_stale.
        if local is not None:
            return local.bids, local.asks, True, local.age_sec
        bids, asks = await self._fetch_book(
            symbol, book_side, side=side, q_star=q_star
        )
        return bids, asks, False, None

    @abstractmethod
    async def _fetch_book(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        side: Side | None = None,
        q_star: Decimal | None = None,
    ) -> tuple[OrderbookLevels, OrderbookLevels]:
        """Return ``(bids, asks)`` best-first. May use ``side``/``q_star`` to escalate depth."""
        ...

    async def _cached_depth_fetch(
        self,
        symbol: str,
        book_side: CexBookSide,
        *,
        depth: Hashable,
        fetch: Callable[[], Awaitable[tuple[OrderbookLevels, OrderbookLevels]]],
    ) -> BookSnapshot:
        """Fetch via the short-TTL book cache (depth is part of the key — WHI-843)."""
        key = book_cache_key(self.venue, symbol, book_side, depth)
        return await self._book_cache.get_or_fetch(key, fetch, depth=depth)

    def _log_rate_limit_headers(self, resp: httpx.Response, url: str) -> None:
        for name in self._rate_limit_log_headers:
            value = resp.headers.get(name)
            if value is not None:
                logger.info("%s %s=%s url=%s", self.venue, name, value, url)
                return

    def _payload_is_rate_limited(self, payload: dict[str, Any]) -> bool:
        """Return True when the body indicates a retryable rate limit."""
        return False

    def _validate_success_payload(self, payload: dict[str, Any]) -> None:
        """Raise AdapterFetchError for non-retryable business errors in ``payload``."""
        return None

    async def _request_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        """GET JSON with throttle, header logging, and exponential backoff."""
        delay = self._backoff_start_s
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            await acquire_within_budget(self._limiter, venue=self.venue)
            try:
                resp = await self.http.get(url, params=params)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"{self.venue} timeout: {url}") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"{self.venue} HTTP error: {exc}") from exc

            self._log_rate_limit_headers(resp, url)

            if resp.status_code in self._retry_http_statuses:
                is_throttle = resp.status_code in self._rate_limit_http_statuses
                if is_throttle:
                    last_error = AdapterRateLimitedError(
                        f"{self.venue} rate limited (HTTP {resp.status_code}) "
                        f"attempt={attempt + 1}",
                        retry_after_s=delay,
                    )
                else:
                    last_error = AdapterFetchError(
                        f"{self.venue} HTTP {resp.status_code} retryable "
                        f"attempt={attempt + 1}"
                    )
                logger.warning("%s", last_error)
                if attempt + 1 < self._max_retries:
                    if is_throttle:
                        await sleep_within_budget(
                            delay, venue=self.venue, reason="rate limited"
                        )
                    else:
                        await asyncio.sleep(delay)
                    delay *= 2
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"{self.venue} HTTP {resp.status_code}: {resp.text[:200]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise AdapterFetchError(f"{self.venue} response is not JSON") from exc
            if not isinstance(payload, dict):
                raise AdapterFetchError(
                    f"{self.venue} unexpected JSON type: {type(payload)}"
                )

            if self._payload_is_rate_limited(payload):
                last_error = AdapterRateLimitedError(
                    f"{self.venue} body rate-limit attempt={attempt + 1}",
                    retry_after_s=delay,
                )
                logger.warning("%s", last_error)
                if attempt + 1 < self._max_retries:
                    await sleep_within_budget(
                        delay, venue=self.venue, reason="body rate-limit"
                    )
                    delay *= 2
                continue

            self._validate_success_payload(payload)
            return payload

        if last_error is not None:
            raise last_error
        raise AdapterFetchError(f"{self.venue} request failed with no response")

    async def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
        form: str | None = None,
    ) -> Quote:
        explicit_itype = instrument_type is not None
        requested = instrument_type or default_instrument_type(self.venue_class)
        asset_key = asset.upper()
        # Echo requested tier name (mock parity); Phase 1 bps stay default_taker
        # (WHI-799 §11 Q3) regardless of fee_tier label.
        tier = fee_tier or DEFAULT_FEE_TIER

        if mid.asset.upper() != asset_key:
            raise AdapterError(
                f"mid.asset={mid.asset!r} does not match asset={asset!r}"
            )

        book_side = resolve_cex_instrument(requested)
        if book_side is None:
            return build_error_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=requested,
                error_code="unsupported_instrument_type",
                message=(
                    f"CEX adapters only support instrument_type spot|perp, "
                    f"got {requested!r}"
                ),
                fee_tier=tier,
                status="error",
            )

        symbol = resolve_cex_symbol(asset_key, book_side, form=form, venue=self.venue)
        # Equity perps have no CEX spot book — when the caller omitted
        # instrument_type and form, fall through to the only listed book (WHI-826).
        if (
            symbol is None
            and not explicit_itype
            and form is None
            and book_side == "spot"
            and resolve_cex_symbol(asset_key, "perp", form=form, venue=self.venue) is not None
        ):
            book_side = "perp"
            symbol = resolve_cex_symbol(asset_key, "perp", form=form, venue=self.venue)
        if symbol is None or not self._venue_lists_asset(
            asset_key, book_side, form=form
        ):
            return build_error_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=book_side,
                error_code="unsupported_asset",
                message=(
                    f"{asset} not supported by {self.venue} adapter "
                    f"as instrument_type={book_side!r}"
                    + (f" form={form!r}" if form else "")
                ),
                fee_tier=tier,
                status="unsupported_asset",
            )

        schedule = self.get_fees(asset_key, instrument_type=book_side)
        trading_fee = require_taker_bps(self.venue, schedule)
        multiplier = resolve_cex_multiplier(asset_key, book_side, form=form)

        q_star = notional_usd / mid.mid
        try:
            bids, asks, from_ws, book_age = await self._resolve_book(
                symbol, book_side, side=side, q_star=q_star
            )
        except LocalBookUnavailable as exc:
            return build_error_quote(
                venue=self.venue,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                mid=mid,
                instrument_type=book_side,
                error_code=exc.code,
                message=exc.message,
                fee_tier=tier,
                venue_symbol=symbol,
                status="error",
            )
        return build_quote_from_book(
            venue=self.venue,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            mid=mid,
            instrument_type=book_side,
            venue_symbol=symbol,
            bids=bids,
            asks=asks,
            fee_tier=tier,
            trading_fee_bps=trading_fee,
            multiplier=multiplier,
            from_ws=from_ws,
            book_age_sec=book_age,
            form=form,
        )

    async def get_quotes_batch(
        self,
        asset: str,
        sides: Sequence[Side],
        notionals: Sequence[Decimal],
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
        form: str | None = None,
    ) -> list[Quote]:
        """Price many notionals/sides from **one** orderbook fetch (WHI-843).

        Fetches depth sufficient for the largest notional, then walks that book
        at every size. All returned quotes share one wall-clock timestamp.
        Per-tier ``insufficient_liquidity`` is still possible when the book
        fills a smaller tier but not a larger one.
        """
        if not notionals:
            raise AdapterError("get_quotes_batch requires at least one notional")
        if not sides:
            raise AdapterError("get_quotes_batch requires at least one side")

        explicit_itype = instrument_type is not None
        requested = instrument_type or default_instrument_type(self.venue_class)
        asset_key = asset.upper()
        tier = fee_tier or DEFAULT_FEE_TIER

        if mid.asset.upper() != asset_key:
            raise AdapterError(
                f"mid.asset={mid.asset!r} does not match asset={asset!r}"
            )

        book_side = resolve_cex_instrument(requested)
        if book_side is None:
            return [
                build_error_quote(
                    venue=self.venue,
                    asset=asset_key,
                    side=side,
                    notional_usd=n,
                    mid=mid,
                    instrument_type=requested,
                    error_code="unsupported_instrument_type",
                    message=(
                        f"CEX adapters only support instrument_type spot|perp, "
                        f"got {requested!r}"
                    ),
                    fee_tier=tier,
                    status="error",
                )
                for n in notionals
                for side in sides
            ]

        symbol = resolve_cex_symbol(asset_key, book_side, form=form, venue=self.venue)
        if (
            symbol is None
            and not explicit_itype
            and form is None
            and book_side == "spot"
            and resolve_cex_symbol(asset_key, "perp", form=form, venue=self.venue) is not None
        ):
            book_side = "perp"
            symbol = resolve_cex_symbol(asset_key, "perp", form=form, venue=self.venue)
        if symbol is None or not self._venue_lists_asset(
            asset_key, book_side, form=form
        ):
            return [
                build_error_quote(
                    venue=self.venue,
                    asset=asset_key,
                    side=side,
                    notional_usd=n,
                    mid=mid,
                    instrument_type=book_side,
                    error_code="unsupported_asset",
                    message=(
                        f"{asset} not supported by {self.venue} adapter "
                        f"as instrument_type={book_side!r}"
                        + (f" form={form!r}" if form else "")
                    ),
                    fee_tier=tier,
                    status="unsupported_asset",
                )
                for n in notionals
                for side in sides
            ]

        schedule = self.get_fees(asset_key, instrument_type=book_side)
        trading_fee = require_taker_bps(self.venue, schedule)
        multiplier = resolve_cex_multiplier(asset_key, book_side, form=form)

        # Depth for the largest tier — escalate until *every* requested side fills
        # q_max (or max depth). One-sided escalation would leave the opposite
        # side under-depth on asymmetric books (WHI-843 / §4.7 parity).
        max_notional = max(notionals)
        q_max = max_notional / mid.mid
        side_order = list(sides)
        try:
            bids, asks, from_ws, book_age = await self._resolve_book(
                symbol, book_side, side=side_order[0], q_star=q_max
            )
        except LocalBookUnavailable as exc:
            return [
                build_error_quote(
                    venue=self.venue,
                    asset=asset_key,
                    side=side,
                    notional_usd=n,
                    mid=mid,
                    instrument_type=book_side,
                    error_code=exc.code,
                    message=exc.message,
                    fee_tier=tier,
                    venue_symbol=symbol,
                    status="error",
                )
                for n in notionals
                for side in sides
            ]
        if not from_ws:
            for extra_side in side_order[1:]:
                levels = asks if extra_side == "buy" else bids
                if walk_book(levels, q_max) is not None:
                    continue
                # Re-escalate for the under-filled side; only adopt the new book if
                # it still fills every side that already filled on the prior book.
                new_bids, new_asks = await self._fetch_book(
                    symbol, book_side, side=extra_side, q_star=q_max
                )
                ok_to_swap = True
                for prior in side_order:
                    prior_levels = asks if prior == "buy" else bids
                    new_levels = new_asks if prior == "buy" else new_bids
                    if (
                        walk_book(prior_levels, q_max) is not None
                        and walk_book(new_levels, q_max) is None
                    ):
                        ok_to_swap = False
                        break
                if ok_to_swap:
                    bids, asks = new_bids, new_asks
        shared_ts = datetime.now(tz=UTC)

        out: list[Quote] = []
        for n in notionals:
            for side in sides:
                out.append(
                    build_quote_from_book(
                        venue=self.venue,
                        asset=asset_key,
                        side=side,
                        notional_usd=n,
                        mid=mid,
                        instrument_type=book_side,
                        venue_symbol=symbol,
                        bids=bids,
                        asks=asks,
                        fee_tier=tier,
                        trading_fee_bps=trading_fee,
                        timestamp=shared_ts,
                        multiplier=multiplier,
                        from_ws=from_ws,
                        book_age_sec=book_age,
                        form=form,
                    )
                )
        return out

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
        form: str | None = None,
    ) -> TopOfBook | None:
        asset_key = asset.upper()
        book_side: CexBookSide = instrument_type or "spot"
        symbol = resolve_cex_symbol(asset_key, book_side, form=form, venue=self.venue)
        if symbol is None:
            raise UnsupportedAssetError(
                f"{asset} not supported by {self.venue} as {book_side}"
                + (f" form={form!r}" if form else "")
            )
        multiplier = resolve_cex_multiplier(asset_key, book_side, form=form)
        bids, asks, _from_ws, _age = await self._resolve_book(symbol, book_side)
        return build_top_of_book(
            venue=self.venue,
            asset=asset_key,
            instrument_type=book_side,
            mid=mid,
            bids=bids,
            asks=asks,
            multiplier=multiplier,
            form=form,
        )

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
        form: str | None = None,
    ) -> list[str]:
        if instrument_type in ("spot", "perp"):
            assets = supported_cex_assets(instrument_type, form=form)
        else:
            assets = supported_cex_assets()
        return [
            a
            for a in assets
            if self._venue_lists_asset(a, instrument_type, form=form)
        ]

    def _venue_lists_asset(
        self,
        asset: str,
        instrument_type: InstrumentType | CexBookSide | None,
        *,
        form: str | None = None,
    ) -> bool:
        """Per-venue listing filter (override for Bybit bStock gaps, etc.)."""
        _ = asset, instrument_type, form
        return True
