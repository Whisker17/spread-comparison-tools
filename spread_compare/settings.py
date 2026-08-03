"""Typed runtime config loaded from ``config/*.yaml`` (WHI-807).

Secrets stay in ``.env``; non-secret tunables live here. Values marked unvalidated
in WHI-799 §3.2 / WHI-807 are engineering defaults pending DESIGN.md §2.

YAML is authoritative — pydantic fields have **no** Python-side default values so a
missing key fails at startup instead of silently diverging from the file.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "config"


class MidSettings(BaseModel):
    """``config/mid.yaml`` — reference-mid priority chain controls (WHI-799 §3.2)."""

    model_config = ConfigDict(extra="forbid")

    force_pyth: bool
    stale_threshold_sec: float = Field(gt=0)
    cache_max_age_sec: float = Field(gt=0)
    http_timeout_sec: float = Field(gt=0)
    pyth_feed_ids: dict[str, str]

    @field_validator("pyth_feed_ids", mode="before")
    @classmethod
    def _normalize_feed_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(k).upper(): str(v) for k, v in value.items()}


class AggregatorSettings(BaseModel):
    """``config/aggregator.yaml`` — fan-out timeouts and response cache."""

    model_config = ConfigDict(extra="forbid")

    venue_timeout_sec: float = Field(gt=0)
    response_cache_ttl_sec: float = Field(ge=0)


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"config {path} must be a YAML mapping, got {type(raw).__name__}")
    return raw


def _merge_local(name: str) -> dict[str, Any]:
    """Load ``config/<name>.yaml`` then overlay ``config/<name>.local.yaml`` if present."""
    base_path = _CONFIG_DIR / f"{name}.yaml"
    if not base_path.is_file():
        raise FileNotFoundError(f"required config file missing: {base_path}")
    base = _read_yaml(base_path)
    local = _read_yaml(_CONFIG_DIR / f"{name}.local.yaml")
    return {**base, **local}


@lru_cache(maxsize=1)
def load_mid_settings() -> MidSettings:
    """Parse mid settings once; fail fast on invalid config."""
    return MidSettings.model_validate(_merge_local("mid"))


@lru_cache(maxsize=1)
def load_aggregator_settings() -> AggregatorSettings:
    """Parse aggregator settings once; fail fast on invalid config."""
    return AggregatorSettings.model_validate(_merge_local("aggregator"))


def clear_settings_cache() -> None:
    """Drop cached settings (tests that rewrite YAML)."""
    load_mid_settings.cache_clear()
    load_aggregator_settings.cache_clear()
