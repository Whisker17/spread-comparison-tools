"""PancakeSwap v3 on BSC via on-chain QuoterV2 (WHI-804 / WHI-826 / WHI-881 / WHI-891).

Quote leg is USDT on BSC. Single-venue semantics only — no 0x/1inch.
Phase 1: fixed v3 fee-tier probe (skip Smart Router / multi-hop).

Stock underlyings resolve to tokenized tickers by form (WHI-881 / WHI-891):
QQQ/bstock→QQQB, SPCX/bstock→SPCXB, NVDA/bstock→NVDAB, NVDA/ondo→NVDAON,
plus Phase-A bStocks SPY/AAPL/TSLA/MSFT/GOOGL/META/AMZN (WHI-890 §8).
Token addresses keyed by ticker in ``BSC_TOKENS`` (shared SSOT with Tessera).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from spread_compare.adapters._amm_common import (
    PANCAKE_FEE_TIERS,
    AmmDexAdapter,
    QuoterResult,
    TokenInfo,
    probe_quoter_v2,
    to_raw,
)
from spread_compare.adapters._prop_common import BSC_STOCK_FORM_TICKER, BSC_TOKENS
from spread_compare.adapters.registry import register_adapter
from spread_compare.models import ReferenceMid, Side

# QuoterV2 (BSC).
# Verified 2026-08-03 against PancakeSwap developer docs:
# https://developer.pancakeswap.finance/contracts/v3/addresses
# Matches WHI-800 §5.3.
_QUOTER_V2 = "0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997"

# Bridged ETH on BSC (not in prop BSC table): WHI-798 §3.2.
_ETH = TokenInfo("0x2170Ed0880ac9A755fd29B2688956BD959F933F8", 18, "ETH")
# BSC_TOKENS is the address SSOT; ETH is the only Pancake-local override.
# Stock underlyings resolve form → ticker via BSC_STOCK_FORM_TICKER, then here.
_TOKEN_BY_TICKER: Final[dict[str, TokenInfo]] = {**BSC_TOKENS, "ETH": _ETH}
_USDT = BSC_TOKENS["USDT"]


@register_adapter
class PancakeSwapBscAdapter(AmmDexAdapter):
    """PancakeSwap (BSC) QuoterV2 adapter — fee-tier probe, ExactIn/ExactOut."""

    venue: str = "pancakeswap_bsc"
    rpc_env: str = "BSC_RPC_URL"
    native_binance_symbol: str = "BNBUSDT"
    # Underlyings (WHI-881 / WHI-891); crypto form=null, stocks require form.
    supported: tuple[str, ...] = (
        "BTC",
        "ETH",
        "QQQ",
        "SPCX",
        "NVDA",
        "SPY",
        "AAPL",
        "TSLA",
        "MSFT",
        "GOOGL",
        "META",
        "AMZN",
    )
    lp_fee_tiers: tuple[int, ...] = PANCAKE_FEE_TIERS

    def _base_token(self, asset: str, *, form: str | None = None) -> TokenInfo:
        ticker = self._token_ticker(asset, form=form)
        return _TOKEN_BY_TICKER[ticker]

    def _token_ticker(self, asset: str, *, form: str | None = None) -> str:
        key = asset.upper()
        if key in ("BTC", "ETH"):
            return key
        if form is None:
            raise ValueError(f"{key} requires form on {self.venue}")
        ticker = BSC_STOCK_FORM_TICKER.get((key, form.lower()))
        if ticker is None or ticker not in _TOKEN_BY_TICKER:
            raise ValueError(f"{key} form={form!r} has no PancakeSwap BSC token")
        return ticker

    def _quote_token(self) -> TokenInfo:
        return _USDT

    async def _quote_best(
        self,
        asset: str,
        side: Side,
        notional_usd: Decimal,
        mid: ReferenceMid,
        *,
        form: str | None = None,
    ) -> QuoterResult | None:
        base = self._base_token(asset, form=form)
        quote = self._quote_token()
        q_star = notional_usd / mid.mid
        amount_base = to_raw(q_star, base.decimals)
        return await probe_quoter_v2(
            self._require_rpc(),
            _QUOTER_V2,
            token_base=base.address,
            token_quote=quote.address,
            amount_base_raw=amount_base,
            fee_tiers=self.lp_fee_tiers,
            side=side,
        )
