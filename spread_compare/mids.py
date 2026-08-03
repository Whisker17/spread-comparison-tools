"""Reference-mid service (WHI-799 §3 / WHI-807).

One mid per ``(snapshot_id, asset)``. Adapters receive the resolved
:class:`~spread_compare.models.ReferenceMid` and must not invent their own.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from spread_compare.assets import (
    CRYPTO_BLUE_CHIPS,
    EQUITY_PERP_ASSETS,
    TOKENIZED_CEX_SPOT,
)
from spread_compare.models import MidSource, ReferenceMid
from spread_compare.settings import MidSettings, load_mid_settings

logger = logging.getLogger(__name__)

_BINANCE_FAPI = "https://fapi.binance.com"
_BINANCE_SPOT = "https://api.binance.com"
_BYBIT = "https://api.bybit.com"
_PYTH_HERMES = "https://hermes.pyth.network"

# Spot/perp symbol suffixes for major crypto on CEX wire formats.
_USDT_SYMBOL = "{asset}USDT"


class MidResolutionError(Exception):
    """No mid source could produce a price for the requested asset."""


@dataclass(frozen=True, slots=True)
class _SourceResult:
    mid: Decimal
    mid_source: MidSource
    timestamp: datetime
    sources_detail: list[str] | None = None


class MarkProvider(Protocol):
    """Optional pluggable mark source for ``proxy_perp_mark_median`` (stocks)."""

    async def marks_for(self, asset: str) -> Sequence[tuple[str, Decimal]]:
        """Return ``(source_label, mark)`` pairs that are currently available."""
        ...


FetchFn = Callable[[], Awaitable[_SourceResult | None]]


def is_mid_stale(
    quote_timestamp: datetime,
    mid_timestamp: datetime,
    *,
    stale_threshold_sec: float,
) -> bool:
    """WHI-799 §3.2: ``abs(quote.ts - mid.ts) > stale_threshold_sec``."""
    delta = abs((quote_timestamp - mid_timestamp).total_seconds())
    return delta > stale_threshold_sec


def median_marks(values: Sequence[Decimal]) -> Decimal | None:
    """Median of mark samples; even count → arithmetic mean of the two middles.

    WHI-799 §3.3 ``proxy_perp_mark_median`` rule.
    """
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    if n % 2 == 1:
        return ordered[n // 2]
    lo = ordered[n // 2 - 1]
    hi = ordered[n // 2]
    return (lo + hi) / Decimal("2")


def _parse_decimal(raw: object, *, field: str) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise MidResolutionError(f"invalid decimal for {field}: {raw!r}") from exc
    if value <= 0:
        raise MidResolutionError(f"{field} must be positive, got {value}")
    return value


class MidService:
    """Resolve a single :class:`ReferenceMid` per asset with short internal cache."""

    def __init__(
        self,
        settings: MidSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        mark_provider: MarkProvider | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings if settings is not None else load_mid_settings()
        self._client = client
        self._owns_client = client is None
        self._mark_provider = mark_provider
        self._clock = clock or time.monotonic
        self._cache: dict[str, tuple[float, _SourceResult]] = {}

    async def aclose(self) -> None:
        """Close the owned HTTP client, if any."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def settings(self) -> MidSettings:
        return self._settings

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=5.0)
        return self._client

    async def resolve(self, asset: str, *, snapshot_id: str) -> ReferenceMid:
        """Resolve mid for ``asset`` and stamp it with ``snapshot_id``.

        Raises :class:`MidResolutionError` when every source fails — callers must
        fail the whole quote package (WHI-799 §6.6).
        """
        asset_key = asset.upper()
        source = await self._resolve_source(asset_key)
        return ReferenceMid(
            snapshot_id=snapshot_id,
            asset=asset_key,
            mid=source.mid,
            mid_source=source.mid_source,
            timestamp=source.timestamp,
            sources_detail=source.sources_detail,
        )

    async def _resolve_source(self, asset: str) -> _SourceResult:
        now = self._clock()
        cached = self._cache.get(asset)
        if cached is not None:
            cached_at, result = cached
            if now - cached_at <= self._settings.cache_max_age_sec:
                return result

        result = await self._fetch_chain(asset)
        self._cache[asset] = (now, result)
        return result

    async def _fetch_chain(self, asset: str) -> _SourceResult:
        if self._settings.force_pyth:
            result = await self._try_pyth(asset)
            if result is not None:
                return result
            raise MidResolutionError(f"force_pyth set but pyth failed for {asset}")

        if asset in TOKENIZED_CEX_SPOT:
            venue = TOKENIZED_CEX_SPOT[asset]
            if venue == "binance":
                result = await self._try_binance_spot_tob(asset)
            else:
                result = await self._try_bybit_spot_tob(asset)
            if result is not None:
                return result
            raise MidResolutionError(f"tokenized spot TOB failed for {asset}")

        if asset in EQUITY_PERP_ASSETS:
            result = await self._try_proxy_mark_median(asset)
            if result is not None:
                return result
            raise MidResolutionError(f"proxy mark median failed for {asset}")

        # Crypto blue chips and "Others" share the §3.2 priority chain.
        chain: list[FetchFn] = [
            lambda: self._try_binance_usdm_index(asset),
            lambda: self._try_binance_spot_tob(asset),
            lambda: self._try_bybit_spot_tob(asset),
            lambda: self._try_pyth(asset),
        ]
        if asset not in CRYPTO_BLUE_CHIPS:
            # Others without index often still have spot TOB; chain still works.
            pass

        errors: list[str] = []
        for fetch in chain:
            try:
                result = await fetch()
            except Exception as exc:  # noqa: BLE001 — collect and fall through
                errors.append(f"{type(exc).__name__}: {exc}")
                logger.debug("mid source failed for %s: %s", asset, exc)
                continue
            if result is not None:
                return result
        detail = "; ".join(errors) if errors else "all sources returned empty"
        raise MidResolutionError(f"no mid for {asset}: {detail}")

    async def _try_binance_usdm_index(self, asset: str) -> _SourceResult | None:
        symbol = _USDT_SYMBOL.format(asset=asset)
        url = f"{_BINANCE_FAPI}/fapi/v1/premiumIndex"
        try:
            resp = await self._http().get(url, params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            price = _parse_decimal(data["indexPrice"], field="indexPrice")
            ts = _ms_to_dt(data.get("time"))
            return _SourceResult(price, "binance_usdm_index", ts)
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("binance_usdm_index failed for %s: %s", asset, exc)
            return None

    async def _try_binance_spot_tob(self, asset: str) -> _SourceResult | None:
        symbol = _USDT_SYMBOL.format(asset=asset)
        url = f"{_BINANCE_SPOT}/api/v3/ticker/bookTicker"
        try:
            resp = await self._http().get(url, params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            bid = _parse_decimal(data["bidPrice"], field="bidPrice")
            ask = _parse_decimal(data["askPrice"], field="askPrice")
            mid = (bid + ask) / Decimal("2")
            return _SourceResult(mid, "binance_spot_tob", datetime.now(tz=UTC))
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("binance_spot_tob failed for %s: %s", asset, exc)
            return None

    async def _try_bybit_spot_tob(self, asset: str) -> _SourceResult | None:
        symbol = _USDT_SYMBOL.format(asset=asset)
        url = f"{_BYBIT}/v5/market/tickers"
        try:
            resp = await self._http().get(
                url, params={"category": "spot", "symbol": symbol}
            )
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("result", {}).get("list") or []
            if not rows:
                return None
            row = rows[0]
            bid = _parse_decimal(row["bid1Price"], field="bid1Price")
            ask = _parse_decimal(row["ask1Price"], field="ask1Price")
            mid = (bid + ask) / Decimal("2")
            return _SourceResult(mid, "bybit_spot_tob", datetime.now(tz=UTC))
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("bybit_spot_tob failed for %s: %s", asset, exc)
            return None

    async def _try_pyth(self, asset: str) -> _SourceResult | None:
        feed_id = self._settings.pyth_feed_ids.get(asset)
        if not feed_id:
            return None
        # Hermes accepts hex with or without 0x; normalize to bare hex.
        feed = feed_id.removeprefix("0x")
        url = f"{_PYTH_HERMES}/v2/updates/price/latest"
        try:
            resp = await self._http().get(url, params={"ids[]": feed})
            resp.raise_for_status()
            data = resp.json()
            parsed = data.get("parsed") or []
            if not parsed:
                return None
            price_obj = parsed[0]["price"]
            raw_price = _parse_decimal(price_obj["price"], field="pyth.price")
            expo = int(price_obj["expo"])
            # price * 10^expo (expo is typically negative)
            mid = raw_price * (Decimal("10") ** Decimal(expo))
            if mid <= 0:
                return None
            publish_time = price_obj.get("publish_time")
            ts = (
                datetime.fromtimestamp(int(publish_time), tz=UTC)
                if publish_time is not None
                else datetime.now(tz=UTC)
            )
            return _SourceResult(mid, "pyth", ts, sources_detail=[f"pyth:{feed}"])
        except (
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
            MidResolutionError,
        ) as exc:
            logger.debug("pyth failed for %s: %s", asset, exc)
            return None

    async def _try_proxy_mark_median(self, asset: str) -> _SourceResult | None:
        if self._mark_provider is None:
            return None
        try:
            samples = list(await self._mark_provider.marks_for(asset))
        except Exception as exc:  # noqa: BLE001
            logger.debug("mark_provider failed for %s: %s", asset, exc)
            return None
        if not samples:
            return None
        values = [m for _, m in samples]
        med = median_marks(values)
        if med is None:
            return None
        labels = [label for label, _ in samples]
        return _SourceResult(
            med,
            "proxy_perp_mark_median",
            datetime.now(tz=UTC),
            sources_detail=labels,
        )


def _ms_to_dt(raw: object) -> datetime:
    if raw is None:
        return datetime.now(tz=UTC)
    try:
        ms = int(str(raw))
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(tz=UTC)
