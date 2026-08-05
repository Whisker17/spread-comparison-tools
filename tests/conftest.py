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
def enable_mock_adapter_for_offline_tests() -> Iterator[None]:
    """Re-enable the fixture ``mock`` adapter for the offline suite (WHI-849).

    Production commits ``config/venues.yaml`` with ``disabled: [mock]`` so the
    scaffold adapter never appears on a real deploy. Unit/API tests still use
    mock as the offline stand-in; overlay with an empty disable list for the
    process. Settings tests that assert committed defaults read the YAML file
    directly (see test_settings / test_startup_degradation).
    """
    from pathlib import Path

    from spread_compare.settings import clear_settings_cache

    # settings.py lives in spread_compare/; config/ is repo-root sibling.
    config_dir = Path(__file__).resolve().parents[1] / "config"
    path = config_dir / "venues.local.yaml"
    previous: str | None = path.read_text(encoding="utf-8") if path.is_file() else None
    path.write_text(
        "# pytest overlay — re-enable mock for offline tests (WHI-849)\n"
        "disabled: []\n",
        encoding="utf-8",
    )
    clear_settings_cache()
    try:
        yield
    finally:
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(previous, encoding="utf-8")
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
