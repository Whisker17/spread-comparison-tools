"""Collect symbols and start WS feeds + fast mid after adapter startup (WHI-847 / WHI-855).

Subscription set is the **product catalog / phase-1 assets that adapters actually
serve** — not the full venue universe (WHI-855). Reconnect must not re-subscribe
hundreds of unserved coins (quiet markets keep firing ``book_stale``).
"""

from __future__ import annotations

import logging
from typing import Any

from spread_compare.adapters.registry import get as get_adapter
from spread_compare.cex_symbols import resolve_cex_symbol, supported_cex_assets
from spread_compare.mids import MidService
from spread_compare.perp_symbols import (
    HL_PHASE1_ASSETS,
    resolve_apex_base,
    resolve_hl_coin,
    resolve_lighter_symbol,
)
from spread_compare.settings import WsSettings, load_ws_settings
from spread_compare.ws_feeds import WsFeedManager, set_ws_feed_manager
from spread_compare.ws_mid import FastMidPoller
from spread_compare.ws_registry import default_ws_registry

logger = logging.getLogger(__name__)

# Blue chips + high-volume others that section pages request often.
_FAST_MID_ASSETS = (
    "BTC",
    "ETH",
    "SOL",
    "DOGE",
    "WIF",
    "XRP",
    "SUI",
    "LINK",
    "AVAX",
    "ADA",
    "BNB",
)

# Phase-1 logical set shared across HL / Lighter / ApeX WS subscriptions.
# Includes PEPE/BONK multiplier infrastructure (not in assets.ASSETS).
# Named after the product surface, not one venue — HL_PHASE1_ASSETS is the
# shared constant in perp_symbols.py.
_WS_SERVED_PERP_ASSETS: tuple[str, ...] = HL_PHASE1_ASSETS


async def start_ws_ingest(
    mid_service: MidService,
    *,
    settings: WsSettings | None = None,
) -> tuple[WsFeedManager | None, FastMidPoller | None]:
    """Start multiplexed WS feeds. Never raises — degrades to REST on failure."""
    ws_settings = settings if settings is not None else load_ws_settings()
    if not ws_settings.enabled:
        logger.info("ws ingest disabled")
        set_ws_feed_manager(None)
        return None, None

    registry = default_ws_registry()
    registry.set_max_book_age_sec(ws_settings.max_book_age_sec)
    manager = WsFeedManager(ws_settings, registry=registry)

    binance_spot = _cex_symbols("spot")
    binance_fut = _cex_symbols("perp")
    bybit_spot = _cex_symbols("spot", exclude_bstocks=True)
    bybit_linear = _cex_symbols("perp")
    hl_coins = _hl_coins()
    lighter_markets = _lighter_markets()
    apex_symbols = _apex_cross_symbols()

    try:
        await manager.start(
            binance_spot_symbols=binance_spot,
            binance_futures_symbols=binance_fut,
            bybit_spot_symbols=bybit_spot,
            bybit_linear_symbols=bybit_linear,
            hyperliquid_coins=hl_coins,
            lighter_markets=lighter_markets,
            apex_symbols=apex_symbols,
        )
    except Exception:  # noqa: BLE001
        logger.exception("ws feed manager start failed; REST fallback only")
        set_ws_feed_manager(None)
        return None, None

    set_ws_feed_manager(manager)
    logger.info(
        "ws feeds started sockets=%s binance_spot=%s binance_fut=%s bybit_spot=%s "
        "bybit_linear=%s hl=%s lighter=%s apex=%s",
        manager.socket_count,
        len(binance_spot),
        len(binance_fut),
        len(bybit_spot),
        len(bybit_linear),
        len(hl_coins),
        len(lighter_markets),
        len(apex_symbols),
    )

    mid_poller: FastMidPoller | None = FastMidPoller(
        mid_service, _FAST_MID_ASSETS, ws_settings=ws_settings
    )
    try:
        assert mid_poller is not None
        mid_poller.start()
    except Exception:  # noqa: BLE001
        logger.exception("fast mid poller failed to start")
        mid_poller = None

    return manager, mid_poller


async def stop_ws_ingest(
    manager: WsFeedManager | None,
    mid_poller: FastMidPoller | None,
) -> None:
    if mid_poller is not None:
        await mid_poller.stop()
    if manager is not None:
        await manager.stop()
    set_ws_feed_manager(None)


