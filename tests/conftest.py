"""Shared pytest config: --live flag skips network tests unless opted in (WHI-823)."""

from __future__ import annotations

import os

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
def _default_amm_rpc_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide placeholder RPC URLs when unset so startup_all() works offline."""
    for key, default in _AMM_RPC_DEFAULTS.items():
        if not os.environ.get(key, "").strip():
            monkeypatch.setenv(key, default)
