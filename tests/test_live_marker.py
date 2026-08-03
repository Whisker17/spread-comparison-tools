"""Live-test skip convention (WHI-823).

Default ``uv run pytest`` skips this; ``uv run pytest --live`` runs it.
"""

from __future__ import annotations

import pytest


@pytest.mark.live
def test_live_marker_runs_only_with_flag() -> None:
    """Placeholder proving the live marker is wired; no network I/O."""
    assert True