def _cex_symbols(book_side: str, *, exclude_bstocks: bool = False) -> list[str]:
    from spread_compare.assets import TOKENIZED_CEX_SPOT

    out: list[str] = []
    for asset in supported_cex_assets(book_side):  # type: ignore[arg-type]
        # Bybit has no bStocks (*B); use catalog membership, not a hand list.
        if exclude_bstocks and asset in TOKENIZED_CEX_SPOT:
            continue
        sym = resolve_cex_symbol(asset, book_side)  # type: ignore[arg-type]
        if sym:
            out.append(sym)
    # Prefer blue chips first for connection subscribe order.
    priority = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    out = sorted(set(out), key=lambda s: (0 if s in priority else 1, s))
    return out


def _hl_coins() -> list[str]:
    """Hyperliquid coins for WS — phase-1 product set only (WHI-855).

    Previously used the adapter's full meta universe (300+ coins), so reconnect
    re-subscribed hundreds of markets the dashboard never quotes.
    """
    coins: list[str] = []
    for asset in _WS_SERVED_PERP_ASSETS:
        try:
            coins.append(resolve_hl_coin(asset).venue_symbol)
        except Exception:  # noqa: BLE001
            continue
    # Prefer blue chips first.
    priority = {"BTC", "ETH", "SOL"}
    return sorted(set(coins), key=lambda c: (0 if c in priority else 1, c))


def _lighter_markets() -> dict[str, str]:
    """market_id → symbol, scoped to phase-1 assets the product serves (WHI-855)."""
    wanted: set[str] = set()
    for asset in _WS_SERVED_PERP_ASSETS:
        try:
            wanted.add(resolve_lighter_symbol(asset).venue_symbol.upper())
        except Exception:  # noqa: BLE001
            continue

    adapter = _safe_adapter("lighter")
    markets: dict[str, str] = {}
    if adapter is not None:
        by_sym = getattr(adapter, "_markets_by_symbol", None)
        if isinstance(by_sym, dict):
            for symbol, meta in by_sym.items():
                sym_u = str(symbol).upper()
                if sym_u not in wanted:
                    continue
                mid = getattr(meta, "market_id", None)
                if mid is not None:
                    markets[str(mid)] = sym_u
            if markets:
                return markets
        # Fallback: market_id_for per phase-1 asset.
        for asset in _WS_SERVED_PERP_ASSETS:
            try:
                resolved = resolve_lighter_symbol(asset)
                market_id_for = getattr(adapter, "market_id_for", None)
                if not callable(market_id_for):
                    continue
                mid = market_id_for(asset)
                if mid is not None:
                    markets[str(mid)] = resolved.venue_symbol.upper()
            except Exception:  # noqa: BLE001
                continue
        if markets:
            return markets

    # No adapter / cold path: empty — REST fallback until adapter starts.
    return markets


def _apex_cross_symbols() -> list[str]:
    """ApeX crossSymbolName list for phase-1 assets only (WHI-855)."""
    wanted_bases: set[str] = set()
    for asset in _WS_SERVED_PERP_ASSETS:
        try:
            wanted_bases.add(resolve_apex_base(asset).venue_symbol.upper())
        except Exception:  # noqa: BLE001
            continue

    adapter = _safe_adapter("apex")
    symbols: list[str] = []
    if adapter is not None:
        by_base = getattr(adapter, "_symbols_by_base", None)
        if isinstance(by_base, dict):
            for base in wanted_bases:
                meta = by_base.get(base)
                if meta is None:
                    continue
                cross = getattr(meta, "cross_symbol_name", None)
                if cross:
                    symbols.append(str(cross).upper())
            if symbols:
                return sorted(set(symbols))

    # Fallback: phase-1 assets as BASEUSDT (works for crypto; equity may differ).
    for asset in _WS_SERVED_PERP_ASSETS:
        try:
            base = resolve_apex_base(asset).venue_symbol
            symbols.append(f"{base}USDT")
        except Exception:  # noqa: BLE001
            continue
    return sorted(set(symbols))


def _safe_adapter(slug: str) -> Any | None:
    try:
        return get_adapter(slug)
    except Exception:  # noqa: BLE001
        return None
