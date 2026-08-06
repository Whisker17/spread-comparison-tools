"""Shared EVM AMM quoter helpers (WHI-804).

Uses raw JSON-RPC over ``httpx.AsyncClient`` + ``eth_abi`` (no web3 dependency).
Underscore-prefixed so adapter auto-discovery skips this module.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal
from urllib.parse import urlparse

import httpx
from eth_abi.abi import decode, encode
from eth_utils.abi import function_signature_to_4byte_selector
from eth_utils.address import to_checksum_address

from spread_compare.adapters.base import (
    AdapterError,
    AdapterFetchError,
    BaseAdapter,
    default_instrument_type,
)
from spread_compare.costs import spread_bps as calc_spread_bps
from spread_compare.costs import total_cost_bps
from spread_compare.impact import apply_impact_threshold, derive_price_impact_bps
from spread_compare.models import (
    FeeBreakdown,
    InstrumentType,
    QtyMethod,
    Quote,
    QuoteStatus,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)
from spread_compare.ratelimit import TokenBucketRateLimiter
from spread_compare.settings import RpcChainBudget, load_rpc_settings
from spread_compare.upstream_events import record_rate_limit

logger = logging.getLogger(__name__)

# Uniswap V3 / PancakeSwap V3 QuoterV2 (struct form).
_SIG_QUOTE_EXACT_IN_SINGLE = "quoteExactInputSingle((address,address,uint256,uint24,uint160))"
_SIG_QUOTE_EXACT_OUT_SINGLE = "quoteExactOutputSingle((address,address,uint256,uint24,uint160))"
# Aerodrome MixedQuoter (IMixedRouteQuoterV1).
_SIG_AERO_V3 = "quoteExactInputSingleV3((address,address,uint256,int24,uint160))"
_SIG_AERO_V2 = "quoteExactInputSingleV2((address,address,bool,uint256))"
# Aerodrome Router V2-style getAmountsOut.
_SIG_GET_AMOUNTS_OUT = "getAmountsOut(uint256,(address,address,bool,address)[])"
# Multicall3 aggregate3 — per-call success flags so one revert does not poison the batch.
_SIG_AGGREGATE3 = "aggregate3((address,bool,bytes)[])"

SEL_QUOTE_EXACT_IN_SINGLE: Final[bytes] = function_signature_to_4byte_selector(
    _SIG_QUOTE_EXACT_IN_SINGLE
)
SEL_QUOTE_EXACT_OUT_SINGLE: Final[bytes] = function_signature_to_4byte_selector(
    _SIG_QUOTE_EXACT_OUT_SINGLE
)
SEL_AERO_V3: Final[bytes] = function_signature_to_4byte_selector(_SIG_AERO_V3)
SEL_AERO_V2: Final[bytes] = function_signature_to_4byte_selector(_SIG_AERO_V2)
SEL_GET_AMOUNTS_OUT: Final[bytes] = function_signature_to_4byte_selector(_SIG_GET_AMOUNTS_OUT)
SEL_AGGREGATE3: Final[bytes] = function_signature_to_4byte_selector(_SIG_AGGREGATE3)

# Multicall3 CREATE2 address — identical on Ethereum, Base, and BSC (and 100+ chains).
# Verified 2026-08-04:
# - Deployments list: https://www.multicall3.com/deployments
# - Ethereum: https://etherscan.io/address/0xcA11bde05977b3631167028862bE2a173976CA11
# - Base: https://basescan.org/address/0xcA11bde05977b3631167028862bE2a173976CA11
# - BSC: https://bscscan.com/address/0xcA11bde05977b3631167028862bE2a173976CA11
MULTICALL3_ADDRESS: Final[str] = "0xcA11bde05977b3631167028862bE2a173976CA11"

# Fee tier probes (Uniswap fee units = 1e-6). Source: WHI-800 §5.1 / §5.3 (2026-08-03).
UNISWAP_FEE_TIERS: Final[tuple[int, ...]] = (100, 500, 3000, 10000)
# PancakeSwap v3 defaults include 2500 (0.25%); WHI-800 §5.3 bStocks note (2026-08-03).
PANCAKE_FEE_TIERS: Final[tuple[int, ...]] = (100, 500, 2500, 10000)
# Aerodrome CL tick spacings for Base blue-chip pools (WHI-800 §5.2 CL example uses 100;
# 1/50/100/200 are the standard Slipstream spacings — 2026-08-03).
AERO_TICK_SPACINGS: Final[tuple[int, ...]] = (1, 50, 100, 200)

_BINANCE_BOOK_TICKER = "https://api.binance.com/api/v3/ticker/bookTicker"
_WEI: Final[Decimal] = Decimal(10) ** 18


@dataclass(frozen=True, slots=True)
class TokenInfo:
    """On-chain token metadata for a logical asset or quote leg."""

    address: str
    decimals: int
    symbol: str


@dataclass(frozen=True, slots=True)
class QuoterResult:
    """Best executable quoter outcome for one side."""

    amount_in: int
    amount_out: int
    gas_estimate: int | None
    fee_label: str
    lp_fee_tier_bps: Decimal | None
    exact_out: bool


def fee_to_lp_bps(fee: int) -> Decimal:
    """Convert Uniswap/PCS fee units (1e-6) to basis points."""
    return Decimal(fee) / Decimal(100)


def to_raw(amount: Decimal, decimals: int) -> int:
    """Scale a human amount to integer token units (floor)."""
    scale = Decimal(10) ** decimals
    return int(amount * scale)


def from_raw(raw: int, decimals: int) -> Decimal:
    """Scale integer token units to a Decimal human amount."""
    return Decimal(raw) / (Decimal(10) ** decimals)

_DOTENV_LOADED = False


def load_dotenv_once() -> None:
    """Load repo-root ``.env`` into ``os.environ`` (idempotent)."""
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    from dotenv import load_dotenv

    load_dotenv()  # searches cwd and parents; no-op if file absent
    _DOTENV_LOADED = True


def require_env(name: str) -> str:
    """Return a non-empty env var or raise with a clear message.

    Loads ``.env`` once first so secrets declared there are visible
    (AGENTS.md runtime-configuration rule).
    """
    load_dotenv_once()
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"missing required env var {name} (set it in .env — see .env.example)"
        )
    return value


def encode_quote_exact_input_single(
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    sqrt_price_limit_x96: int = 0,
) -> bytes:
    """ABI-encode QuoterV2.quoteExactInputSingle."""
    params = (
        to_checksum_address(token_in),
        to_checksum_address(token_out),
        amount_in,
        fee,
        sqrt_price_limit_x96,
    )
    return SEL_QUOTE_EXACT_IN_SINGLE + encode(
        ["(address,address,uint256,uint24,uint160)"], [params]
    )


def encode_quote_exact_output_single(
    token_in: str,
    token_out: str,
    amount_out: int,
    fee: int,
    sqrt_price_limit_x96: int = 0,
) -> bytes:
    """ABI-encode QuoterV2.quoteExactOutputSingle."""
    params = (
        to_checksum_address(token_in),
        to_checksum_address(token_out),
        amount_out,
        fee,
        sqrt_price_limit_x96,
    )
    return SEL_QUOTE_EXACT_OUT_SINGLE + encode(
        ["(address,address,uint256,uint24,uint160)"], [params]
    )


def decode_quoter_v2_result(data: bytes) -> tuple[int, int, int, int]:
    """Decode (amount, sqrtPriceX96After, initializedTicksCrossed, gasEstimate)."""
    amount, sqrt_after, ticks, gas_est = decode(
        ["uint256", "uint160", "uint32", "uint256"], data
    )
    return int(amount), int(sqrt_after), int(ticks), int(gas_est)


def encode_aero_exact_in_v3(
    token_in: str,
    token_out: str,
    amount_in: int,
    tick_spacing: int,
    sqrt_price_limit_x96: int = 0,
) -> bytes:
    """ABI-encode MixedQuoter.quoteExactInputSingleV3."""
    params = (
        to_checksum_address(token_in),
        to_checksum_address(token_out),
        amount_in,
        tick_spacing,
        sqrt_price_limit_x96,
    )
    return SEL_AERO_V3 + encode(
        ["(address,address,uint256,int24,uint160)"], [params]
    )


def encode_aero_exact_in_v2(
    token_in: str,
    token_out: str,
    stable: bool,
    amount_in: int,
) -> bytes:
    """ABI-encode MixedQuoter.quoteExactInputSingleV2."""
    params = (
        to_checksum_address(token_in),
        to_checksum_address(token_out),
        stable,
        amount_in,
    )
    return SEL_AERO_V2 + encode(["(address,address,bool,uint256)"], [params])


def decode_aero_v2_amount(data: bytes) -> int:
    """Decode uint256 amountOut from quoteExactInputSingleV2."""
    (amount_out,) = decode(["uint256"], data)
    return int(amount_out)


def encode_get_amounts_out(
    amount_in: int,
    routes: list[tuple[str, str, bool, str]],
) -> bytes:
    """ABI-encode Router.getAmountsOut(uint256, Route[])."""
    encoded_routes = [
        (
            to_checksum_address(token_from),
            to_checksum_address(token_to),
            stable,
            to_checksum_address(factory),
        )
        for token_from, token_to, stable, factory in routes
    ]
    return SEL_GET_AMOUNTS_OUT + encode(
        ["uint256", "(address,address,bool,address)[]"],
        [amount_in, encoded_routes],
    )


def decode_get_amounts_out(data: bytes) -> list[int]:
    """Decode uint256[] from getAmountsOut."""
    (amounts,) = decode(["uint256[]"], data)
    return [int(a) for a in amounts]


def prefer_quoter_result(
    current: QuoterResult | None,
    candidate: QuoterResult,
    *,
    prefer_min_in: bool = False,
) -> QuoterResult:
    """Pick the better quoter result.

    ExactIn: higher amount_out wins. ExactOut: lower amount_in wins.
    When amounts tie (or for ExactIn when within the same amount), prefer a
    candidate that carries a gasEstimate so total_cost_bps can be filled.
    """
    if current is None:
        return candidate
    if prefer_min_in:
        if candidate.amount_in < current.amount_in:
            return candidate
        if candidate.amount_in > current.amount_in:
            return current
    else:
        if candidate.amount_out > current.amount_out:
            return candidate
        if candidate.amount_out < current.amount_out:
            return current
    # Amounts equal: prefer known gas.
    if candidate.gas_estimate is not None and current.gas_estimate is None:
        return candidate
    return current


class JsonRpcError(AdapterFetchError):
    """JSON-RPC eth_* call failed."""

    def __init__(
        self,
        message: str,
        *,
        transport: bool = False,
        revert: bool = False,
        rate_limited: bool = False,
    ) -> None:
        super().__init__(message)
        self.transport = transport
        self.revert = revert
        self.rate_limited = rate_limited


def is_rate_limited_error(exc: BaseException) -> bool:
    """True when the failure is an exhausted RPC rate limit (WHI-842)."""
    return isinstance(exc, JsonRpcError) and exc.rate_limited


def _is_execution_revert(err: object) -> bool:
    """True when the JSON-RPC error is a contract revert (pool miss / too deep)."""
    text = str(err).lower()
    if "execution reverted" in text or "revert" in text:
        return True
    if isinstance(err, dict):
        code = err.get("code")
        # eth_call reverts commonly surface as code 3 or -32000 with revert data.
        if code == 3:
            return True
        if code == -32000 and "revert" in text:
            return True
    return False


def _is_rpc_rate_limit_error(err: object) -> bool:
    """True when a JSON-RPC error body indicates provider rate limiting.

    Checked only after :func:`_is_execution_revert` is false. Message matching
    uses the dict ``message`` field (not the whole error string) so a revert
    reason that happens to contain digits like ``429`` is not misclassified.
    """
    if isinstance(err, dict):
        code = err.get("code")
        # Common provider codes for rate limit / capacity (Alchemy/Infura/etc.).
        if code in (-32005, -32016, 429):
            return True
        message = str(err.get("message") or "").lower()
        if "rate limit" in message or "too many requests" in message:
            return True
        return False
    text = str(err).lower()
    return "rate limit" in text or "too many requests" in text


def rpc_endpoint_label(url: str) -> str:
    """Host-only label for logs — never include path/query (may embed API keys)."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return "rpc"
    return host or "rpc"


