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
