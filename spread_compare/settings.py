"""Typed runtime config loaded from ``config/*.yaml`` (WHI-807 / WHI-836).

Secrets stay in ``.env``; non-secret tunables live here. Values marked unvalidated
in WHI-799 §3.2 / WHI-807 are engineering defaults pending DESIGN.md §2.

YAML is authoritative — pydantic fields have **no** Python-side default values so a
missing key fails at startup instead of silently diverging from the file.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from spread_compare.models import VenueClass

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "config"


class StockMidP2Step(BaseModel):
    """One step of the stock mid P2 tokenized CEX TOB order (WHI-799 §3.3.1)."""

    model_config = ConfigDict(extra="forbid")

    form: str
    venue: str

    @field_validator("form")
    @classmethod
    def _known_form(cls, value: str) -> str:
        from spread_compare.assets import FORM_IDS

        key = value.strip().lower()
        if key not in FORM_IDS:
            raise ValueError(
                f"stock_mid_p2_order form must be one of {list(FORM_IDS)}, got {value!r}"
            )
        return key

    @field_validator("venue")
    @classmethod
    def _known_cex_venue(cls, value: str) -> str:
        key = value.strip().lower()
        if key not in {"binance", "bybit"}:
            raise ValueError(
                f"stock_mid_p2_order venue must be binance or bybit, got {value!r}"
            )
        return key


class MidSettings(BaseModel):
    """``config/mid.yaml`` — reference-mid priority chain controls (WHI-799 §3.2)."""

    model_config = ConfigDict(extra="forbid")

    force_pyth: bool
    stale_threshold_sec: float = Field(gt=0)
    cache_max_age_sec: float = Field(gt=0)
    http_timeout_sec: float = Field(gt=0)
    # WHI-847: tighter mid freshness for quotes walked from WS books.
    max_age_for_ws_quote_sec: float = Field(gt=0)
    pyth_feed_ids: dict[str, str]
    # WHI-881 / WHI-799 §3.3.1: fixed P2 order for stock underlyings (unvalidated).
    stock_mid_p2_order: list[StockMidP2Step]

    @field_validator("pyth_feed_ids", mode="before")
    @classmethod
    def _normalize_feed_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(k).upper(): str(v) for k, v in value.items()}

    @field_validator("stock_mid_p2_order")
    @classmethod
    def _nonempty_p2_order(cls, value: list[StockMidP2Step]) -> list[StockMidP2Step]:
        if not value:
            raise ValueError("stock_mid_p2_order must list at least one step")
        return value


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


class ImpactSettings(BaseModel):
    """``config/impact.yaml`` — price-impact guard threshold (WHI-845)."""

    model_config = ConfigDict(extra="forbid")

    # Quotes with price_impact_bps above this become status=excessive_impact.
    # Decimal to match model-layer bps; YAML numbers parse natively.
    max_price_impact_bps: Decimal = Field(gt=0)


class OrderbookCacheSettings(BaseModel):
    """``config/orderbook_cache.yaml`` — short-TTL book snapshot reuse (WHI-843)."""

    model_config = ConfigDict(extra="forbid")

    # Seconds a fetched book remains reusable for multi-tier / TOB walks.
    ttl_sec: float = Field(ge=0)


class WsStreamFlags(BaseModel):
    """Per-stream enable flags under ``config/ws.yaml`` streams."""

    model_config = ConfigDict(extra="forbid")

    binance_spot: bool
    binance_futures: bool
    bybit_spot: bool
    bybit_linear: bool
    hyperliquid: bool
    lighter: bool
    apex: bool


# Multiplexed orderbook stream ids (WsStreamFlags fields / WsFeedManager).
KNOWN_WS_STREAM_IDS: frozenset[str] = frozenset(WsStreamFlags.model_fields)


class WsSettings(BaseModel):
    """``config/ws.yaml`` — WebSocket orderbook ingest (WHI-847 / WHI-855)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    max_book_age_sec: float = Field(gt=0)
    reconnect_min_sec: float = Field(gt=0)
    reconnect_max_sec: float = Field(gt=0)
    lighter_min_resync_interval_sec: float = Field(gt=0)
    lighter_resync_snapshot_timeout_sec: float = Field(gt=0)
    fast_mid_poll_interval_sec: float = Field(gt=0)
    # Per-venue subscribe chunk sizes (args per op) — WHI-855.
    bybit_spot_subscribe_chunk: int = Field(ge=1)
    bybit_linear_subscribe_chunk: int = Field(ge=1)
    apex_subscribe_chunk: int = Field(ge=1)
    # Binance spot REST resync budget — WHI-855.
    binance_spot_min_resync_interval_sec: float = Field(gt=0)
    binance_spot_resync_weight: int = Field(ge=1)
    binance_spot_resync_weight_budget_per_min: int = Field(ge=1)
    # Heartbeats — transport ping default + Hyperliquid app-level override.
    default_transport_ping_interval_sec: float = Field(gt=0)
    hyperliquid_app_ping_interval_sec: float = Field(gt=0)
    hyperliquid_transport_ping: bool
    streams: WsStreamFlags

    @model_validator(mode="after")
    def _reconnect_max_not_below_min(self) -> WsSettings:
        if self.reconnect_max_sec < self.reconnect_min_sec:
            raise ValueError(
                "reconnect_max_sec must be >= reconnect_min_sec "
                f"(got max={self.reconnect_max_sec}, min={self.reconnect_min_sec})"
            )
        return self


