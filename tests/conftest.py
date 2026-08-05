"""Shared pytest config: --live flag skips network tests unless opted in (WHI-823).

Also installs offline MockTransport clients on registered perp adapters so
``startup_all()`` stays offline-safe, and dummy AMM RPC env for offline startup.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

# Repo-root config/ (sibling of tests/).
_REPO_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def load_committed_config(name: str) -> dict[str, Any]:
    """Load ``config/<name>.yaml`` only (no ``*.local.yaml`` overlay).

    Used by tests that must assert production-committed defaults while the
    offline suite re-enables ``mock`` via an in-memory ``_merge_local`` patch.
    """
    base_path = _REPO_CONFIG_DIR / f"{name}.yaml"
    raw = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError(f"config {base_path} must be a YAML mapping, got {type(raw).__name__}")
    return dict(raw)

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
def enable_mock_adapter_for_offline_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Re-enable the fixture ``mock`` adapter for the offline suite (WHI-849).

    Production commits ``config/venues.yaml`` with ``disabled: [mock]``. Unit/API
    tests still use mock as the offline stand-in. Patch ``_merge_local`` in memory
    so every importer of the cached loaders sees empty ``disabled`` — do **not**
    write ``config/*.local.yaml`` (deploy treats those as hostile tree leaks;
    also not xdist-safe).
    """
    from spread_compare import settings as settings_mod
    from spread_compare.settings import clear_settings_cache

    original_merge = settings_mod._merge_local

    def _merge_local_for_tests(name: str) -> dict[str, Any]:
        raw = dict(original_merge(name))
        if name == "venues":
            raw["disabled"] = []
        return raw

    clear_settings_cache()
    monkeypatch.setattr(settings_mod, "_merge_local", _merge_local_for_tests)
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
