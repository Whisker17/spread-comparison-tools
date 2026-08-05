"""Jupiter prop-AMM adapters for Solana (WHI-806 / WHI-797 / WHI-836).

Three venue instances share one Quote API client pattern, filtered by
``dexes=<exact Jupiter label>``. Labels are case-sensitive and validated at
startup against ``/program-id-to-label`` (wrong labels look like empty markets).

Rate budget is a process-wide :class:`TokenBucketRateLimiter` sized from
``config/jupiter.yaml`` (and optionally refined from response headers).
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, ClassVar, Final, Literal

import httpx

from spread_compare.adapters._prop_common import (
    SOL_MINTS,
    PropFill,
    PropNoQuoteError,
    build_non_ok_quote,
    exact_in_prop_quote,
    optional_env,
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
from spread_compare.budget import acquire_within_budget, sleep_within_budget
from spread_compare.impact import fraction_to_impact_bps
from spread_compare.models import (
    InstrumentType,
    Quote,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.ratelimit import TokenBucketRateLimiter
from spread_compare.settings import JupiterSettings, load_jupiter_settings
from spread_compare.upstream_events import record_rate_limit

logger = logging.getLogger(__name__)

# Abstracted base URL — Metis v1 is in maintenance; Swap V2 migration expected.
# Non-secret: override via env only for staging/migration; not a secret (AGENTS.md).
JUPITER_BASE_URL: Final[str] = "https://api.jup.ag/swap/v1"
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
_jupiter_limiter: TokenBucketRateLimiter | None = None
_jupiter_limiter_keyed: bool | None = None
# One program-id-to-label fetch serves all three Solana prop adapters.
_label_map_cache: dict[str, str] | None = None
# Loop-local locks (asyncio.Lock cannot cross event loops / TestClient).
_meta_lock: asyncio.Lock | None = None
_meta_loop: asyncio.AbstractEventLoop | None = None


def _reset_jupiter_limiter_for_tests() -> None:
    """Test helper: drop the shared limiter + label cache so tests start clean."""
    global _jupiter_limiter, _jupiter_limiter_keyed, _label_map_cache
    global _meta_lock, _meta_loop
    _jupiter_limiter = None
    _jupiter_limiter_keyed = None
    _label_map_cache = None
    _meta_lock = None
    _meta_loop = None


def _get_meta_lock() -> asyncio.Lock:
    """Return an asyncio.Lock bound to the current event loop."""
    global _meta_lock, _meta_loop
    loop = asyncio.get_running_loop()
    if _meta_lock is None or _meta_loop is not loop:
        _meta_lock = asyncio.Lock()
        _meta_loop = loop
    return _meta_lock


def _capacity_for(*, has_api_key: bool, settings: JupiterSettings) -> int:
    return settings.keyed_capacity if has_api_key else settings.keyless_capacity


async def _get_jupiter_limiter(*, has_api_key: bool) -> TokenBucketRateLimiter:
    """Return the process-wide Jupiter token-bucket limiter (created on first use).

    Capacity is chosen from the strictest mode seen: once any keyless caller
    has been observed, keep the keyless capacity even if a later caller has a key.
    """
    global _jupiter_limiter, _jupiter_limiter_keyed
    settings = load_jupiter_settings()
    async with _get_meta_lock():
        if _jupiter_limiter is None:
            capacity = _capacity_for(has_api_key=has_api_key, settings=settings)
            _jupiter_limiter = TokenBucketRateLimiter(
                capacity=capacity,
                window_s=settings.window_sec,
            )
            _jupiter_limiter_keyed = has_api_key
        elif not has_api_key and _jupiter_limiter_keyed and _jupiter_limiter is not None:
            # Downgrade to keyless capacity without inventing extra tokens.
            _jupiter_limiter.set_capacity(settings.keyless_capacity)
            _jupiter_limiter_keyed = False
        return _jupiter_limiter


def _observe_rate_limit_headers(
    resp: httpx.Response,
    limiter: TokenBucketRateLimiter,
    *,
    venue: str,
    has_api_key: bool,
) -> None:
    """Log rate-limit headers and optionally sync the bucket (never logs the API key).

    Capacity adaptation is keyed-only: WHI-836 header measurements were taken
    under the keyed plan. Keyless responses still log headers for observability
    but do not raise the local token balance (avoids no-op limiter on a longer
    keyless window).
    """
    remaining_raw = resp.headers.get("x-ratelimit-remaining")
    current_raw = resp.headers.get("x-ratelimit-current")
    reset_raw = resp.headers.get("x-ratelimit-reset")
    if remaining_raw is None and current_raw is None and reset_raw is None:
        return
    logger.info(
        "%s Jupiter rate-limit headers remaining=%s current=%s reset=%s",
        venue,
        remaining_raw,
        current_raw,
        reset_raw,
    )
    settings = load_jupiter_settings()
    if not settings.adapt_from_headers or not has_api_key:
        return
    try:
        remaining = int(remaining_raw) if remaining_raw is not None else None
        current = int(current_raw) if current_raw is not None else None
    except ValueError:
        return
    if remaining is not None and current is not None:
        limiter.observe_window(remaining=remaining, current=current)
    elif remaining is not None:
        limiter.observe_remaining(remaining)


def jupiter_base_url() -> str:
    """Jupiter Metis v1 base; optional env override for migration only."""
    return optional_env("JUPITER_BASE_URL") or JUPITER_BASE_URL


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
        super().__init__(**({} if timeout is None else {"timeout": timeout}))
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

        async def fetch(token_in: str, token_out: str, amount: int) -> PropFill:
            body = await self._fetch_quote(token_in, token_out, amount)
            try:
                in_raw = int(body["inAmount"])
                out_raw = int(body["outAmount"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterFetchError(
                    f"{self.venue}: invalid Jupiter quote body: {exc}"
                ) from exc
            self._assert_route_labels(body)
            impact_bps = _parse_jupiter_price_impact_bps(body)
            # Solana tx fees fixed at 0 (WHI-799 §8) — gas_usd left None with gas_unknown=False.
            return PropFill(
                amount_in=in_raw,
                amount_out=out_raw,
                gas_usd=None,
                price_impact_bps=impact_bps,
            )

        return await exact_in_prop_quote(
            venue=self.venue,
            mid=mid,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            instrument_type=itype,
            base=SOL_MINTS[asset_key],
            quote_tok=SOL_MINTS["USDC"],
            fee_tier=self.jupiter_label,
            fetch=fetch,
            provider_label="Jupiter",
            gas_unknown_when_missing=False,
        )

    def _assert_route_labels(self, body: dict[str, Any]) -> None:
        """Every hop must carry the requested dex label (WHI-797 §4.3 isolation)."""
        plan = body.get("routePlan")
        if not isinstance(plan, list) or not plan:
            raise AdapterFetchError(f"{self.venue}: Jupiter quote missing routePlan")
        for hop in plan:
            if not isinstance(hop, dict):
                continue
            info = hop.get("swapInfo") or {}
            label = info.get("label") if isinstance(info, dict) else None
            if label != self.jupiter_label:
                raise AdapterFetchError(
                    f"{self.venue}: route hop label {label!r} != requested "
                    f"{self.jupiter_label!r} (dexes filter not isolated)"
                )

    async def _validate_label(self) -> None:
        """Fail fast if Jupiter no longer maps our program_id to jupiter_label.

        Wrong label after a successful map fetch is fatal (config). Transport
        failure is logged and non-fatal so a Jupiter blip cannot brick the whole
        app lifespan (WHI-799 §6.6 per-venue degradation).
        """
        try:
            mapping = await self._load_label_map()
        except AdapterError as exc:
            logger.warning(
                "%s Jupiter label map unavailable at startup: %s — continuing; "
                "quotes may return NO_ROUTES_FOUND if the label is wrong",
                self.venue,
                exc,
            )
            return
        actual = mapping.get(self.program_id)
        if actual != self.jupiter_label:
            # Config/code bug — must fail boot, not degrade (WHI-840).
            raise AdapterConfigError(
                f"{self.venue}: Jupiter label validation failed — expected "
                f"program_id={self.program_id!r} → label={self.jupiter_label!r}, "
                f"got label={actual!r}. Wrong labels are indistinguishable from "
                f"empty markets at quote time (NO_ROUTES_FOUND)."
            )

    async def _load_label_map(self) -> dict[str, str]:
        """Fetch /program-id-to-label once; share across Solana prop adapters."""
        global _label_map_cache
        if _label_map_cache is not None:
            return _label_map_cache

        # Resolve limiter outside the meta lock (asyncio.Lock is not reentrant).
        limiter = await _get_jupiter_limiter(has_api_key=bool(self._api_key))
        async with _get_meta_lock():
            if _label_map_cache is not None:
                return _label_map_cache

            url = f"{jupiter_base_url().rstrip('/')}/program-id-to-label"
            headers = self._headers()
            await acquire_within_budget(limiter, venue=self.venue)
            try:
                resp = await self.http.get(url, headers=headers)
                _observe_rate_limit_headers(
                    resp, limiter, venue=self.venue, has_api_key=bool(self._api_key)
                )
                if resp.status_code == 429:
                    record_rate_limit("jupiter")
                    wait = _retry_after_seconds(resp, 0)
                    logger.warning(
                        "%s label-map rate limited; sleep=%.2fs", self.venue, wait
                    )
                    await sleep_within_budget(
                        wait, venue=self.venue, reason="Jupiter rate limited"
                    )
                    await acquire_within_budget(limiter, venue=self.venue)
                    resp = await self.http.get(url, headers=headers)
                    _observe_rate_limit_headers(
                        resp, limiter, venue=self.venue, has_api_key=bool(self._api_key)
                    )
                resp.raise_for_status()
                raw: Any = resp.json()
            except AdapterRateLimitedError:
                raise
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                raise AdapterFetchError(
                    f"{self.venue}: failed to fetch Jupiter program-id-to-label: {exc}"
                ) from exc

            if not isinstance(raw, dict):
                raise AdapterFetchError(
                    f"{self.venue}: program-id-to-label returned non-object"
                )
            # Coerce values to str for stable lookup.
            mapping = {str(k): str(v) for k, v in raw.items()}
            _label_map_cache = mapping
            return mapping

    async def _fetch_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
    ) -> dict[str, Any]:
        """GET /quote with rate limit + 429 backoff. Raises on config errors."""
        params: dict[str, str | int] = {
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
            await acquire_within_budget(limiter, venue=self.venue)
            try:
                resp = await self.http.get(url, params=params, headers=headers)
            except httpx.TimeoutException as exc:
                raise AdapterTimeoutError(f"{self.venue}: Jupiter quote timed out") from exc
            except httpx.HTTPError as exc:
                raise AdapterFetchError(f"{self.venue}: Jupiter transport error: {exc}") from exc

            _observe_rate_limit_headers(
                resp, limiter, venue=self.venue, has_api_key=bool(self._api_key)
            )

            if resp.status_code == 429:
                record_rate_limit("jupiter")
                wait = _retry_after_seconds(resp, attempt)
                remaining_hdr = resp.headers.get("x-ratelimit-remaining")
                logger.warning(
                    "%s rate limited (429) attempt=%s sleep=%.2fs remaining=%s",
                    self.venue,
                    attempt + 1,
                    wait,
                    remaining_hdr,
                )
                await sleep_within_budget(
                    wait, venue=self.venue, reason="Jupiter rate limited"
                )
                last_err = AdapterRateLimitedError(
                    f"{self.venue}: Jupiter rate limited",
                    retry_after_s=wait,
                )
                continue

            if resp.status_code == 400:
                return self._handle_400(resp)

            if resp.status_code >= 500:
                wait = min(2.0 * (2**attempt), 8.0)
                logger.warning(
                    "%s Jupiter 5xx=%s attempt=%s sleep=%.1fs",
                    self.venue,
                    resp.status_code,
                    attempt + 1,
                    wait,
                )
                # 5xx is not rate_limited (WHI-799 §6.6 / WHI-844) — keep sleeping
                # under asyncio.timeout; do not reclassify as rate_limited.
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
            raise AdapterConfigError(
                f"{self.venue}: Jupiter config error — {error_text} "
                f"(do not set dexes and excludeDexes together)"
            )

        if error_code == "NO_ROUTES_FOUND" or "No routes found" in error_text:
            raise PropNoQuoteError(
                f"{self.venue}: no routes for {self.jupiter_label} "
                f"({error_code or error_text})",
                code="NO_ROUTES_FOUND",
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


def _parse_jupiter_price_impact_bps(body: dict[str, Any]) -> Decimal | None:
    """Parse Jupiter ``priceImpactPct`` (unit fraction) into bps (WHI-845).

    Missing or unparseable values return None so ``build_ok_quote`` falls back
    to mid-relative ``|spread_bps|``.
    """
    raw = body.get("priceImpactPct")
    if raw is None or raw == "":
        return None
    try:
        return fraction_to_impact_bps(raw)
    except (ArithmeticError, ValueError, TypeError):
        return None


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
            delta = float(reset) - time.time()
            if 0 < delta < 120:
                return float(delta)
        except ValueError:
            pass
    return float(min(2.0 * (2**attempt), 30.0))


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
