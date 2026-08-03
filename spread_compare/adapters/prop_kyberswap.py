"""KyberSwap prop-AMM adapters for Tessera on Base / BSC (WHI-806 / WHI-797 §7).

Source id is all-lowercase ``tessera`` (≠ venue slug). Gas comes from the
route response (``gasUsd``) — no separate gas-price call.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, ClassVar, Final, Literal

import httpx

from spread_compare.adapters._prop_common import (
    BASE_TOKENS,
    BSC_TOKENS,
    TokenInfo,
    build_non_ok_quote,
    build_ok_prop_quote,
    from_raw,
    prop_fee_schedule,
    require_mid_match,
    to_raw,
)
from spread_compare.adapters.base import (
    AdapterConfigError,
    AdapterError,
    AdapterFetchError,
    AdapterTimeoutError,
    BaseAdapter,
    default_instrument_type,
)
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import (
    FeeSchedule,
    InstrumentType,
    QtyMethod,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)

logger = logging.getLogger(__name__)

DEFAULT_KYBER_BASE_URL: Final[str] = "https://aggregator-api.kyberswap.com"
_SOURCE_ID: Final[str] = "tessera"
_CLIENT_ID: Final[str] = "spread-comparison-tools"

# Startup smoke pairs (known-good; WHI-797 §7.4 / acceptance criteria).
_SMOKE_BASE_IN = BASE_TOKENS["ETH"]
_SMOKE_BASE_OUT = BASE_TOKENS["USDC"]
_SMOKE_BASE_AMOUNT = 10**15  # 0.001 WETH — small, cheap smoke
_SMOKE_BSC_IN = BSC_TOKENS["BTC"]
_SMOKE_BSC_OUT = BSC_TOKENS["USDT"]
_SMOKE_BSC_AMOUNT = 10**15  # 0.001 BTCB


class KyberSwapPropAdapter(BaseAdapter):
    """Base class for KyberSwap ``includedSources=tessera`` venues."""

    venue: str
    venue_class: VenueClass = "prop_amm"
    chain_slug: ClassVar[str]  # "base" | "bsc"
    tokens: ClassVar[dict[str, TokenInfo]]
    quote_asset: ClassVar[str]  # "USDC" or "USDT"
    supported: ClassVar[tuple[str, ...]]

    def __init__(self, *, timeout: float | None = None) -> None:
        if timeout is None:
            super().__init__()
        else:
            super().__init__(timeout=timeout)
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

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule:
        return prop_fee_schedule(
            self.venue,
            asset,
            instrument_type=instrument_type,
            venue_class=self.venue_class,
        )

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

        base = self.tokens[asset_key]
        quote_tok = self.tokens[self.quote_asset]
        venue_symbol = f"{base.symbol}/{quote_tok.symbol}"

        if side == "sell":
            qty_base = notional_usd / mid.mid
            amount_in = to_raw(qty_base, base.decimals)
            token_in, token_out = base.address, quote_tok.address
            qty_method: QtyMethod = "base_from_mid"
        else:
            # ExactIn on quote leg (USDC/USDT → base).
            amount_in = to_raw(notional_usd, quote_tok.decimals)
            token_in, token_out = quote_tok.address, base.address
            qty_method = "quote_exact_in_approx"
            qty_base = Decimal("0")

        if amount_in <= 0:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code="no_quote",
                error_message="computed input amount is zero",
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )

        try:
            summary = await self._fetch_route(token_in, token_out, amount_in)
        except _NoRouteError as exc:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code=exc.code,
                error_message=str(exc),
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )
        except AdapterConfigError:
            raise
        except AdapterError as exc:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="error",
                error_code="adapter_error",
                error_message=str(exc),
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )

        try:
            in_raw = int(summary["amountIn"])
            out_raw = int(summary["amountOut"])
        except (KeyError, TypeError, ValueError) as exc:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="error",
                error_code="parse_error",
                error_message=f"invalid KyberSwap routeSummary: {exc}",
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )

        if in_raw <= 0 or out_raw <= 0:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code="no_quote",
                error_message="KyberSwap returned zero amounts",
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )

        if side == "sell":
            base_amt = from_raw(in_raw, base.decimals)
            quote_amt = from_raw(out_raw, quote_tok.decimals)
            qty_base = base_amt
        else:
            quote_amt = from_raw(in_raw, quote_tok.decimals)
            base_amt = from_raw(out_raw, base.decimals)
            qty_base = base_amt

        if base_amt <= 0 or quote_amt <= 0:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code="no_quote",
                error_message="zero base/quote after scaling",
                venue_symbol=venue_symbol,
                qty_method=qty_method,
            )

        effective_price = quote_amt / base_amt
        gas_usd = _parse_gas_usd(summary)
        return build_ok_prop_quote(
            venue=self.venue,
            mid=mid,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            instrument_type=itype,
            effective_price=effective_price,
            qty_base=qty_base,
            qty_method=qty_method,
            fee_tier=_SOURCE_ID,
            gas_usd=gas_usd,
            gas_unknown=gas_usd is None,
            venue_symbol=venue_symbol,
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
        except _NoRouteError as exc:
            raise AdapterError(
                f"{self.venue}: KyberSwap startup smoke failed for known-good pair "
                f"on chain={self.chain_slug!r}: {exc}. Source id may have drifted "
                f"(expected includedSources={_SOURCE_ID!r})."
            ) from exc
        except AdapterError:
            raise

    async def _fetch_route(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
    ) -> dict[str, Any]:
        """GET /{chain}/api/v1/routes with includedSources=tessera."""
        # Prefer all-lowercase addresses (accepted by Kyber; mixed-case needs EIP-55).
        token_in_q = token_in.lower()
        token_out_q = token_out.lower()
        url = (
            f"{DEFAULT_KYBER_BASE_URL.rstrip('/')}/"
            f"{self.chain_slug}/api/v1/routes"
        )
        params = {
            "tokenIn": token_in_q,
            "tokenOut": token_out_q,
            "amountIn": str(amount_in),
            "includedSources": _SOURCE_ID,
        }
        headers = {
            "Accept": "application/json",
            "x-client-id": _CLIENT_ID,
        }
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

        # HTTP layer: Kyber often returns 200 with business code in body.
        if resp.status_code == 429:
            raise AdapterFetchError(f"{self.venue}: KyberSwap rate limited (HTTP 429)")

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
            raise _NoRouteError(
                f"{self.venue}: route not found (code=4008)", code="4008"
            )

        if code == 40011:
            raise AdapterConfigError(
                f"{self.venue}: KyberSwap filtered liquidity sources (code=40011) — "
                f"bad source id or venue absent on chain={self.chain_slug!r} "
                f"(message={message!r})"
            )

        if code == 4000:
            # Token not registered / bad address → treat as no_quote (business).
            raise _NoRouteError(
                f"{self.venue}: bad request / token not registered (code=4000): "
                f"{message}",
                code="4000",
            )

        if resp.status_code >= 400:
            raise AdapterFetchError(
                f"{self.venue}: KyberSwap HTTP {resp.status_code} code={code} "
                f"message={message!r}"
            )

        raise AdapterFetchError(
            f"{self.venue}: KyberSwap unexpected code={code} message={message!r}"
        )


class _NoRouteError(Exception):
    """Internal: KyberSwap business empty state (4008 / 4000)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


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
