"""Jupiter prop-AMM adapters for Solana (WHI-806 / WHI-797).

Three venue instances share one Quote API client pattern, filtered by
``dexes=<exact Jupiter label>``. Labels are case-sensitive and validated at
startup against ``/program-id-to-label`` (wrong labels look like empty markets).
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, ClassVar, Final, Literal

import httpx

from spread_compare.adapters._perp_common import AsyncRateLimiter
from spread_compare.adapters._prop_common import (
    SOL_MINTS,
    build_non_ok_quote,
    build_ok_prop_quote,
    from_raw,
    optional_env,
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

# Abstracted base URL — Metis v1 is in maintenance; Swap V2 migration expected.
DEFAULT_JUPITER_BASE_URL: Final[str] = "https://api.jup.ag/swap/v1"
# Keyless plan is 0.5 RPS (burst ~5); safe default ≥2s spacing (WHI-797 §3.3).
_KEYLESS_MIN_INTERVAL_S: Final[float] = 2.0
# With an API key, Free plan is 1 RPS; still keep a small floor.
_KEYED_MIN_INTERVAL_S: Final[float] = 1.0
_MAX_RETRIES: Final[int] = 4
_DEFAULT_SLIPPAGE_BPS: Final[int] = 50

# Expected program IDs for startup label validation (WHI-797 §4.1).
_EXPECTED_PROGRAM_IDS: Final[dict[str, str]] = {
    "HumidiFi": "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp",
    "TesseraV": "TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH",
    "BisonFi": "BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi",
}

_SOLANA_ASSETS: Final[tuple[str, ...]] = ("SOL", "BTC", "ETH")

# Module-level limiter shared by all three Solana prop adapters (one upstream).
_jupiter_limiter: AsyncRateLimiter | None = None
_jupiter_limiter_lock = asyncio.Lock()


def _reset_jupiter_limiter_for_tests() -> None:
    """Test helper: drop the shared limiter so spacing tests start clean."""
    global _jupiter_limiter
    _jupiter_limiter = None


async def _get_jupiter_limiter(*, has_api_key: bool) -> AsyncRateLimiter:
    """Return the process-wide Jupiter rate limiter (created on first use)."""
    global _jupiter_limiter
    async with _jupiter_limiter_lock:
        if _jupiter_limiter is None:
            interval = _KEYED_MIN_INTERVAL_S if has_api_key else _KEYLESS_MIN_INTERVAL_S
            _jupiter_limiter = AsyncRateLimiter(interval)
        return _jupiter_limiter


def jupiter_base_url() -> str:
    """Configurable base URL (env ``JUPITER_BASE_URL``; default Metis v1)."""
    return optional_env("JUPITER_BASE_URL") or DEFAULT_JUPITER_BASE_URL


class JupiterPropAdapter(BaseAdapter):
    """Base class for Jupiter-filtered prop AMM venues on Solana."""

    venue: str
    venue_class: VenueClass = "prop_amm"
    jupiter_label: ClassVar[str]
    program_id: ClassVar[str]
    # Default single-market isolation; set False for same-venue multi-hop (WHI-797 §4.5).
    only_direct_routes: ClassVar[bool] = True
    supported: ClassVar[tuple[str, ...]] = _SOLANA_ASSETS

    def __init__(self, *, timeout: float | None = None) -> None:
        if timeout is None:
            super().__init__()
        else:
            super().__init__(timeout=timeout)
        self._labels_validated = False
        self._api_key: str | None = None

    async def startup(self) -> None:
        if self._started and self._labels_validated:
            return
        self._api_key = optional_env("JUPITER_API_KEY")
        await super().startup()
        await self._validate_label()
        self._labels_validated = True

    async def aclose(self) -> None:
        self._labels_validated = False
        self._api_key = None
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
        """Prop AMMs have no orderbook concept (WHI-799 §7)."""
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

        if asset_key not in self.supported:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="unsupported_asset",
                error_code="unsupported_asset",
                error_message=f"{asset_key} not supported on {self.venue} (Jupiter prop)",
            )

        require_mid_match(mid, asset_key)
        if notional_usd <= 0:
            raise AdapterError(f"notional_usd must be positive, got {notional_usd}")

        base = SOL_MINTS[asset_key]
        quote_tok = SOL_MINTS["USDC"]
        venue_symbol = f"{base.symbol}/{quote_tok.symbol}"

        if side == "sell":
            # ExactIn base → USDC.
            qty_base = notional_usd / mid.mid
            amount_in = to_raw(qty_base, base.decimals)
            input_mint, output_mint = base.address, quote_tok.address
            qty_method: QtyMethod = "base_from_mid"
        else:
            # Buy: ExactIn on quote leg (USDC → base); ExactOut unverified on prop AMMs.
            amount_in = to_raw(notional_usd, quote_tok.decimals)
            input_mint, output_mint = quote_tok.address, base.address
            qty_method = "quote_exact_in_approx"
            qty_base = Decimal("0")  # filled from response

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
            body = await self._fetch_quote(input_mint, output_mint, amount_in)
        except _NoRoutesError as exc:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code="NO_ROUTES_FOUND",
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
            in_raw = int(body["inAmount"])
            out_raw = int(body["outAmount"])
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
                error_message=f"invalid Jupiter quote body: {exc}",
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
                error_message="Jupiter returned zero amounts",
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
        # Solana tx fees are fixed at 0 bps (WHI-799 §8 / WHI-806) — not unknown.
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
            fee_tier=self.jupiter_label,
            gas_usd=None,
            gas_unknown=False,
            venue_symbol=venue_symbol,
        )

    async def _validate_label(self) -> None:
        """Fail fast if Jupiter no longer maps our program_id to jupiter_label."""
        url = f"{jupiter_base_url().rstrip('/')}/program-id-to-label"
        headers = self._headers()
        try:
            resp = await self.http.get(url, headers=headers)
            resp.raise_for_status()
            mapping: dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AdapterFetchError(
                f"{self.venue}: failed to fetch Jupiter program-id-to-label: {exc}"
            ) from exc

        if not isinstance(mapping, dict):
            raise AdapterFetchError(
                f"{self.venue}: program-id-to-label returned non-object"
            )

        # Map is program_id → label.
        actual = mapping.get(self.program_id)
        if actual != self.jupiter_label:
            # Also accept reverse map (label → program) if shape ever flips.
            reverse = {v: k for k, v in mapping.items() if isinstance(v, str)}
            prog_for_label = reverse.get(self.jupiter_label)
            if prog_for_label == self.program_id:
                return
            raise AdapterError(
                f"{self.venue}: Jupiter label validation failed — expected "
                f"program_id={self.program_id!r} → label={self.jupiter_label!r}, "
                f"got label={actual!r}. Wrong labels are indistinguishable from "
                f"empty markets at quote time (NO_ROUTES_FOUND)."
            )
        expected = _EXPECTED_PROGRAM_IDS.get(self.jupiter_label)
        if expected is not None and expected != self.program_id:
            raise AdapterError(
                f"{self.venue}: program_id {self.program_id!r} does not match "
                f"canonical {_EXPECTED_PROGRAM_IDS[self.jupiter_label]!r} for "
                f"label {self.jupiter_label!r}"
            )

    async def _fetch_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> dict[str, Any]:
        """GET /quote with rate limit + 429 backoff. Raises on config errors."""
        params: dict[str, str | int | bool] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount,
            "slippageBps": _DEFAULT_SLIPPAGE_BPS,
            "dexes": self.jupiter_label,
            "onlyDirectRoutes": "true" if self.only_direct_routes else "false",
            "swapMode": "ExactIn",
        }
        url = f"{jupiter_base_url().rstrip('/')}/quote"
        headers = self._headers()
        limiter = await _get_jupiter_limiter(has_api_key=bool(self._api_key))

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            await limiter.acquire()
            try:
                resp = await self.http.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"{self.venue}: Jupiter quote timed out") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"{self.venue}: Jupiter transport error: {exc}") from exc

            if resp.status_code == 429:
                wait = _retry_after_seconds(resp, attempt)
                logger.warning(
                    "%s rate limited (429) attempt=%s sleep=%.2fs remaining=%s",
                    self.venue,
                    attempt + 1,
                    wait,
                    resp.headers.get("x-ratelimit-remaining"),
                )
                await asyncio.sleep(wait)
                last_err = AdapterFetchError(f"{self.venue}: Jupiter rate limited")
                continue

            if resp.status_code == 400:
                return self._handle_400(resp)

            if resp.status_code >= 500:
                wait = min(2**attempt, 8.0)
                logger.warning(
                    "%s Jupiter 5xx=%s attempt=%s sleep=%.1fs",
                    self.venue,
                    resp.status_code,
                    attempt + 1,
                    wait,
                )
                await asyncio.sleep(wait)
                last_err = AdapterFetchError(
                    f"{self.venue}: Jupiter HTTP {resp.status_code}"
                )
                continue

            try:
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                raise AdapterFetchError(
                    f"{self.venue}: Jupiter response error: {exc}"
                ) from exc
            if not isinstance(body, dict):
                raise AdapterFetchError(f"{self.venue}: Jupiter quote not an object")
            return body

        raise last_err or AdapterFetchError(f"{self.venue}: Jupiter quote failed")

    def _handle_400(self, resp: httpx.Response) -> dict[str, Any]:
        """Map HTTP 400 body to no_quote vs config error (WHI-797 §8.2)."""
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        error_text = str(body.get("error") or body.get("message") or "")
        error_code = str(body.get("errorCode") or "")

        if "Cannot set dexes and exclude dexes at the same time" in error_text:
            # Programmer/config error — never swallow as empty quote.
            raise AdapterConfigError(
                f"{self.venue}: Jupiter config error — {error_text} "
                f"(do not set dexes and excludeDexes together)"
            )

        if error_code == "NO_ROUTES_FOUND" or "No routes found" in error_text:
            raise _NoRoutesError(
                f"{self.venue}: no routes for {self.jupiter_label} ({error_code or error_text})"
            )

        raise AdapterFetchError(
            f"{self.venue}: Jupiter HTTP 400: {error_text or body!r}"
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        key = self._api_key or optional_env("JUPITER_API_KEY")
        if key:
            headers["x-api-key"] = key
        return headers


class _NoRoutesError(Exception):
    """Internal: Jupiter returned NO_ROUTES_FOUND (business empty state)."""


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    """Backoff for 429; prefer ``x-ratelimit-reset`` / Retry-After when present."""
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return max(float(retry_after), 0.5)
        except ValueError:
            pass
    reset = resp.headers.get("x-ratelimit-reset")
    if reset:
        try:
            # Jupiter returns a unix timestamp for the window reset.
            delta = float(reset) - time.time()
            if 0 < delta < 120:
                return float(delta)
        except ValueError:
            pass
    # Exponential backoff floor: 2s, 4s, 8s, ...
    return float(min(2.0 * (2**attempt), 30.0))


# ---------------------------------------------------------------------------
# Registered venue instances
# ---------------------------------------------------------------------------


@register_adapter
class HumidiFiAdapter(JupiterPropAdapter):
    """HumidiFi via Jupiter ``dexes=HumidiFi``."""

    venue: str = "humidifi"
    jupiter_label: ClassVar[str] = "HumidiFi"
    program_id: ClassVar[str] = _EXPECTED_PROGRAM_IDS["HumidiFi"]


@register_adapter
class TesseraSolanaAdapter(JupiterPropAdapter):
    """Tessera (Solana) via Jupiter ``dexes=TesseraV`` (label ≠ slug)."""

    venue: str = "tessera_solana"
    jupiter_label: ClassVar[str] = "TesseraV"
    program_id: ClassVar[str] = _EXPECTED_PROGRAM_IDS["TesseraV"]


@register_adapter
class BisonFiAdapter(JupiterPropAdapter):
    """BisonFi via Jupiter ``dexes=BisonFi``."""

    venue: str = "bisonfi"
    jupiter_label: ClassVar[str] = "BisonFi"
    program_id: ClassVar[str] = _EXPECTED_PROGRAM_IDS["BisonFi"]
