"""KyberSwap prop-AMM adapters for Tessera on Base / BSC (WHI-806 / WHI-797 §7).

Source id is all-lowercase ``tessera`` (≠ venue slug). Gas comes from the
route response (``gasUsd``) — no separate gas-price call.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any, ClassVar, Final, Literal

import httpx

from spread_compare.adapters._prop_common import (
    BASE_TOKENS,
    BSC_TOKENS,
    PropFill,
    PropNoQuoteError,
    TokenInfo,
    build_non_ok_quote,
    exact_in_prop_quote,
    require_mid_match,
)
from spread_compare.adapters.base import (
    AdapterConfigError,
    AdapterError,
    AdapterFetchError,
    AdapterRateLimitedError,
    AdapterTimeoutError,
    BaseAdapter,
    default_instrument_type,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.budget import would_exceed_budget
from spread_compare.models import (
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.ratelimit import AsyncRateLimiter, acquire_within_budget

logger = logging.getLogger(__name__)

KYBER_BASE_URL: Final[str] = "https://aggregator-api.kyberswap.com"
_SOURCE_ID: Final[str] = "tessera"
_CLIENT_ID: Final[str] = "spread-comparison-tools"
# WHI-797 §7.2: far looser than Jupiter; keep a polite client floor.
_MIN_INTERVAL_S: Final[float] = 0.1
_MAX_RETRIES: Final[int] = 3

_SMOKE_BASE_IN = BASE_TOKENS["ETH"]
_SMOKE_BASE_OUT = BASE_TOKENS["USDC"]
_SMOKE_BASE_AMOUNT = 10**15  # 0.001 WETH
_SMOKE_BSC_IN = BSC_TOKENS["BTC"]
_SMOKE_BSC_OUT = BSC_TOKENS["USDT"]
_SMOKE_BSC_AMOUNT = 10**15  # 0.001 BTCB

_kyber_limiter = AsyncRateLimiter(_MIN_INTERVAL_S)


class KyberSwapPropAdapter(BaseAdapter):
    """Base class for KyberSwap ``includedSources=tessera`` venues."""

    venue: str
    venue_class: VenueClass = "prop_amm"
    chain_slug: ClassVar[str]  # "base" | "bsc"
    tokens: ClassVar[dict[str, TokenInfo]]
    quote_asset: ClassVar[str]  # "USDC" or "USDT"
    supported: ClassVar[tuple[str, ...]]

    def __init__(self, *, timeout: float | None = None) -> None:
        super().__init__(**({} if timeout is None else {"timeout": timeout}))
        self._smoke_ok = False

    async def startup(self) -> None:
        if self._started and self._smoke_ok:
            return
        await super().startup()
        await self._startup_smoke()
        self._smoke_ok = True

    async def aclose(self) -> None:
        self._smoke_ok = False
        await super().aclose()

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]:
        _ = instrument_type
        return list(self.supported)

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        _ = asset, mid, instrument_type
        return None

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
        _ = fee_tier
        itype: InstrumentType = instrument_type or default_instrument_type(self.venue_class)
        asset_key = asset.upper()

        if asset_key not in self.supported or asset_key not in self.tokens:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="unsupported_asset",
                error_code="unsupported_asset",
                error_message=f"{asset_key} not supported on {self.venue} (KyberSwap prop)",
            )

        require_mid_match(mid, asset_key)
        if notional_usd <= 0:
            raise AdapterError(f"notional_usd must be positive, got {notional_usd}")

        async def fetch(token_in: str, token_out: str, amount: int) -> PropFill:
            summary = await self._fetch_route(token_in, token_out, amount)
            try:
                in_raw = int(summary["amountIn"])
                out_raw = int(summary["amountOut"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterFetchError(
                    f"{self.venue}: invalid KyberSwap routeSummary: {exc}"
                ) from exc
            self._assert_route_exchange(summary)
            # Missing gasUsd → gas_unknown (WHI-799 §5.2); never silent zero.
            return PropFill(
                amount_in=in_raw,
                amount_out=out_raw,
                gas_usd=_parse_gas_usd(summary),
            )

        return await exact_in_prop_quote(
            venue=self.venue,
            mid=mid,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            instrument_type=itype,
            base=self.tokens[asset_key],
            quote_tok=self.tokens[self.quote_asset],
            fee_tier=_SOURCE_ID,
            fetch=fetch,
            provider_label="KyberSwap",
            gas_unknown_when_missing=True,
        )

    def _assert_route_exchange(self, summary: dict[str, Any]) -> None:
        """Every hop must be tessera (WHI-797 §7.2 isolation)."""
        route = summary.get("route")
        if not isinstance(route, list) or not route:
            raise AdapterFetchError(f"{self.venue}: KyberSwap route missing")
        for path in route:
            if not isinstance(path, list):
                continue
            for hop in path:
                if not isinstance(hop, dict):
                    continue
                exchange = str(hop.get("exchange") or "").lower()
                if exchange != _SOURCE_ID:
                    raise AdapterFetchError(
                        f"{self.venue}: hop exchange {exchange!r} != {_SOURCE_ID!r} "
                        f"(includedSources filter not isolated)"
                    )

    async def _startup_smoke(self) -> None:
        """One known-good pair per chain to catch source-id drift (WHI-797 §7.3)."""
        if self.chain_slug == "base":
            token_in, token_out, amount = (
                _SMOKE_BASE_IN.address,
                _SMOKE_BASE_OUT.address,
                _SMOKE_BASE_AMOUNT,
            )
        else:
            token_in, token_out, amount = (
                _SMOKE_BSC_IN.address,
                _SMOKE_BSC_OUT.address,
                _SMOKE_BSC_AMOUNT,
            )
        try:
            await self._fetch_route(token_in, token_out, amount)
        except AdapterConfigError:
            # 40011 = source-id drift / venue absent — fail-fast (WHI-797 §7.3).
            raise
        except PropNoQuoteError as exc:
            # 4008/4000 on the smoke pair is a temporary empty book, not config drift
            # (WHI-797 §7.4: no route is a normal business state). Do not brick app boot.
            logger.warning(
                "%s KyberSwap startup smoke: no route on known-good pair "
                "(chain=%s): %s — continuing; quotes may return no_quote",
                self.venue,
                self.chain_slug,
                exc,
            )
        except AdapterError as exc:
            logger.warning(
                "%s KyberSwap startup smoke transport/upstream failure: %s — continuing",
                self.venue,
                exc,
            )

    async def _fetch_route(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> dict[str, Any]:
        """GET /{chain}/api/v1/routes with includedSources=tessera."""
        # Prefer all-lowercase addresses (accepted by Kyber; mixed-case needs EIP-55).
        url = (
            f"{KYBER_BASE_URL.rstrip('/')}/"
            f"{self.chain_slug}/api/v1/routes"
        )
        params = {
            "tokenIn": token_in.lower(),
            "tokenOut": token_out.lower(),
            "amountIn": str(amount_in),
            "includedSources": _SOURCE_ID,
        }
        headers = {
            "Accept": "application/json",
            "x-client-id": _CLIENT_ID,
        }

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await acquire_within_budget(_kyber_limiter, venue=self.venue)
            try:
                resp = await self.http.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(
                    f"{self.venue}: KyberSwap route timed out"
                ) from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(
                    f"{self.venue}: KyberSwap transport error: {exc}"
                ) from exc

            if resp.status_code == 429:
                wait = min(2.0 * (2**attempt), 8.0)
                logger.warning(
                    "%s KyberSwap 429 attempt=%s sleep=%.1fs",
                    self.venue,
                    attempt + 1,
                    wait,
                )
                if would_exceed_budget(wait):
                    raise AdapterRateLimitedError(
                        f"{self.venue}: KyberSwap rate limited; retry_after="
                        f"{wait:.1f}s exceeds remaining quote budget",
                        retry_after_s=wait,
                    )
                await asyncio.sleep(wait)
                last_err = AdapterRateLimitedError(
                    f"{self.venue}: KyberSwap rate limited",
                    retry_after_s=wait,
                )
                continue

            try:
                body = resp.json()
            except ValueError as exc:
                raise AdapterFetchError(
                    f"{self.venue}: KyberSwap non-JSON response HTTP {resp.status_code}"
                ) from exc

            if not isinstance(body, dict):
                raise AdapterFetchError(f"{self.venue}: KyberSwap body not an object")

            code = body.get("code")
            message = str(body.get("message") or "")

            if code == 0:
                data = body.get("data") or {}
                if not isinstance(data, dict):
                    raise AdapterFetchError(f"{self.venue}: KyberSwap data not an object")
                summary = data.get("routeSummary")
                if not isinstance(summary, dict):
                    raise AdapterFetchError(
                        f"{self.venue}: KyberSwap missing routeSummary"
                    )
                return summary

            if code == 4008:
                raise PropNoQuoteError(
                    f"{self.venue}: route not found (code=4008)", code="4008"
                )

            if code == 40011:
                raise AdapterConfigError(
                    f"{self.venue}: KyberSwap filtered liquidity sources (code=40011) — "
                    f"bad source id or venue absent on chain={self.chain_slug!r} "
                    f"(message={message!r})"
                )

            if code == 4000:
                # WHI-799 §4.4: token not in source registry → unsupported_asset.
                raise PropNoQuoteError(
                    f"{self.venue}: bad request / token not registered (code=4000): "
                    f"{message}",
                    code="4000",
                )

            if resp.status_code >= 500:
                wait = min(2.0 * (2**attempt), 8.0)
                if would_exceed_budget(wait):
                    raise AdapterRateLimitedError(
                        f"{self.venue}: KyberSwap 5xx backoff {wait:.1f}s exceeds "
                        f"remaining quote budget",
                        retry_after_s=wait,
                    )
                await asyncio.sleep(wait)
                last_err = AdapterFetchError(
                    f"{self.venue}: KyberSwap HTTP {resp.status_code}"
                )
                continue

            if resp.status_code >= 400:
                raise AdapterFetchError(
                    f"{self.venue}: KyberSwap HTTP {resp.status_code} code={code} "
                    f"message={message!r}"
                )

            raise AdapterFetchError(
                f"{self.venue}: KyberSwap unexpected code={code} message={message!r}"
            )

        raise last_err or AdapterFetchError(f"{self.venue}: KyberSwap route failed")


def _parse_gas_usd(summary: dict[str, Any]) -> Decimal | None:
    """Extract gasUsd from routeSummary; None if missing/unparseable."""
    raw = summary.get("gasUsd")
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None
    if value < 0:
        return None
    return value


@register_adapter
class TesseraBaseAdapter(KyberSwapPropAdapter):
    """Tessera on Base via KyberSwap ``includedSources=tessera``."""

    venue: str = "tessera_base"
    chain_slug: ClassVar[str] = "base"
    tokens: ClassVar[dict[str, TokenInfo]] = BASE_TOKENS
    quote_asset: ClassVar[str] = "USDC"
    supported: ClassVar[tuple[str, ...]] = ("ETH", "BTC", "AERO", "VIRTUAL", "EURC")


@register_adapter
class TesseraBscAdapter(KyberSwapPropAdapter):
    """Tessera on BSC via KyberSwap ``includedSources=tessera``."""

    venue: str = "tessera_bsc"
    chain_slug: ClassVar[str] = "bsc"
    tokens: ClassVar[dict[str, TokenInfo]] = BSC_TOKENS
    quote_asset: ClassVar[str] = "USDT"
    supported: ClassVar[tuple[str, ...]] = ("BTC", "QQQB", "SPCXB", "NVDAB", "NVDAON")
