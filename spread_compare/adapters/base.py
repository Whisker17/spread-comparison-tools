"""VenueAdapter protocol, BaseAdapter lifecycle, and error hierarchy (WHI-799 §7).

WHI-823: I/O methods are async; metadata reads stay sync (state cached at startup).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

import httpx

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


class UnsupportedAssetError(AdapterError):
    """Asset is not supported by this venue for the requested instrument type."""


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
        """Return the static fee schedule for this venue (numbers may be placeholders)."""
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

    Subclasses implement quote/fee methods. Override ``startup`` to fetch
    metadata (market maps, label tables) after calling ``await super().startup()``.
    The HTTP client is created lazily on first ``http`` access — ``startup`` itself
    is a no-op so adapters with no network work at boot stay offline-safe.
    """

    def __init__(
        self,
        *,
        timeout: float = _DEFAULT_HTTP_TIMEOUT,
        trust_env: bool = True,
    ) -> None:
        self._timeout = timeout
        self._trust_env = trust_env
        self._client: httpx.AsyncClient | None = None
        self._started = False

    @property
    def http(self) -> httpx.AsyncClient:
        """Lazily create a shared async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                trust_env=self._trust_env,
            )
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


def default_instrument_type(venue_class: VenueClass) -> InstrumentType:
    """Default instrument_type when the caller passes None (WHI-799 §7)."""
    mapping: dict[VenueClass, InstrumentType] = {
        "cex": "spot",
        "perp_dex": "perp",
        "amm_dex": "amm_pool",
        "prop_amm": "prop_amm",
    }
    return mapping[venue_class]