def encode_multicall3_aggregate3(calls: Sequence[tuple[str, bytes]]) -> bytes:
    """ABI-encode Multicall3.aggregate3 with allowFailure=True per subcall."""
    encoded_calls = [
        (to_checksum_address(target), True, calldata)
        for target, calldata in calls
    ]
    return SEL_AGGREGATE3 + encode(
        ["(address,bool,bytes)[]"],
        [encoded_calls],
    )


def decode_multicall3_aggregate3(data: bytes) -> list[tuple[bool, bytes]]:
    """Decode Multicall3.aggregate3 → list of (success, returnData)."""
    (results,) = decode(["(bool,bytes)[]"], data)
    return [(bool(success), bytes(ret)) for success, ret in results]


@dataclass
class _EndpointState:
    """Shared per-URL limiter + gas-price cache (budget belongs to the endpoint)."""

    limiter: TokenBucketRateLimiter
    budget: RpcChainBudget
    gas_price_wei: int | None = None
    gas_price_mono: float = 0.0


_ENDPOINT_STATE: dict[str, _EndpointState] = {}


def _endpoint_state(url: str, budget: RpcChainBudget) -> _EndpointState:
    state = _ENDPOINT_STATE.get(url)
    if state is None:
        state = _EndpointState(
            limiter=TokenBucketRateLimiter(
                capacity=budget.rps,
                window_s=budget.window_sec,
            ),
            budget=budget,
        )
        _ENDPOINT_STATE[url] = state
        return state
    # Keep limiter capacity in sync if config was reloaded (tests).
    if (
        state.budget.rps != budget.rps
        or state.budget.window_sec != budget.window_sec
    ):
        state.limiter = TokenBucketRateLimiter(
            capacity=budget.rps,
            window_s=budget.window_sec,
        )
    state.budget = budget
    return state


