"""Typed runtime config loaded from ``config/*.yaml`` (WHI-807 / WHI-836).

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
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spread_compare.models import VenueClass

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
    # Per-class overrides; empty map = always use venue_timeout_sec. Required key
    # (may be {}) so a missing YAML entry fails at load, not at first fan-out.
    venue_timeout_by_class: dict[VenueClass, float]
    response_cache_ttl_sec: float = Field(ge=0)

    @field_validator("venue_timeout_by_class")
    @classmethod
    def _positive_class_timeouts(
        cls, value: dict[VenueClass, float]
    ) -> dict[VenueClass, float]:
        for key, timeout in value.items():
            if timeout <= 0:
                raise ValueError(
                    f"venue_timeout_by_class[{key!r}] must be > 0, got {timeout}"
                )
        return value

    def timeout_for(self, venue_class: VenueClass) -> float:
        """Per-venue-class timeout, falling back to the global default."""
        return self.venue_timeout_by_class.get(venue_class, self.venue_timeout_sec)


class JupiterSettings(BaseModel):
    """``config/jupiter.yaml`` — Quote API rate budget (WHI-836)."""

    model_config = ConfigDict(extra="forbid")

    keyless_capacity: int = Field(ge=1)
    keyed_capacity: int = Field(ge=1)
    window_sec: float = Field(gt=0)
    adapt_from_headers: bool

    @model_validator(mode="after")
    def _keyless_not_above_keyed(self) -> JupiterSettings:
        # prop_jupiter "strictest mode wins" assumes keyless is the tighter budget.
        if self.keyless_capacity > self.keyed_capacity:
            raise ValueError(
                "keyless_capacity must be <= keyed_capacity "
                f"(got keyless={self.keyless_capacity}, keyed={self.keyed_capacity})"
            )
        return self


class ApiSettings(BaseModel):
    """``config/api.yaml`` — HTTP surface tunables (CORS origins, WHI-808 / WHI-814)."""

    model_config = ConfigDict(extra="forbid")

    cors_origins: list[str] = Field(min_length=0)
    # Per-client min interval for POST /simulate (Jupiter keyless ~0.5 RPS budget).
    simulate_min_interval_sec: float = Field(ge=0)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_origins(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(v).rstrip("/") for v in value]


class RpcChainOverride(BaseModel):
    """Optional per-``rpc_env`` budget override under ``config/rpc.yaml`` chains."""

    model_config = ConfigDict(extra="forbid")

    rps: int | None = Field(default=None, ge=1)
    window_sec: float | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=1)
    backoff_start_sec: float | None = Field(default=None, gt=0)
    gas_price_cache_ttl_sec: float | None = Field(default=None, ge=0)


class RpcChainBudget(BaseModel):
    """Resolved per-endpoint RPC client budget (WHI-842)."""

    model_config = ConfigDict(extra="forbid")

    rps: int = Field(ge=1)
    window_sec: float = Field(gt=0)
    max_retries: int = Field(ge=1)
    backoff_start_sec: float = Field(gt=0)
    gas_price_cache_ttl_sec: float = Field(ge=0)


class RpcSettings(BaseModel):
    """``config/rpc.yaml`` — EVM JSON-RPC rate budget + retry (WHI-842)."""

    model_config = ConfigDict(extra="forbid")

    default_rps: int = Field(ge=1)
    window_sec: float = Field(gt=0)
    max_retries: int = Field(ge=1)
    backoff_start_sec: float = Field(gt=0)
    gas_price_cache_ttl_sec: float = Field(ge=0)
    chains: dict[str, RpcChainOverride]

    @field_validator("chains", mode="before")
    @classmethod
    def _normalize_chain_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(k).strip(): v for k, v in value.items() if str(k).strip()}

    def budget_for(self, rpc_env: str) -> RpcChainBudget:
        """Resolve defaults with optional per-env overrides."""
        override = self.chains.get(rpc_env)
        if override is None:
            return RpcChainBudget(
                rps=self.default_rps,
                window_sec=self.window_sec,
                max_retries=self.max_retries,
                backoff_start_sec=self.backoff_start_sec,
                gas_price_cache_ttl_sec=self.gas_price_cache_ttl_sec,
            )
        return RpcChainBudget(
            rps=override.rps if override.rps is not None else self.default_rps,
            window_sec=(
                override.window_sec
                if override.window_sec is not None
                else self.window_sec
            ),
            max_retries=(
                override.max_retries
                if override.max_retries is not None
                else self.max_retries
            ),
            backoff_start_sec=(
                override.backoff_start_sec
                if override.backoff_start_sec is not None
                else self.backoff_start_sec
            ),
            gas_price_cache_ttl_sec=(
                override.gas_price_cache_ttl_sec
                if override.gas_price_cache_ttl_sec is not None
                else self.gas_price_cache_ttl_sec
            ),
        )


class VenueSettings(BaseModel):
    """``config/venues.yaml`` — enable/disable + startup-retry (WHI-840)."""

    model_config = ConfigDict(extra="forbid")

    disabled: list[str]
    startup_retry_interval_sec: float = Field(ge=0)
    startup_retry_backoff_multiplier: float = Field(gt=1)
    startup_retry_max_interval_sec: float = Field(gt=0)

    @field_validator("disabled", mode="before")
    @classmethod
    def _normalize_disabled(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [str(v).strip() for v in value if str(v).strip()]

    @field_validator("disabled")
    @classmethod
    def _known_disabled_slugs(cls, value: list[str]) -> list[str]:
        # Lazy import: settings must stay importable before adapter discovery.
        from spread_compare.adapters.registry import allowed_adapter_slugs

        allowed = allowed_adapter_slugs()
        unknown = sorted({s for s in value if s not in allowed})
        if unknown:
            raise ValueError(
                f"unknown venue slug(s) in disabled: {unknown}; "
                f"allowed: {sorted(allowed)}"
            )
        return value

    @model_validator(mode="after")
    def _max_not_below_interval(self) -> VenueSettings:
        if (
            self.startup_retry_interval_sec > 0
            and self.startup_retry_max_interval_sec < self.startup_retry_interval_sec
        ):
            raise ValueError(
                "startup_retry_max_interval_sec must be >= startup_retry_interval_sec "
                f"(got max={self.startup_retry_max_interval_sec}, "
                f"interval={self.startup_retry_interval_sec})"
            )
        return self


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


@lru_cache(maxsize=1)
def load_jupiter_settings() -> JupiterSettings:
    """Parse Jupiter rate-budget settings once; fail fast on invalid config."""
    return JupiterSettings.model_validate(_merge_local("jupiter"))


@lru_cache(maxsize=1)
def load_api_settings() -> ApiSettings:
    """Parse API settings once; fail fast on invalid config."""
    return ApiSettings.model_validate(_merge_local("api"))


@lru_cache(maxsize=1)
def load_venue_settings() -> VenueSettings:
    """Parse venue enable/disable + retry settings once; fail fast on invalid config."""
    return VenueSettings.model_validate(_merge_local("venues"))


@lru_cache(maxsize=1)
def load_rpc_settings() -> RpcSettings:
    """Parse EVM JSON-RPC budget settings once; fail fast on invalid config."""
    return RpcSettings.model_validate(_merge_local("rpc"))


def clear_settings_cache() -> None:
    """Drop cached settings (tests that rewrite YAML)."""
    load_mid_settings.cache_clear()
    load_aggregator_settings.cache_clear()
    load_jupiter_settings.cache_clear()
    load_api_settings.cache_clear()
    load_venue_settings.cache_clear()
    load_rpc_settings.cache_clear()
