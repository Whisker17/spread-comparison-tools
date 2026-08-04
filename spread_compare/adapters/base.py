"""VenueAdapter protocol, BaseAdapter lifecycle, and error hierarchy (WHI-799 §7).

WHI-823: I/O methods are async; metadata reads stay sync (state cached at startup).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

import httpx

from spread_compare.fees import get_fee_schedule
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)

_DEFAULT_HTTP_TIMEOUT = 10.0


class AdapterError(Exception):
    """Base error for adapter failures (fetch/timeout/parse).

    Orderbook venues must raise this (or a subclass) on TOB fetch failure —
    never return ``None`` for failure (``None`` means "no orderbook concept").
    """


class AdapterFetchError(AdapterError):
    """Upstream HTTP/RPC fetch or parse failed."""


class AdapterTimeoutError(AdapterError):
    """Upstream call timed out."""


class AdapterRateLimitedError(AdapterError):
    """Upstream rate limit or local limiter wait exceeds remaining quote budget (WHI-844).

    Mapped to ``Quote.status=rate_limited`` so the UI can distinguish it from
    a genuine timeout. ``retry_after_s`` is optional operator telemetry.
    """

    def __init__(self, message: str, *, retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class UnsupportedAssetError(AdapterError):
    """Asset is not supported by this venue for the requested instrument type."""


class AdapterConfigError(AdapterError):
    """Client/config misuse that must fail fast (never map to empty quote)."""


class VenueAdapter(Protocol):
    """Cross-venue adapter surface (WHI-799 §7; async I/O per WHI-823)."""

    venue: str
    venue_class: VenueClass

    async def startup(self) -> None:
        """Build clients and cache state used by sync metadata methods.

        Must be idempotent: a second call is a no-op.
        """
        ...

    async def aclose(self) -> None:
        """Release resources. Safe to call without a prior ``startup()``."""
        ...

    async def get_quote(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        instrument_type: InstrumentType | None = None,
        fee_tier: str | None = None,
    ) -> Quote:
        """Return a size-aware quote. Computes spread/total bps via shared formulas."""
        ...

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        """Return TOB for orderbook venues; always None for AMM/Prop.

        On fetch failure, raise AdapterError — do not return None.
        """
        ...

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        """Return the static fee schedule for this venue (config-backed, WHI-812)."""
        ...

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        """Assets this adapter can quote for the given (or default) instrument type."""
        ...


class BaseAdapter:
    """Concrete lifecycle + shared ``httpx.AsyncClient`` for venue adapters.

    Subclasses implement quote methods and set ``venue`` / ``venue_class``.
    Override ``startup`` to fetch metadata after ``await super().startup()``.
    The HTTP client is created lazily on first ``http`` access — ``startup`` itself
    is a no-op so adapters with no network work at boot stay offline-safe.
    """

    venue: str
    venue_class: VenueClass

    def __init__(self, *, timeout: float = _DEFAULT_HTTP_TIMEOUT) -> None:
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._started = False

    @property
    def http(self) -> httpx.AsyncClient:
        """Lazily create a shared async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def startup(self) -> None:
        """Idempotent no-op base; subclasses override for metadata warm-up."""
        if self._started:
            return
        self._started = True

    async def aclose(self) -> None:
        """Close the HTTP client if created. Safe without prior ``startup()``."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._started = False

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        """Config-backed fee schedule (WHI-812). Override for scaffold-only adapters."""
        itype = instrument_type or default_instrument_type(self.venue_class)
        return get_fee_schedule(self.venue, itype, asset=asset)


def default_instrument_type(venue_class: VenueClass) -> InstrumentType:
    """Default instrument_type when the caller passes None (WHI-799 §7)."""
    mapping: dict[VenueClass, InstrumentType] = {
        "cex": "spot",
        "perp_dex": "perp",
        "amm_dex": "amm_pool",
        "prop_amm": "prop_amm",
    }
    return mapping[venue_class]


def require_taker_bps(venue: str, schedule: FeeSchedule) -> Decimal:
    """Return schedule.taker_bps or raise when missing (orderbook venues)."""
    if schedule.taker_bps is None:
        raise AdapterError(f"{venue}: fee schedule missing taker_bps")
    return schedule.taker_bps