def clear_rpc_endpoint_state() -> None:
    """Drop per-URL limiter/gas caches (tests)."""
    _ENDPOINT_STATE.clear()


def _retry_after_seconds(
    response: httpx.Response | None,
    attempt: int,
    *,
    start: float,
    max_wait: float,
    floor: float,
) -> float:
    """Backoff for 429; honour Retry-After when present, capped at max_wait."""
    if response is not None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                parsed = float(retry_after)
            except ValueError:
                pass
            else:
                wait = parsed if parsed > floor else floor
                return wait if wait < max_wait else max_wait
    wait = start * float(2**attempt)
    return wait if wait < max_wait else max_wait


def _log_rate_limit_headers(
    response: httpx.Response,
    *,
    host: str,
    method: str,
) -> None:
    """Log provider rate-limit signals without logging the full URL."""
    remaining = response.headers.get("x-ratelimit-remaining")
    limit = response.headers.get("x-ratelimit-limit")
    reset = response.headers.get("x-ratelimit-reset")
    retry_after = response.headers.get("retry-after")
    if remaining is None and limit is None and reset is None and retry_after is None:
        return
    # WARNING when actively rate-limited; routine headers stay DEBUG.
    level = logging.WARNING if response.status_code == 429 else logging.DEBUG
    logger.log(
        level,
        "rpc rate-limit signal host=%s method=%s remaining=%s limit=%s reset=%s "
        "retry_after=%s status=%s",
        host,
        method,
        remaining,
        limit,
        reset,
        retry_after,
        response.status_code,
    )


