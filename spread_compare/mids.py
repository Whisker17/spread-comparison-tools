"""Reference-mid service (WHI-799 §3 / WHI-807).

One mid per ``(snapshot_id, asset)``. Adapters receive the resolved
:class:`~spread_compare.models.ReferenceMid` and must not invent their own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from spread_compare.assets import STOCK_PERP_UNDERLYINGS, is_stock_asset
from spread_compare.cex_symbols import resolve_cex_multiplier, resolve_cex_symbol
from spread_compare.models import MidSource, ReferenceMid
from spread_compare.settings import MidSettings, StockMidP2Step, load_mid_settings

logger = logging.getLogger(__name__)

_BINANCE_FAPI = "https://fapi.binance.com"
_BINANCE_SPOT = "https://api.binance.com"
_BYBIT = "https://api.bybit.com"
_HYPERLIQUID = "https://api.hyperliquid.xyz"
_PYTH_HERMES = "https://hermes.pyth.network"


class MidResolutionError(Exception):
    """No mid source could produce a price for the requested asset."""


@dataclass(frozen=True, slots=True)
class _SourceResult:
    mid: Decimal
    mid_source: MidSource
    timestamp: datetime
    sources_detail: list[str] | None = None


class MarkProvider(Protocol):
    """Pluggable mark source for ``proxy_perp_mark_median`` (stocks)."""

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


def _ms_to_dt(raw: object) -> datetime:
    if raw is None:
        return datetime.now(tz=UTC)
    try:
        ms = int(str(raw))
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return datetime.now(tz=UTC)


class DefaultMarkProvider:
    """Fetch available perp marks from public CEX / perp-DEX endpoints (WHI-799 §3.3)."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def marks_for(self, asset: str) -> Sequence[tuple[str, Decimal]]:
        """Sample marks from the five §3.3 venues (skip silently when unavailable)."""
        asset_key = asset.upper()
        # Prefer perp wire form when listed (e.g. 1000PEPEUSDT); scale to 1×.
        # Stocks: form=perp symbols (WHI-881).
        form = "perp" if is_stock_asset(asset_key) else None
        bn_sym = resolve_cex_symbol(
            asset_key, "perp", form=form, venue="binance"
        )
        by_sym = resolve_cex_symbol(
            asset_key, "perp", form=form, venue="bybit"
        )
        mult = resolve_cex_multiplier(asset_key, "perp", form=form)
        labeled = (
            ("binance", self._binance_mark_scaled(bn_sym, mult)),
            ("bybit", self._bybit_mark_scaled(by_sym, mult)),
            ("hyperliquid", self._hyperliquid_mark(asset_key)),
            ("lighter", self._lighter_mark(asset_key)),
            ("apex", self._apex_mark(asset_key)),
        )
        results = await asyncio.gather(
            *(coro for _, coro in labeled), return_exceptions=True
        )
        samples: list[tuple[str, Decimal]] = []
        for (label, _), result in zip(labeled, results, strict=True):
            if isinstance(result, BaseException):
                logger.debug("mark %s failed for %s: %s", label, asset, result)
                continue
            if result is not None:
                samples.append((label, result))
        return samples

    async def _binance_mark_scaled(
        self, symbol: str | None, mult: Decimal
    ) -> Decimal | None:
        if not symbol:
            return None
        resp = await self._client.get(
            f"{_BINANCE_FAPI}/fapi/v1/premiumIndex", params={"symbol": symbol}
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        raw = data.get("markPrice") or data.get("indexPrice")
        if raw is None:
            return None
        mark = _parse_decimal(raw, field="binance.mark")
        return mark / mult if mult != 1 else mark

    async def _bybit_mark_scaled(
        self, symbol: str | None, mult: Decimal
    ) -> Decimal | None:
        if not symbol:
            return None
        return await self._bybit_mark(symbol, mult=mult)

    async def _bybit_mark(self, symbol: str, *, mult: Decimal = Decimal(1)) -> Decimal | None:
        resp = await self._client.get(
            f"{_BYBIT}/v5/market/tickers",
            params={"category": "linear", "symbol": symbol},
        )
        if resp.status_code >= 400:
            return None
        rows = resp.json().get("result", {}).get("list") or []
        if not rows:
            return None
        raw = rows[0].get("markPrice") or rows[0].get("lastPrice")
        if raw is None or raw == "":
            return None
        mark = _parse_decimal(raw, field="bybit.mark")
        return mark / mult if mult != 1 else mark

    async def _hyperliquid_mark(self, asset: str) -> Decimal | None:
        """Resolve mark from main book or HIP-3 ``xyz`` (WHI-826 / WHI-798 §8 Q10).

        Scales only when the scaled venue coin (e.g. kPEPE) is what matched.
        """
        from spread_compare.perp_symbols import (
            UnsupportedPerpSymbolError,
            resolve_hl_coin,
        )

        try:
            resolved = resolve_hl_coin(asset)
        except UnsupportedPerpSymbolError:
            resolved = None
        coin = resolved.venue_symbol if resolved is not None else asset.upper()
        mult = resolved.multiplier if resolved is not None else Decimal(1)
        dex = coin.split(":", 1)[0] if ":" in coin else ""
        body: dict[str, object] = {"type": "metaAndAssetCtxs"}
        if dex:
            body["dex"] = dex
        resp = await self._client.post(f"{_HYPERLIQUID}/info", json=body)
        if resp.status_code >= 400:
            return None
        data = resp.json()
        if not isinstance(data, list) or len(data) < 2:
            return None
        meta, ctxs = data[0], data[1]
        universe = meta.get("universe") or []
        bare = coin.split(":", 1)[-1]
        # Only match the resolved venue coin (and bare HIP-3 name), not a 1× alias.
        targets = {coin, coin.lower()}
        if dex:
            targets.add(bare)
            targets.add(bare.upper())
        for i, entry in enumerate(universe):
            if i >= len(ctxs):
                break
            name = str(entry.get("name") or "")
            candidates = {name, name.upper(), name.lower()}
            if ":" not in name and dex:
                candidates.add(f"{dex}:{name.upper()}")
            if candidates.isdisjoint(targets):
                continue
            raw = ctxs[i].get("markPx")
            if raw is None:
                return None
            mark = _parse_decimal(raw, field="hyperliquid.mark")
            # Scale only for known scaled coins (kPEPE); HIP-3 equity is mult=1.
            return mark / mult if mult != 1 else mark
        return None

    async def _lighter_mark(self, asset: str) -> Decimal | None:
        # Public orderBooks list; match by symbol when present.
        from spread_compare.perp_symbols import resolve_lighter_symbol

        resolved = resolve_lighter_symbol(asset)
        venue_sym = resolved.venue_symbol.upper()
        mult = resolved.multiplier
        resp = await self._client.get(
            "https://mainnet.zklighter.elliot.ai/api/v1/orderBooks"
        )
        if resp.status_code >= 400:
            return None
        data = resp.json()
        books: list[object]
        if isinstance(data, list):
            books = data
        elif isinstance(data, dict):
            raw_books = data.get("order_books") or data.get("orderBooks") or []
            books = raw_books if isinstance(raw_books, list) else []
        else:
            books = []
        for book in books:
            if not isinstance(book, dict):
                continue
            name_u = str(book.get("symbol") or book.get("market_id") or "").upper()
            # Exact venue wire form only — never match 1× PEPE when we need 1000PEPE.
            if name_u != venue_sym:
                continue
            raw = book.get("mark_price") or book.get("last_trade_price")
            if raw is None:
                return None
            mark = _parse_decimal(raw, field="lighter.mark")
            return mark / mult if mult != 1 else mark
        return None

    async def _apex_mark(self, asset: str) -> Decimal | None:
        from spread_compare.perp_symbols import resolve_apex_base

        resolved = resolve_apex_base(asset)
        mult = resolved.multiplier
        # Only the resolved wire form (1000PEPEUSDT when scaled) — no 1× fallback.
        symbols = [f"{resolved.venue_symbol}USDT"]
        if mult == 1:
            symbols.extend([f"{asset}USDT", f"{asset}-USDT"])
        payload: object | None = None
        for symbol in symbols:
            resp = await self._client.get(
                "https://omni.apex.exchange/api/v3/ticker",
                params={"symbol": symbol},
            )
            if resp.status_code >= 400:
                continue
            data = resp.json()
            payload = data.get("data") if isinstance(data, dict) else data
            if isinstance(payload, list) and payload:
                payload = payload[0]
            if isinstance(payload, dict):
                break
        if not isinstance(payload, dict):
            return None
        raw = payload.get("markPrice") or payload.get("lastPrice") or payload.get("fairPrice")
        if raw is None:
            return None
        mark = _parse_decimal(raw, field="apex.mark")
        return mark / mult if mult != 1 else mark


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
            self._client = httpx.AsyncClient(timeout=self._settings.http_timeout_sec)
        return self._client

    def _marks(self) -> MarkProvider:
        if self._mark_provider is not None:
            return self._mark_provider
        return DefaultMarkProvider(self._http())

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

    def seed_cache(
        self,
        asset: str,
        *,
        mid: Decimal,
        mid_source: MidSource,
        timestamp: datetime,
    ) -> None:
        """Inject a fresh mid into the short-lived cache (WHI-847 fast mid path).

        Does not invent a ``snapshot_id`` — that is stamped at :meth:`resolve` time.
        """
        asset_key = asset.upper()
        if mid <= 0:
            raise ValueError(f"mid must be positive, got {mid}")
        self._cache[asset_key] = (
            self._clock(),
            _SourceResult(mid, mid_source, timestamp),
        )

    def cache_age_sec(self, asset: str) -> float | None:
        """Age of the cached mid for ``asset``, or None when uncached (WHI-819)."""
        asset_key = asset.upper()
        cached = self._cache.get(asset_key)
        if cached is None:
            return None
        cached_at, _result = cached
        return max(0.0, self._clock() - cached_at)

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

        # WHI-799 §3.3 v3 / WHI-881: one mid per stock underlying (all forms share).
        if is_stock_asset(asset) or asset in STOCK_PERP_UNDERLYINGS:
            return await self._try_stock_chain(asset)

        # Crypto blue chips (CRYPTO_BLUE_CHIPS) and Others: §3.2 priority chain.
        return await self._try_crypto_chain(asset)

    async def _try_stock_chain(self, asset: str) -> _SourceResult:
        """Underlying-first stock mid (WHI-799 §3.3.1).

        P0 ``cex_tradfi_index`` → P1 ``proxy_perp_mark_median`` → P2 tokenized
        CEX spot TOB in fixed order from ``mid.stock_mid_p2_order``.
        SPCX (and any underlying without a perp form) falls through to P2 only
        (WHI-799 §3.3.2).
        """
        from spread_compare.assets import get_form

        errors: list[str] = []
        # P0/P1 when catalog has a perp form (live or unverified) or known
        # equity-perp underlyings not yet in the Phase-1 catalog rows.
        has_equity_ref = (
            get_form(asset, "perp") is not None or asset in STOCK_PERP_UNDERLYINGS
        )

        if has_equity_ref:
            try:
                result = await self._try_cex_tradfi_index(asset)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"cex_tradfi_index: {exc}")
                result = None
            if result is not None:
                return result
            try:
                result = await self._try_proxy_mark_median(
                    asset, mid_source="proxy_perp_mark_median"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"proxy_perp_mark_median: {exc}")
                result = None
            if result is not None:
                return result

        # P2: fixed form×venue order (not dynamic depth ranking).
        for step in self._settings.stock_mid_p2_order:
            try:
                result = await self._try_stock_p2_tob(asset, step)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"p2 {step.form}@{step.venue}: {exc}")
                result = None
            if result is not None:
                if asset == "SPCX":
                    detail = list(result.sources_detail or [])
                    tag = "private_underlying_no_equity_ref"
                    if tag not in detail:
                        detail.append(tag)
                    result = _SourceResult(
                        result.mid,
                        result.mid_source,
                        result.timestamp,
                        sources_detail=detail,
                    )
                return result

        err_detail = "; ".join(errors) if errors else "all stock mid sources empty"
        raise MidResolutionError(
            f"no mid for stock underlying {asset}: {err_detail}"
        )

    async def _try_stock_p2_tob(
        self, asset: str, step: StockMidP2Step
    ) -> _SourceResult | None:
        """Tokenized CEX spot TOB for one P2 step (form-aware wire symbol)."""
        if step.venue == "binance":
            return await self._try_binance_spot_tob(asset, form=step.form)
        if step.venue == "bybit":
            return await self._try_bybit_spot_tob(asset, form=step.form)
        logger.debug("unknown stock P2 venue %s for %s", step.venue, asset)
        return None

    async def _try_crypto_chain(self, asset: str) -> _SourceResult:
        chain: list[FetchFn] = [
            lambda: self._try_binance_usdm_index(asset),
            lambda: self._try_binance_spot_tob(asset),
            lambda: self._try_bybit_spot_tob(asset),
            lambda: self._try_pyth(asset),
        ]
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
        # Equity index path: stock underlyings use form=perp wire symbols.
        form = "perp" if is_stock_asset(asset) else None
        symbol = resolve_cex_symbol(asset, "perp", form=form, venue="binance")
        if symbol is None:
            return None
        mult = resolve_cex_multiplier(asset, "perp", form=form)
        url = f"{_BINANCE_FAPI}/fapi/v1/premiumIndex"
        try:
            resp = await self._http().get(url, params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            price = _parse_decimal(data["indexPrice"], field="indexPrice")
            if mult != 1:
                price = price / mult
            ts = _ms_to_dt(data.get("time"))
            return _SourceResult(price, "binance_usdm_index", ts)
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("binance_usdm_index failed for %s: %s", asset, exc)
            return None

    async def _try_binance_spot_tob(
        self, asset: str, *, form: str | None = None
    ) -> _SourceResult | None:
        symbol = resolve_cex_symbol(asset, "spot", form=form, venue="binance")
        if symbol is None:
            return None
        mult = resolve_cex_multiplier(asset, "spot", form=form)
        url = f"{_BINANCE_SPOT}/api/v3/ticker/bookTicker"
        try:
            resp = await self._http().get(url, params={"symbol": symbol})
            resp.raise_for_status()
            data = resp.json()
            bid = _parse_decimal(data["bidPrice"], field="bidPrice")
            ask = _parse_decimal(data["askPrice"], field="askPrice")
            mid = (bid + ask) / Decimal("2")
            if mult != 1:
                mid = mid / mult
            return _SourceResult(mid, "binance_spot_tob", datetime.now(tz=UTC))
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("binance_spot_tob failed for %s form=%s: %s", asset, form, exc)
            return None

    async def _try_bybit_spot_tob(
        self, asset: str, *, form: str | None = None
    ) -> _SourceResult | None:
        symbol = resolve_cex_symbol(asset, "spot", form=form, venue="bybit")
        if symbol is None:
            return None
        mult = resolve_cex_multiplier(asset, "spot", form=form)
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
            if mult != 1:
                mid = mid / mult
            return _SourceResult(mid, "bybit_spot_tob", datetime.now(tz=UTC))
        except (httpx.HTTPError, KeyError, TypeError, MidResolutionError) as exc:
            logger.debug("bybit_spot_tob failed for %s form=%s: %s", asset, form, exc)
            return None

    async def _try_pyth(self, asset: str) -> _SourceResult | None:
        feed_id = self._settings.pyth_feed_ids.get(asset)
        if not feed_id:
            return None
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

    async def _try_cex_tradfi_index(self, asset: str) -> _SourceResult | None:
        """Best-effort CEX TradFi index via Binance premiumIndex when listed.

        WHI-799 §3.3 prefers this over mark median. Many equity tickers are not
        on USDT-M; returns None and the caller falls through to median.
        """
        result = await self._try_binance_usdm_index(asset)
        if result is None:
            return None
        return _SourceResult(
            result.mid,
            "cex_tradfi_index",
            result.timestamp,
            sources_detail=["binance_usdm_index"],
        )

    async def _try_proxy_mark_median(
        self,
        asset: str,
        *,
        mid_source: MidSource = "proxy_perp_mark_median",
    ) -> _SourceResult | None:
        try:
            samples = list(await self._marks().marks_for(asset))
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
            mid_source,
            datetime.now(tz=UTC),
            sources_detail=labels,
        )