class PollerGroupSettings(BaseModel):
    """One upstream budget group under ``config/poller.yaml`` groups (WHI-846)."""

    model_config = ConfigDict(extra="forbid")

    interval_sec: float = Field(gt=0)
    # Per-group sampled tiers (WHI-864) — Jupiter stays sparse; Kyber/RPC keep
    # the full §4.1 matrix. Must be WHI-799 §4.1 values so store keys match
    # GET /quotes requests.
    notionals_usd: list[Decimal] = Field(min_length=1)
    # Cap average sweep RPS as a fraction of a known capacity (Jupiter keyed).
    # Mutually optional with ``max_rps`` — at least one pacing bound applies via
    # interval-derived rate when both are absent/None.
    budget_share: float | None = Field(default=None, gt=0, le=1)
    # Absolute RPS cap when upstream capacity is unpublished (Kyber / RPC).
    max_rps: float | None = Field(default=None, gt=0)
    # Age past which a store row is marked quote_stale and loses §5.2 best.
    max_quote_age_for_best_sec: float = Field(gt=0)
    # Age past which a failed refresh degrades the stored row to error.
    max_stale_sec: float = Field(gt=0)

    @field_validator("notionals_usd")
    @classmethod
    def _tier_notionals(cls, value: list[Decimal]) -> list[Decimal]:
        from spread_compare.models import NOTIONAL_TIERS_USD

        allowed = set(NOTIONAL_TIERS_USD)
        for n in value:
            if n not in allowed:
                raise ValueError(
                    f"notionals_usd entry {n} is not a WHI-799 §4.1 tier "
                    f"{list(NOTIONAL_TIERS_USD)}"
                )
        return value

    @model_validator(mode="after")
    def _stale_not_below_best_age(self) -> PollerGroupSettings:
        if self.max_stale_sec < self.max_quote_age_for_best_sec:
            raise ValueError(
                "max_stale_sec must be >= max_quote_age_for_best_sec "
                f"(got stale={self.max_stale_sec}, best={self.max_quote_age_for_best_sec})"
            )
        return self


class StreamSettings(BaseModel):
    """``config/stream.yaml`` — browser WebSocket push stream (WHI-848)."""

    model_config = ConfigDict(extra="forbid")

    # Batch window for delta frames; caps push rate under bursty venue updates.
    coalesce_interval_ms: float = Field(gt=0)
    heartbeat_interval_sec: float = Field(gt=0)
    # Client-side dead-connection threshold (must exceed heartbeat interval).
    client_liveness_timeout_sec: float = Field(gt=0)
    max_clients: int = Field(ge=1)
    max_assets_per_client: int = Field(ge=1)
    max_venues_per_client: int = Field(ge=1)
    max_queue_depth: int = Field(ge=1)

    @model_validator(mode="after")
    def _liveness_above_heartbeat(self) -> StreamSettings:
        if self.client_liveness_timeout_sec <= self.heartbeat_interval_sec:
            raise ValueError(
                "client_liveness_timeout_sec must be > heartbeat_interval_sec "
                f"(got liveness={self.client_liveness_timeout_sec}, "
                f"heartbeat={self.heartbeat_interval_sec})"
            )
        return self


