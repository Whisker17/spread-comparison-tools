"""Shared pytest config: --live flag skips network tests unless opted in (WHI-823).

Also installs offline MockTransport clients on registered perp adapters so
``startup_all()`` stays offline-safe without production fallback tables.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest


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
