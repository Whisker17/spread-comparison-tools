"""Shared pytest config: --live flag skips network tests unless opted in (WHI-823).

Also installs offline MockTransport clients on registered perp adapters so
``startup_all()`` stays offline-safe, and dummy AMM RPC env for offline startup.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest

# Dummy RPCs so AMM adapter startup() succeeds offline (WHI-804 fail-fast env rule).
# Live tests require real URLs in the process environment before this fixture runs.
_AMM_RPC_DEFAULTS = {
    "ETH_RPC_URL": "http://127.0.0.1:8545",
    "BASE_RPC_URL": "http://127.0.0.1:8545",
    "BSC_RPC_URL": "http://127.0.0.1:8545",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run tests marked live (hits real upstream APIs; needs network/credentials)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="need --live option to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(autouse=True)
def clear_orderbook_snapshot_cache() -> Iterator[None]:
    """Isolate the process-wide WHI-843 book cache between tests."""
    from spread_compare.orderbook_cache import default_orderbook_cache

    default_orderbook_cache().clear()
    yield
    default_orderbook_cache().clear()


@pytest.fixture(autouse=True)
def clear_quote_store() -> Iterator[None]:
    """Isolate the process-wide WHI-846 quote store between tests."""
    from spread_compare.quote_store import default_quote_store, reset_default_quote_store

    reset_default_quote_store()
    default_quote_store().clear()
    yield
    reset_default_quote_store()


@pytest.fixture(autouse=True)
def disable_pull_poller(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep offline tests free of background upstream sweeps (WHI-846).

    Opt-in tests inject ``poller_settings=...`` on QuoteAggregator / PullQuotePoller
    rather than re-enabling the process-wide background loop.
    """
    from spread_compare.settings import clear_settings_cache, load_poller_settings

    clear_settings_cache()
    base = load_poller_settings()
    disabled = base.model_copy(update={"enabled": False})

    def _disabled() -> object:
        return disabled

    # Preserve lru_cache API so clear_settings_cache() still works.
    _disabled.cache_clear = load_poller_settings.cache_clear  # type: ignore[attr-defined]

    monkeypatch.setattr("spread_compare.settings.load_poller_settings", _disabled)
    monkeypatch.setattr("spread_compare.api.app.load_poller_settings", _disabled)
    # aggregator imports the symbol at call time via default arg load — patch module attr.
    monkeypatch.setattr(
        "spread_compare.aggregator.load_poller_settings",
        _disabled,
        raising=False,
    )
    yield
    clear_settings_cache()


@pytest.fixture(autouse=True)
def offline_perp_http(request: pytest.FixtureRequest) -> Iterator[None]:
    """Wire mock HTTP for registered perp adapters in non-live tests."""
    if request.node.get_closest_marker("live"):
        yield
        return

    from tests.perp_offline_http import install_offline_clients

    clients = install_offline_clients()
    yield

    async def _close() -> None:
        for client in clients:
            await client.aclose()

    asyncio.run(_close())


@pytest.fixture(autouse=True)
def offline_prop_http(request: pytest.FixtureRequest) -> Iterator[None]:
    """Wire mock HTTP for registered prop AMM adapters in non-live tests."""
    if request.node.get_closest_marker("live"):
        yield
        return

    from tests.prop_offline_http import install_offline_clients

    clients = install_offline_clients()
    yield

    async def _close() -> None:
        for client in clients:
            await client.aclose()

    asyncio.run(_close())


@pytest.fixture(autouse=True)
def _default_amm_rpc_env(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provide placeholder RPC URLs when unset so startup_all() works offline.

    Skipped under ``--live`` so missing real RPCs fail fast instead of dialing
    localhost. Only fills keys that are empty in the process environment.
    """
    if request.config.getoption("--live"):
        return
    # Offline unit tests must not pick up a host SOCKS/HTTP proxy (httpx then
    # requires socksio). Live tests keep the process environment as-is.
    for key in (
        "ALL_PROXY",
        "all_proxy",
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "SOCKS_PROXY",
        "socks_proxy",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, default in _AMM_RPC_DEFAULTS.items():
        if not os.environ.get(key, "").strip():
            monkeypatch.setenv(key, default)