class RpcClient:
    """Async JSON-RPC client for eth_call / eth_gasPrice (WHI-804 / WHI-842).

    One limiter + gas cache per endpoint URL (shared across adapter instances).
    HTTP 429 and provider rate-limit JSON-RPC codes are retried with backoff;
    exhausted retries raise :class:`JsonRpcError` with ``rate_limited=True``.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        rpc_env: str = "",
        budget: RpcChainBudget | None = None,
    ) -> None:
        self._http = http
        self._url = url
        self._rpc_env = rpc_env
        self._host = rpc_endpoint_label(url)
        if budget is None:
            budget = load_rpc_settings().budget_for(rpc_env)
        self._budget = budget
        self._state = _endpoint_state(url, budget)
        self._next_id = 1

    @property
    def host(self) -> str:
        """Safe endpoint label for logs (never the raw URL)."""
        return self._host

    def _next_payload(self, method: str, params: list[Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

    def _parse_jsonrpc_body(self, body: object, *, method: str) -> Any:
        """Extract result from a single JSON-RPC object or raise JsonRpcError."""
        if not isinstance(body, dict):
            raise JsonRpcError(
                f"{method} transport failed: non-object response (host={self._host})",
                transport=True,
            )
        if body.get("error"):
            err = body["error"]
            if _is_execution_revert(err):
                raise JsonRpcError(
                    f"{method} error: {err}",
                    transport=False,
                    revert=True,
                )
            if _is_rpc_rate_limit_error(err):
                record_rate_limit("rpc")
                raise JsonRpcError(
                    f"{method} rate limited (rpc error) host={self._host}",
                    transport=True,
                    rate_limited=True,
                )
            raise JsonRpcError(
                f"{method} error: {err}",
                transport=True,
                revert=False,
            )
        return body.get("result")

    def _backoff_wait(
        self,
        response: httpx.Response | None,
        attempt: int,
    ) -> float:
        return _retry_after_seconds(
            response,
            attempt,
            start=self._budget.backoff_start_sec,
            max_wait=self._budget.backoff_max_sec,
            floor=self._budget.retry_after_floor_sec,
        )

    async def call(self, method: str, params: list[Any]) -> Any:
        """Single JSON-RPC method call with HTTP + body-level rate-limit retry."""
        last_rate_limited: JsonRpcError | None = None
        max_attempts = self._budget.max_attempts
        for attempt in range(max_attempts):
            payload = self._next_payload(method, params)
            response = await self._post_json(payload)
            try:
                body = response.json()
            except ValueError as exc:
                raise JsonRpcError(
                    f"{method} transport failed: invalid JSON (host={self._host})",
                    transport=True,
                ) from exc
            try:
                return self._parse_jsonrpc_body(body, method=method)
            except JsonRpcError as exc:
                if not exc.rate_limited:
                    raise
                wait = self._backoff_wait(response, attempt)
                last_rate_limited = JsonRpcError(
                    f"{method} rate limited (rpc error) host={self._host} "
                    f"attempt={attempt + 1}/{max_attempts}",
                    transport=True,
                    rate_limited=True,
                )
                logger.warning("%s", last_rate_limited)
                if attempt + 1 < max_attempts:
                    await _async_sleep(wait)
                    continue
                raise last_rate_limited from exc

        raise last_rate_limited or JsonRpcError(
            f"{method} failed with no response (host={self._host})",
            transport=True,
        )

    def _decode_eth_call_result(self, result: object) -> bytes:
        if not isinstance(result, str) or not result.startswith("0x"):
            raise JsonRpcError(f"eth_call returned unexpected result: {result!r}")
        raw = bytes.fromhex(result[2:])
        if not raw:
            raise JsonRpcError("eth_call returned empty data")
        return raw

    def _gas_cache_fresh(self) -> bool:
        ttl = self._budget.gas_price_cache_ttl_sec
        if ttl <= 0 or self._state.gas_price_wei is None:
            return False
        return (time.monotonic() - self._state.gas_price_mono) < ttl

    def _store_gas_price(self, result: object) -> int:
        if not isinstance(result, str) or not result.startswith("0x"):
            raise JsonRpcError(f"eth_gasPrice unexpected: {result!r}")
        price = int(result, 16)
        self._state.gas_price_wei = price
        self._state.gas_price_mono = time.monotonic()
        return price

    async def eth_call(self, to: str, data: bytes) -> bytes:
        result = await self.call(
            "eth_call",
            [{"to": to_checksum_address(to), "data": "0x" + data.hex()}, "latest"],
        )
        return self._decode_eth_call_result(result)

    async def _post_json(self, payload: Any) -> httpx.Response:
        """POST one JSON body (object or batch array) with rate limit + 429 retry."""
        last_rate_limited: JsonRpcError | None = None
        max_attempts = self._budget.max_attempts
        method_label = "batch" if isinstance(payload, list) else str(
            payload.get("method", "rpc") if isinstance(payload, dict) else "rpc"
        )
        for attempt in range(max_attempts):
            await self._state.limiter.acquire()
            try:
                response = await self._http.post(self._url, json=payload)
            except httpx.HTTPError as exc:
                raise JsonRpcError(
                    f"{method_label} transport failed: {type(exc).__name__} "
                    f"(host={self._host})",
                    transport=True,
                ) from exc

            _log_rate_limit_headers(response, host=self._host, method=method_label)

            if response.status_code == 429:
                record_rate_limit("rpc")
                wait = _retry_after_seconds(
                    response,
                    attempt,
                    start=self._budget.backoff_start_sec,
                    max_wait=self._budget.backoff_max_sec,
                    floor=self._budget.retry_after_floor_sec,
                )
                last_rate_limited = JsonRpcError(
                    f"{method_label} rate limited (HTTP 429) host={self._host} "
                    f"attempt={attempt + 1}/{max_attempts}",
                    transport=True,
                    rate_limited=True,
                )
                logger.warning("%s", last_rate_limited)
                if attempt + 1 < max_attempts:
                    await _async_sleep(wait)
                    continue
                raise last_rate_limited

            if response.status_code >= 400:
                raise JsonRpcError(
                    f"{method_label} transport failed: HTTP {response.status_code} "
                    f"(host={self._host})",
                    transport=True,
                )
            return response

        raise last_rate_limited or JsonRpcError(
            f"{method_label} failed with no response (host={self._host})",
            transport=True,
        )

    async def eth_call_many(
        self,
        calls: Sequence[tuple[str, bytes]],
        *,
        warm_gas_price: bool = True,
    ) -> list[tuple[bool, bytes | None]]:
        """Batch eth_calls via Multicall3.aggregate3 (one HTTP round-trip).

        Each entry is ``(success, return_data_or_None)``. A subcall revert
        yields ``(False, None)`` without failing the batch. Outer transport /
        rate-limit failures raise :class:`JsonRpcError`.

        When ``warm_gas_price`` is true and the endpoint gas cache is cold, the
        Multicall3 ``eth_call`` and ``eth_gasPrice`` share one JSON-RPC batch
        HTTP post so a full ``get_quote`` stays at one RPC round-trip.
        """
        if not calls:
            return []

        if len(calls) == 1:
            target, data = calls[0]
            try:
                raw = await self.eth_call(target, data)
            except JsonRpcError as exc:
                # Preserve accounting: only pure execution reverts become no_quote.
                if not exc.revert:
                    raise
                return [(False, None)]
            return [(True, raw)]

        encoded = encode_multicall3_aggregate3(calls)
        multicall_params: list[Any] = [
            {
                "to": to_checksum_address(MULTICALL3_ADDRESS),
                "data": "0x" + encoded.hex(),
            },
            "latest",
        ]
        fetch_gas = warm_gas_price and not self._gas_cache_fresh()

        if fetch_gas:
            raw = await self._eth_call_many_with_gas(multicall_params)
        else:
            raw = await self.eth_call(MULTICALL3_ADDRESS, encoded)

        try:
            decoded = decode_multicall3_aggregate3(raw)
        except ValueError as exc:
            raise JsonRpcError(
                f"Multicall3 decode failed (host={self._host}): {exc}",
                transport=True,
            ) from exc
        if len(decoded) != len(calls):
            raise JsonRpcError(
                f"Multicall3 result length mismatch: got {len(decoded)} "
                f"expected {len(calls)} (host={self._host})",
                transport=True,
            )
        out: list[tuple[bool, bytes | None]] = []
        for success, ret in decoded:
            if not success:
                out.append((False, None))
            elif not ret:
                out.append((True, b""))
            else:
                out.append((True, ret))
        return out

    async def _eth_call_many_with_gas(self, multicall_params: list[Any]) -> bytes:
        """Multicall3 eth_call + eth_gasPrice in one JSON-RPC batch (cold gas cache).

        Retries HTTP 429 via :meth:`_post_json` and body-level rate limits on the
        Multicall3 result with the same bounded backoff as :meth:`call`.
        """
        last_rate_limited: JsonRpcError | None = None
        max_attempts = self._budget.max_attempts
        for attempt in range(max_attempts):
            call_payload = self._next_payload("eth_call", multicall_params)
            gas_payload = self._next_payload("eth_gasPrice", [])
            call_id = call_payload["id"]
            gas_id = gas_payload["id"]
            response = await self._post_json([call_payload, gas_payload])
            try:
                bodies = response.json()
            except ValueError as exc:
                raise JsonRpcError(
                    f"batch transport failed: invalid JSON (host={self._host})",
                    transport=True,
                ) from exc
            if not isinstance(bodies, list) or len(bodies) < 2:
                raise JsonRpcError(
                    f"batch transport failed: expected array response "
                    f"(host={self._host})",
                    transport=True,
                )
            by_id: dict[Any, object] = {}
            for item in bodies:
                if isinstance(item, dict) and "id" in item:
                    by_id[item["id"]] = item
            call_body = by_id.get(call_id, bodies[0])
            gas_body = by_id.get(gas_id, bodies[1])
            try:
                call_result = self._parse_jsonrpc_body(call_body, method="eth_call")
            except JsonRpcError as exc:
                if not exc.rate_limited:
                    raise
                wait = self._backoff_wait(response, attempt)
                last_rate_limited = JsonRpcError(
                    f"eth_call rate limited (rpc error) host={self._host} "
                    f"attempt={attempt + 1}/{max_attempts}",
                    transport=True,
                    rate_limited=True,
                )
                logger.warning("%s", last_rate_limited)
                if attempt + 1 < max_attempts:
                    await _async_sleep(wait)
                    continue
                raise last_rate_limited from exc
            try:
                gas_result = self._parse_jsonrpc_body(gas_body, method="eth_gasPrice")
                self._store_gas_price(gas_result)
            except JsonRpcError as exc:
                # Gas is best-effort; probe results still usable (gas_unknown path).
                logger.debug(
                    "batched eth_gasPrice failed host=%s: %s", self._host, exc
                )
            return self._decode_eth_call_result(call_result)

        raise last_rate_limited or JsonRpcError(
            f"batch eth_call failed with no response (host={self._host})",
            transport=True,
        )

    async def eth_gas_price(self) -> int:
        if self._gas_cache_fresh() and self._state.gas_price_wei is not None:
            return self._state.gas_price_wei
        result = await self.call("eth_gasPrice", [])
        return self._store_gas_price(result)


async def _async_sleep(seconds: float) -> None:
    """Isolated for tests that monkeypatch sleep."""
    await asyncio.sleep(seconds)


# Probe outcome tags (WHI-836 / WHI-842). "ok" means the RPC path for that
# subcall succeeded (even if amount was zero or decode failed after transport OK).
ProbeKind = Literal["ok", "transport", "revert"]
ProbeOutcome = tuple[ProbeKind, QuoterResult | None]


def outcome_from_raw(
    success: bool,
    raw: bytes | None,
    *,
    decode_and_build: Callable[[bytes], QuoterResult | None],
) -> ProbeOutcome:
    """Shared Multicall3 subcall → probe outcome ladder (WHI-842).

    ``decode_and_build(raw)`` returns a :class:`QuoterResult` or ``None``
    (zero/empty), and may raise ``ValueError`` on decode failure (→ ok/None).
    """
    if not success:
        return "revert", None
    if raw is None or raw == b"":
        return "ok", None
    try:
        candidate = decode_and_build(raw)
    except ValueError:
        return "ok", None
    if candidate is None:
        return "ok", None
    return "ok", candidate


def reduce_probe_outcomes(
    outcomes: Sequence[ProbeOutcome],
    *,
    prefer_min_in: bool,
    error_label: str,
) -> QuoterResult | None:
    """Fold probe outcomes into best quote or AdapterFetchError.

    Transport-only total failure raises; any successful RPC path (even with
    zero/empty decode) degrades to ``no_quote`` (``None``) per WHI-799 §6.6.
    """
    best: QuoterResult | None = None
    saw_success = False
    transport_failures = 0
    revert_failures = 0
    for kind, candidate in outcomes:
        if kind == "ok":
            saw_success = True
            if candidate is not None:
                best = prefer_quoter_result(
                    best, candidate, prefer_min_in=prefer_min_in
                )
        elif kind == "transport":
            transport_failures += 1
        else:
            revert_failures += 1
    if best is None and not saw_success and transport_failures > 0:
        raise AdapterFetchError(
            f"RPC transport failed for all {error_label} "
            f"(transport={transport_failures}, reverts={revert_failures})"
        )
    return best


def _quoter_v2_outcome_from_raw(
    *,
    side: Side,
    fee: int,
    amount_base_raw: int,
    success: bool,
    raw: bytes | None,
) -> ProbeOutcome:
    """Map one Multicall3 subcall result to a probe outcome."""

    def _build(decoded_raw: bytes) -> QuoterResult | None:
        amount, _, _, gas_est = decode_quoter_v2_result(decoded_raw)
        if amount <= 0:
            return None
        if side == "sell":
            return QuoterResult(
                amount_in=amount_base_raw,
                amount_out=amount,
                gas_estimate=gas_est,
                fee_label=f"pool_{fee}",
                lp_fee_tier_bps=fee_to_lp_bps(fee),
                exact_out=False,
            )
        return QuoterResult(
            amount_in=amount,
            amount_out=amount_base_raw,
            gas_estimate=gas_est,
            fee_label=f"pool_{fee}",
            lp_fee_tier_bps=fee_to_lp_bps(fee),
            exact_out=True,
        )

    return outcome_from_raw(success, raw, decode_and_build=_build)


async def probe_quoter_v2(
    rpc: RpcClient,
    quoter: str,
    *,
    token_base: str,
    token_quote: str,
    amount_base_raw: int | None,
    fee_tiers: tuple[int, ...],
    side: Side,
) -> QuoterResult | None:
    """Probe Uniswap-family QuoterV2 fee tiers in one Multicall3 round-trip.

    Sell: ExactIn base → quote. Buy: ExactOut base ← quote.
    Transport/RPC outage (no successful eth_call) raises AdapterFetchError so the
    adapter can map to status=error (WHI-799 §6.6). Per-tier reverts stay no_quote.
    Fee tiers are batched via Multicall3.aggregate3 (WHI-842); rate-limit exhaustion
    propagates as :class:`JsonRpcError` with ``rate_limited=True``.
    """
    if amount_base_raw is None or amount_base_raw <= 0:
        return None

    calldatas: list[tuple[str, bytes]] = []
    for fee in fee_tiers:
        if side == "sell":
            data = encode_quote_exact_input_single(
                token_base, token_quote, amount_base_raw, fee
            )
        else:
            data = encode_quote_exact_output_single(
                token_quote, token_base, amount_base_raw, fee
            )
        calldatas.append((quoter, data))

    try:
        results = await rpc.eth_call_many(calldatas)
    except JsonRpcError as exc:
        if exc.rate_limited:
            raise
        # Entire batch transport failure — same accounting as all-transport.
        return reduce_probe_outcomes(
            [("transport", None)] * len(fee_tiers),
            prefer_min_in=side != "sell",
            error_label=f"fee tiers on {quoter}",
        )

    outcomes: list[ProbeOutcome] = []
    for fee, (success, raw) in zip(fee_tiers, results, strict=True):
        outcomes.append(
            _quoter_v2_outcome_from_raw(
                side=side,
                fee=fee,
                amount_base_raw=amount_base_raw,
                success=success,
                raw=raw,
            )
        )
    return reduce_probe_outcomes(
        outcomes,
        prefer_min_in=side != "sell",
        error_label=f"fee tiers on {quoter}",
    )


async def fetch_binance_mid(
    http: httpx.AsyncClient,
    symbol: str,
) -> Decimal | None:
    """Return (bid+ask)/2 for a Binance spot bookTicker, or None on failure."""
    try:
        response = await http.get(_BINANCE_BOOK_TICKER, params={"symbol": symbol})
        response.raise_for_status()
        body = response.json()
        bid = Decimal(str(body["bidPrice"]))
        ask = Decimal(str(body["askPrice"]))
        if bid <= 0 or ask <= 0:
            return None
        return (bid + ask) / Decimal(2)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None


async def estimate_gas_usd(
    rpc: RpcClient,
    http: httpx.AsyncClient,
    *,
    gas_estimate: int | None,
    native_binance_symbol: str,
) -> tuple[Decimal | None, bool]:
    """Return (gas_usd, gas_unknown).

    Formula (WHI-804 / WHI-799 §5.2): gasEstimate × eth_gasPrice × native USD.
    Any failure ⇒ gas_unknown=True and gas_usd=None (never silent 0).
    """
    if gas_estimate is None or gas_estimate <= 0:
        return None, True
    try:
        gas_price_wei = await rpc.eth_gas_price()
    except AdapterError:
        return None, True
    native_usd = await fetch_binance_mid(http, native_binance_symbol)
    if native_usd is None or native_usd <= 0:
        return None, True
    gas_eth = Decimal(gas_estimate) * Decimal(gas_price_wei) / _WEI
    return gas_eth * native_usd, False


def build_non_ok_quote(
    *,
    venue: str,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    status: QuoteStatus,
    error_code: str,
    error_message: str,
    venue_symbol: str | None = None,
    qty_method: QtyMethod | None = None,
) -> Quote:
    """Construct a non-ok Quote with WHI-799 §6.2 null invariants."""
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
        effective_price=None,
        spread_bps=None,
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            fee_tier=None,
            trading_fee_bps=None,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=None,
        ),
        total_cost_bps=None,
        timestamp=datetime.now(tz=UTC),
        status=status,
        qty_base=None,
        qty_method=qty_method,
        error_code=error_code,
        error_message=error_message,
    )


def build_ok_quote(
    *,
    venue: str,
    mid: ReferenceMid,
    asset: str,
    side: Side,
    notional_usd: Decimal,
    instrument_type: InstrumentType,
    effective_price: Decimal,
    qty_base: Decimal,
    qty_method: QtyMethod,
    fee_label: str,
    lp_fee_tier_bps: Decimal | None,
    gas_usd: Decimal | None,
    gas_unknown: bool,
    venue_symbol: str | None,
    price_impact_bps: Decimal | None = None,
) -> Quote:
    """Build an ok Quote with embedded LP fees and shared cost formulas.

    When ``price_impact_bps`` is omitted, mid-relative ``|spread_bps|`` is used
    as the impact diagnostic (WHI-845 — on-chain quoters / Kyber have no separate
    impact field). Jupiter callers pass the upstream-reported value instead.
    """
    sp = calc_spread_bps(side, effective_price, mid.mid)
    cost = total_cost_bps(
        sp,
        embedded_in_price=True,
        trading_fee_bps=None,
        platform_fee_bps=Decimal("0"),
        gas_unknown=gas_unknown,
        gas_usd=gas_usd,
        notional_usd=notional_usd,
    )
    impact = derive_price_impact_bps(price_impact_bps, sp)
    quote = Quote(
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
        effective_price=effective_price,
        spread_bps=sp,
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            fee_tier=fee_label,
            trading_fee_bps=None,
            platform_fee_bps=Decimal("0"),
            lp_fee_tier_bps=lp_fee_tier_bps,
            gas_usd=gas_usd,
            gas_bps=cost.gas_bps,
            gas_unknown=gas_unknown,
            explicit_fee_bps=cost.explicit_fee_bps,
        ),
        total_cost_bps=cost.total_cost_bps,
        timestamp=datetime.now(tz=UTC),
        status="ok",
        qty_base=qty_base,
        qty_method=qty_method,
        price_impact_bps=impact,
    )
    return apply_impact_threshold(quote)


class AmmDexAdapter(BaseAdapter):
    """Base class for on-chain AMM DEX adapters (Uniswap / Aerodrome / Pancake)."""

    venue: str
    venue_class: VenueClass = "amm_dex"
    rpc_env: str
    native_binance_symbol: str  # ETHUSDT or BNBUSDT
    supported: tuple[str, ...] = ("BTC", "ETH")
    # Venue-specific Uniswap-style fee tiers for quoter probes; keep in sync with
    # config/fees/<slug>.yaml lp_fee_tiers_bps (display). Override per adapter.
    lp_fee_tiers: tuple[int, ...] = ()

    def __init__(self, *, timeout: float | None = None) -> None:
        if timeout is None:
            super().__init__()
        else:
            super().__init__(timeout=timeout)
        self._rpc_url: str | None = None
        self._rpc: RpcClient | None = None

    async def startup(self) -> None:
        if self._started:
            return
        # Fail fast on missing RPC URL without opening a network client (BaseAdapter
        # keeps httpx lazy until first use).
        self._rpc_url = require_env(self.rpc_env)
        await super().startup()

    async def aclose(self) -> None:
        self._rpc = None
        self._rpc_url = None
        await super().aclose()

    def _require_rpc(self) -> RpcClient:
        if self._rpc_url is None:
            raise AdapterError(
                f"{self.venue}: adapter not started (call startup() first)"
            )
        if self._rpc is None:
            budget = load_rpc_settings().budget_for(self.rpc_env)
            self._rpc = RpcClient(
                self.http,
                self._rpc_url,
                rpc_env=self.rpc_env,
                budget=budget,
            )
        return self._rpc

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
        form: str | None = None,
    ) -> TopOfBook | None:
        """AMM venues have no orderbook concept (WHI-799 §7)."""
        _ = asset, mid, instrument_type, form
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
        form: str | None = None,
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
                error_message=f"{asset_key} not supported on {self.venue} (EVM AMM)",
            )

        if mid.asset.upper() != asset_key:
            raise AdapterError(
                f"mid.asset={mid.asset!r} does not match asset={asset!r}"
            )
        if mid.mid <= 0:
            raise AdapterError(f"mid must be positive, got {mid.mid}")
        if notional_usd <= 0:
            raise AdapterError(f"notional_usd must be positive, got {notional_usd}")

        try:
            base = self._base_token(asset_key, form=form)
        except (KeyError, ValueError) as exc:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="unsupported_asset",
                error_code="unsupported_asset",
                error_message=(
                    f"{asset_key} form={form!r} not supported on {self.venue}: {exc}"
                ),
            )

        try:
            result = await self._quote_best(
                asset_key, side, notional_usd, mid, form=form
            )
        except AdapterError as exc:
            # WHI-842/WHI-844: exhausted RPC 429 budget → status=rate_limited.
            if is_rate_limited_error(exc):
                return build_non_ok_quote(
                    venue=self.venue,
                    mid=mid,
                    asset=asset_key,
                    side=side,
                    notional_usd=notional_usd,
                    instrument_type=itype,
                    status="rate_limited",
                    error_code="rate_limited",
                    error_message=str(exc),
                )
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
            )

        if result is None:
            return build_non_ok_quote(
                venue=self.venue,
                mid=mid,
                asset=asset_key,
                side=side,
                notional_usd=notional_usd,
                instrument_type=itype,
                status="no_quote",
                error_code="no_quote",
                error_message=f"no executable pool quote for {asset_key} on {self.venue}",
            )

        quote = self._quote_token()
        if result.exact_out:
            # Buy ExactOut: amount_in=quote spent, amount_out=base received.
            base_amt = from_raw(result.amount_out, base.decimals)
            quote_amt = from_raw(result.amount_in, quote.decimals)
            qty_base = base_amt
            qty_method: QtyMethod = "base_from_mid"
        elif side == "sell":
            # Sell ExactIn: amount_in=base sold, amount_out=quote received.
            base_amt = from_raw(result.amount_in, base.decimals)
            quote_amt = from_raw(result.amount_out, quote.decimals)
            qty_base = base_amt
            qty_method = "base_from_mid"
        else:
            # Buy ExactIn approx on quote leg.
            base_amt = from_raw(result.amount_out, base.decimals)
            quote_amt = from_raw(result.amount_in, quote.decimals)
            qty_base = base_amt
            qty_method = "quote_exact_in_approx"

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
                error_message="quoter returned zero amount",
            )

        effective_price = quote_amt / base_amt
        gas_usd, gas_unknown = await estimate_gas_usd(
            self._require_rpc(),
            self.http,
            gas_estimate=result.gas_estimate,
            native_binance_symbol=self.native_binance_symbol,
        )
        return build_ok_quote(
            venue=self.venue,
            mid=mid,
            asset=asset_key,
            side=side,
            notional_usd=notional_usd,
            instrument_type=itype,
            effective_price=effective_price,
            qty_base=qty_base,
            qty_method=qty_method,
            fee_label=result.fee_label,
            lp_fee_tier_bps=result.lp_fee_tier_bps,
            gas_usd=gas_usd,
            gas_unknown=gas_unknown,
            venue_symbol=f"{base.symbol}/{quote.symbol}",
        )

    def _base_token(self, asset: str, *, form: str | None = None) -> TokenInfo:
        raise NotImplementedError

    def _quote_token(self) -> TokenInfo:
        raise NotImplementedError

    async def _quote_best(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        mid: ReferenceMid,
        *,
        form: str | None = None,
    ) -> QuoterResult | None:
        raise NotImplementedError
