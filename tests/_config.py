"""Test helpers for committed config (WHI-849).

Kept out of ``conftest.py`` so tests can import without re-loading the autouse
fixture module under a second identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
        raise TypeError(
            f"config {base_path} must be a YAML mapping, got {type(raw).__name__}"
        )
    return dict(raw)
