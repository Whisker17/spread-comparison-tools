"""CEX logical-asset → venue-symbol map (WHI-798 §3.3).

Adapters resolve symbols only through this module — never hardcode pairs in
request paths. Extend here when new blue-chip or tokenized assets land.
"""

from __future__ import annotations

from typing import Final

# WHI-798 §3.3 / §3.2 CEX column: logical asset → Binance & Bybit USDT pair.
# Spot and USDT-M / linear perp share the same symbol string on both venues.
CEX_USDT_SYMBOLS: Final[dict[str, str]] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}


def resolve_cex_symbol(asset: str) -> str | None:
    """Return the CEX USDT symbol for ``asset``, or ``None`` if unsupported."""
    return CEX_USDT_SYMBOLS.get(asset.upper())


def supported_cex_assets() -> list[str]:
    """Sorted logical asset keys supported on CEX adapters."""
    return sorted(CEX_USDT_SYMBOLS)