class PollerSettings(BaseModel):
    """``config/poller.yaml`` — pull-only background poller (WHI-846 / WHI-864)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    poller_served_classes: list[VenueClass] = Field(min_length=1)
    # Tier set is per group (WHI-864); no global notionals_usd.
    groups: dict[str, PollerGroupSettings]

    @field_validator("poller_served_classes")
    @classmethod
    def _unique_classes(cls, value: list[VenueClass]) -> list[VenueClass]:
        if len(set(value)) != len(value):
            raise ValueError("poller_served_classes must not contain duplicates")
        return value

    @field_validator("groups")
    @classmethod
    def _known_group_keys(
        cls, value: dict[str, PollerGroupSettings]
    ) -> dict[str, PollerGroupSettings]:
        allowed = {"jupiter", "kyber", "rpc"}
        unknown = sorted(k for k in value if k not in allowed)
        if unknown:
            raise ValueError(
                f"unknown poller group key(s): {unknown}; allowed: {sorted(allowed)}"
            )
        if not value:
            raise ValueError("groups must contain at least one sweep group")
        return value

    @model_validator(mode="after")
    def _served_classes_have_groups(self) -> PollerSettings:
        """Every poller-served class must map to a configured sweep group."""
        # amm_dex → rpc; prop_amm → jupiter and/or kyber (both cover prop slugs).
        needs: dict[VenueClass, set[str]] = {
            "amm_dex": {"rpc"},
            "prop_amm": {"jupiter", "kyber"},
            "cex": set(),  # no group — reject if listed
            "perp_dex": set(),
        }
        configured = set(self.groups)
        for vc in self.poller_served_classes:
            required = needs.get(vc, set())
            if not required:
                raise ValueError(
                    f"poller_served_classes includes {vc!r} which has no sweep "
                    "group mapping (only amm_dex / prop_amm are poller-served)"
                )
            if not (required & configured):
                raise ValueError(
                    f"poller_served_classes includes {vc!r} but groups is missing "
                    f"any of {sorted(required)}"
                )
        return self


# Known AMM adapter ``rpc_env`` names (must stay aligned with amm_*.py).
_KNOWN_RPC_ENVS: frozenset[str] = frozenset(
    {"ETH_RPC_URL", "BASE_RPC_URL", "BSC_RPC_URL"}
)


class RpcChainOverride(BaseModel):
    """Optional per-``rpc_env`` budget override under ``config/rpc.yaml`` chains."""

    model_config = ConfigDict(extra="forbid")

    rps: int | None = Field(default=None, ge=1)
    window_sec: float | None = Field(default=None, gt=0)
    max_attempts: int | None = Field(default=None, ge=1)
    backoff_start_sec: float | None = Field(default=None, gt=0)
    backoff_max_sec: float | None = Field(default=None, gt=0)
    retry_after_floor_sec: float | None = Field(default=None, ge=0)
    gas_price_cache_ttl_sec: float | None = Field(default=None, ge=0)


class RpcChainBudget(BaseModel):
    """Resolved per-endpoint RPC client budget (WHI-842)."""

    model_config = ConfigDict(extra="forbid")

    rps: int = Field(ge=1)
    window_sec: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    backoff_start_sec: float = Field(gt=0)
    backoff_max_sec: float = Field(gt=0)
    retry_after_floor_sec: float = Field(ge=0)
    gas_price_cache_ttl_sec: float = Field(ge=0)


class RpcSettings(BaseModel):
    """``config/rpc.yaml`` — EVM JSON-RPC rate budget + retry (WHI-842)."""

    model_config = ConfigDict(extra="forbid")

    default_rps: int = Field(ge=1)
    window_sec: float = Field(gt=0)
    max_attempts: int = Field(ge=1)
    backoff_start_sec: float = Field(gt=0)
    backoff_max_sec: float = Field(gt=0)
    retry_after_floor_sec: float = Field(ge=0)
    gas_price_cache_ttl_sec: float = Field(ge=0)
    chains: dict[str, RpcChainOverride]

    @field_validator("chains", mode="before")
    @classmethod
    def _normalize_chain_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(k).strip(): v for k, v in value.items() if str(k).strip()}

    @field_validator("chains")
    @classmethod
    def _known_chain_keys(
        cls, value: dict[str, RpcChainOverride]
    ) -> dict[str, RpcChainOverride]:
        unknown = sorted(k for k in value if k not in _KNOWN_RPC_ENVS)
        if unknown:
            raise ValueError(
                f"unknown rpc env key(s) in chains: {unknown}; "
                f"allowed: {sorted(_KNOWN_RPC_ENVS)}"
            )
        return value

    @model_validator(mode="after")
    def _backoff_max_not_below_start(self) -> RpcSettings:
        if self.backoff_max_sec < self.backoff_start_sec:
            raise ValueError(
                "backoff_max_sec must be >= backoff_start_sec "
                f"(got max={self.backoff_max_sec}, start={self.backoff_start_sec})"
            )
        return self

    def budget_for(self, rpc_env: str) -> RpcChainBudget:
        """Resolve defaults with optional per-env overrides."""
        base = {
            "rps": self.default_rps,
            "window_sec": self.window_sec,
            "max_attempts": self.max_attempts,
            "backoff_start_sec": self.backoff_start_sec,
            "backoff_max_sec": self.backoff_max_sec,
            "retry_after_floor_sec": self.retry_after_floor_sec,
            "gas_price_cache_ttl_sec": self.gas_price_cache_ttl_sec,
        }
        override = self.chains.get(rpc_env)
        if override is not None:
            base.update(override.model_dump(exclude_none=True))
        return RpcChainBudget.model_validate(base)


class MonitorSettings(BaseModel):
    """``config/monitor.yaml`` — real-time engine health alerts (WHI-819)."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    eval_interval_sec: float = Field(gt=0)
    startup_grace_sec: float = Field(ge=0)
    alert_cooldown_sec: float = Field(ge=0)
    webhook_timeout_sec: float = Field(gt=0)
    # Orderbook / WS class.
    ws_max_book_age_sec: float = Field(gt=0)
    ws_disconnected_alert_sec: float = Field(gt=0)
    # WHI-856: expected-vs-healthy book sync grace (unvalidated defaults).
    ws_books_sync_grace_sec: float = Field(gt=0)
    # Required key (may be `{}`) so a missing YAML entry fails at load.
    ws_books_sync_grace_sec_by_stream: dict[str, float]
    ws_resync_window_sec: float = Field(gt=0)
    ws_resync_count_threshold: int = Field(ge=1)
    ws_failed_resync_threshold: int = Field(ge=1)
    # Pull-only sweep class: age > interval * multiplier → sweep_stale.
    sweep_stale_multiplier: float = Field(gt=1)
    mid_max_age_sec: float = Field(gt=0)
    rate_limit_window_sec: float = Field(gt=0)
    rate_limit_count_threshold: int = Field(ge=1)
    probe_asset: str = Field(min_length=1)
    probe_max_quote_age_sec: float = Field(gt=0)
    probe_min_fresh_store_quotes: int = Field(ge=0)
    probe_min_healthy_books: int = Field(ge=0)
    # WHI-856: per-stream floor (process-wide probe_min_healthy_books alone masks
    # dead venues when one stream is healthy).
    probe_min_healthy_books_per_stream: int = Field(ge=0)

    @field_validator("probe_asset")
    @classmethod
    def _upper_probe_asset(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("ws_books_sync_grace_sec_by_stream")
    @classmethod
    def _positive_known_stream_grace(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = sorted(k for k in value if k not in KNOWN_WS_STREAM_IDS)
        if unknown:
            raise ValueError(
                f"unknown stream id(s) in ws_books_sync_grace_sec_by_stream: "
                f"{unknown}; allowed: {sorted(KNOWN_WS_STREAM_IDS)}"
            )
        for key, sec in value.items():
            if sec <= 0:
                raise ValueError(
                    f"ws_books_sync_grace_sec_by_stream[{key!r}] must be > 0 (got {sec})"
                )
        return value

    def books_sync_grace_sec(self, stream_id: str) -> float:
        """Per-stream books-sync grace, falling back to the global default."""
        return self.ws_books_sync_grace_sec_by_stream.get(
            stream_id, self.ws_books_sync_grace_sec
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


@lru_cache(maxsize=1)
def load_impact_settings() -> ImpactSettings:
    """Parse price-impact guard settings once; fail fast on invalid config."""
    return ImpactSettings.model_validate(_merge_local("impact"))


@lru_cache(maxsize=1)
def load_orderbook_cache_settings() -> OrderbookCacheSettings:
    """Parse orderbook snapshot-cache TTL once; fail fast on invalid config."""
    return OrderbookCacheSettings.model_validate(_merge_local("orderbook_cache"))


@lru_cache(maxsize=1)
def load_poller_settings() -> PollerSettings:
    """Parse pull-only poller settings once; fail fast on invalid config."""
    return PollerSettings.model_validate(_merge_local("poller"))


@lru_cache(maxsize=1)
def load_stream_settings() -> StreamSettings:
    """Parse browser WebSocket push-stream settings once; fail fast on invalid config."""
    return StreamSettings.model_validate(_merge_local("stream"))


@lru_cache(maxsize=1)
def load_ws_settings() -> WsSettings:
    """Parse WebSocket orderbook ingest settings once; fail fast on invalid config."""
    return WsSettings.model_validate(_merge_local("ws"))


@lru_cache(maxsize=1)
def load_monitor_settings() -> MonitorSettings:
    """Parse real-time engine monitor settings once; fail fast on invalid config."""
    return MonitorSettings.model_validate(_merge_local("monitor"))


def clear_settings_cache() -> None:
    """Drop cached settings (tests that rewrite YAML)."""
    load_mid_settings.cache_clear()
    load_aggregator_settings.cache_clear()
    load_jupiter_settings.cache_clear()
    load_api_settings.cache_clear()
    load_venue_settings.cache_clear()
    load_rpc_settings.cache_clear()
    load_impact_settings.cache_clear()
    load_orderbook_cache_settings.cache_clear()
    load_poller_settings.cache_clear()
    load_stream_settings.cache_clear()
    load_ws_settings.cache_clear()
    load_monitor_settings.cache_clear()
