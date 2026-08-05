"""Collect symbols and start WS feeds + fast mid after adapter startup (WHI-847)."""

from __future__ import annotations

import logging
from typing import Any

from spread_compare.adapters.registry import get as get_adapter
from spread_compare.adapters.registry import list_venues
from spread_compare.cex_symbols import resolve_cex_symbol, supported_cex_assets
from spread_compare.mids import MidService
from spread_compare.perp_symbols import resolve_apex_base, resolve_hl_coin, resolve_lighter_symbol
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
    out: list[str] = []
    for asset in supported_cex_assets(book_side):  # type: ignore[arg-type]
        if exclude_bstocks and asset in {"QQQB", "SPCXB", "NVDAB"}:
            continue
        sym = resolve_cex_symbol(asset, book_side)  # type: ignore[arg-type]
        if sym:
            out.append(sym)
    # Prefer blue chips first for connection subscribe order.
    priority = {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    out = sorted(set(out), key=lambda s: (0 if s in priority else 1, s))
    return out


def _hl_coins() -> list[str]:
    adapter = _safe_adapter("hyperliquid")
    assets: list[str] = []
    if adapter is not None:
        try:
            assets = list(adapter.supported_assets())
        except Exception:  # noqa: BLE001
            assets = list(_FAST_MID_ASSETS)
    else:
        assets = list(_FAST_MID_ASSETS)
    coins: list[str] = []
    for asset in assets:
        try:
            coins.append(resolve_hl_coin(asset).venue_symbol)
        except Exception:  # noqa: BLE001
            continue
    return coins


def _lighter_markets() -> dict[str, str]:
    """market_id → symbol."""
    adapter = _safe_adapter("lighter")
    if adapter is None:
        return {}
    markets: dict[str, str] = {}
    # Prefer adapter's warm market table when startup succeeded.
    by_sym = getattr(adapter, "_markets_by_symbol", None)
    if isinstance(by_sym, dict):
        for symbol, meta in by_sym.items():
            mid = getattr(meta, "market_id", None)
            if mid is not None:
                markets[str(mid)] = str(symbol).upper()
        return markets
    # Fallback: resolve phase-1 assets if market_id_for is available.
    for asset in _FAST_MID_ASSETS:
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
    return markets


def _apex_cross_symbols() -> list[str]:
    adapter = _safe_adapter("apex")
    if adapter is None:
        return [f"{a}USDT" for a in ("BTC", "ETH", "SOL")]
    symbols: list[str] = []
    by_base = getattr(adapter, "_symbols_by_base", None)
    if isinstance(by_base, dict):
        for meta in by_base.values():
            cross = getattr(meta, "cross_symbol_name", None)
            if cross:
                symbols.append(str(cross).upper())
        return sorted(set(symbols))
    for asset in _FAST_MID_ASSETS:
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


def list_orderbook_adapters() -> list[str]:
    out: list[str] = []
    for slug in list_venues():
        adapter = get_adapter(slug)
        if adapter.venue_class in ("cex", "perp_dex"):
            out.append(slug)
    return out
