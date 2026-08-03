"""Shared EVM AMM quoter helpers (WHI-804).

Uses raw JSON-RPC over ``httpx.AsyncClient`` + ``eth_abi`` (no web3 dependency).
Underscore-prefixed so adapter auto-discovery skips this module.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal

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
from spread_compare.models import (
    FeeBreakdown,
    FeeSchedule,
    InstrumentType,
    QtyMethod,
    Quote,
    QuoteStatus,
    ReferenceMid,
    Side,
    TopOfBook,
    VenueClass,
)

# Uniswap V3 / PancakeSwap V3 QuoterV2 (struct form).
_SIG_QUOTE_EXACT_IN_SINGLE = "quoteExactInputSingle((address,address,uint256,uint24,uint160))"
_SIG_QUOTE_EXACT_OUT_SINGLE = "quoteExactOutputSingle((address,address,uint256,uint24,uint160))"
# Aerodrome MixedQuoter (IMixedRouteQuoterV1).
_SIG_AERO_V3 = "quoteExactInputSingleV3((address,address,uint256,int24,uint160))"
_SIG_AERO_V2 = "quoteExactInputSingleV2((address,address,bool,uint256))"
# Aerodrome Router V2-style getAmountsOut.
_SIG_GET_AMOUNTS_OUT = "getAmountsOut(uint256,(address,address,bool,address)[])"

SEL_QUOTE_EXACT_IN_SINGLE: Final[bytes] = function_signature_to_4byte_selector(
    _SIG_QUOTE_EXACT_IN_SINGLE
)
SEL_QUOTE_EXACT_OUT_SINGLE: Final[bytes] = function_signature_to_4byte_selector(
    _SIG_QUOTE_EXACT_OUT_SINGLE
)
SEL_AERO_V3: Final[bytes] = function_signature_to_4byte_selector(_SIG_AERO_V3)
SEL_AERO_V2: Final[bytes] = function_signature_to_4byte_selector(_SIG_AERO_V2)
SEL_GET_AMOUNTS_OUT: Final[bytes] = function_signature_to_4byte_selector(_SIG_GET_AMOUNTS_OUT)

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

    def __init__(self, message: str, *, transport: bool = False) -> None:
        super().__init__(message)
        self.transport = transport


class RpcClient:
    """Minimal async JSON-RPC client for eth_call / eth_gasPrice."""

    def __init__(self, http: httpx.AsyncClient, url: str) -> None:
        self._http = http
        self._url = url
        self._next_id = 1

    async def call(self, method: str, params: list[Any]) -> Any:
        req_id = self._next_id
        self._next_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        try:
            response = await self._http.post(self._url, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JsonRpcError(
                f"{method} transport failed: {exc}", transport=True
            ) from exc
        if "error" in body and body["error"]:
            err = body["error"]
            raise JsonRpcError(f"{method} error: {err}", transport=False)
        return body.get("result")

    async def eth_call(self, to: str, data: bytes) -> bytes:
        result = await self.call(
            "eth_call",
            [{"to": to_checksum_address(to), "data": "0x" + data.hex()}, "latest"],
        )
        if not isinstance(result, str) or not result.startswith("0x"):
            raise JsonRpcError(f"eth_call returned unexpected result: {result!r}")
        raw = bytes.fromhex(result[2:])
        if not raw:
            raise JsonRpcError("eth_call returned empty data")
        return raw

    async def eth_gas_price(self) -> int:
        result = await self.call("eth_gasPrice", [])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise JsonRpcError(f"eth_gasPrice unexpected: {result!r}")
        return int(result, 16)


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
    """Probe Uniswap-family QuoterV2 fee tiers; return the best executable quote.

    Sell: ExactIn base → quote. Buy: ExactOut base ← quote.
    Transport/RPC outage (no successful eth_call) raises AdapterFetchError so the
    adapter can map to status=error (WHI-799 §6.6). Per-tier reverts stay no_quote.
    """
    best: QuoterResult | None = None
    saw_success = False
    transport_failures = 0
    revert_failures = 0

    if amount_base_raw is None or amount_base_raw <= 0:
        return None

    async def _try_call(data: bytes) -> tuple[int, int] | None:
        nonlocal saw_success, transport_failures, revert_failures
        try:
            raw = await rpc.eth_call(quoter, data)
            saw_success = True
            amount, _, _, gas_est = decode_quoter_v2_result(raw)
            return amount, gas_est
        except JsonRpcError as exc:
            if exc.transport:
                transport_failures += 1
            else:
                revert_failures += 1
            return None
        except ValueError:
            revert_failures += 1
            return None

    if side == "sell":
        for fee in fee_tiers:
            data = encode_quote_exact_input_single(
                token_base, token_quote, amount_base_raw, fee
            )
            got = await _try_call(data)
            if got is None:
                continue
            amount_out, gas_est = got
            if amount_out <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_base_raw,
                amount_out=amount_out,
                gas_estimate=gas_est,
                fee_label=f"pool_{fee}",
                lp_fee_tier_bps=fee_to_lp_bps(fee),
                exact_out=False,
            )
            best = prefer_quoter_result(best, candidate, prefer_min_in=False)
    else:
        for fee in fee_tiers:
            data = encode_quote_exact_output_single(
                token_quote, token_base, amount_base_raw, fee
            )
            got = await _try_call(data)
            if got is None:
                continue
            amount_in, gas_est = got
            if amount_in <= 0:
                continue
            candidate = QuoterResult(
                amount_in=amount_in,
                amount_out=amount_base_raw,
                gas_estimate=gas_est,
                fee_label=f"pool_{fee}",
                lp_fee_tier_bps=fee_to_lp_bps(fee),
                exact_out=True,
            )
            best = prefer_quoter_result(best, candidate, prefer_min_in=True)

    if best is None and not saw_success and transport_failures > 0:
        raise AdapterFetchError(
            f"RPC transport failed for all fee tiers on {quoter} "
            f"(transport={transport_failures}, reverts={revert_failures})"
        )
    return best


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
) -> Quote:
    """Build an ok Quote with embedded LP fees and shared cost formulas."""
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
    )


class AmmDexAdapter(BaseAdapter):
    """Base class for on-chain AMM DEX adapters (Uniswap / Aerodrome / Pancake)."""

    venue: str
    venue_class: VenueClass = "amm_dex"
    rpc_env: str
    native_binance_symbol: str  # ETHUSDT or BNBUSDT
    supported: tuple[str, ...] = ("BTC", "ETH")
    # Venue-specific Uniswap-style fee tiers for get_fees(); override per adapter.
    lp_fee_tiers: tuple[int, ...] = ()

    def __init__(self, *, timeout: float = 10.0) -> None:
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
            self._rpc = RpcClient(self.http, self._rpc_url)
        return self._rpc

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
        itype: InstrumentType = instrument_type or default_instrument_type(self.venue_class)
        lp_tiers = [fee_to_lp_bps(f) for f in self.lp_fee_tiers] or None
        return FeeSchedule(
            venue=self.venue,
            asset=asset,
            instrument_type=itype,
            maker_bps=None,
            taker_bps=None,
            default_tier="pool",
            lp_fee_tiers_bps=lp_tiers,
            funding_model="none",
            fee_embedded_in_quote=True,
            source_urls=[],
            updated_at=datetime.now(tz=UTC),
        )

    async def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        """AMM venues have no orderbook concept (WHI-799 §7)."""
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
            result = await self._quote_best(asset_key, side, notional_usd, mid)
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

        base = self._base_token(asset_key)
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

    def _base_token(self, asset: str) -> TokenInfo:
        raise NotImplementedError

    def _quote_token(self) -> TokenInfo:
        raise NotImplementedError

    async def _quote_best(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        mid: ReferenceMid,
    ) -> QuoterResult | None:
        raise NotImplementedError
