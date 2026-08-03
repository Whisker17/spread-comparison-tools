"""Typed fee-schedule loader from ``config/fees/*.yaml`` (WHI-812).

Validates YAML into :class:`~spread_compare.models.FeeSchedule` at load time
(fail fast). Lookup is by ``(venue, instrument_type)``; optional ``asset`` is
stamped onto a copy of the venue default schedule (asset-specific overrides
are not used in Phase 1).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from spread_compare.models import FeeSchedule, FeeTier, InstrumentType
from spread_compare.venues import known_slugs

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FEES_DIR: Final[Path] = _REPO_ROOT / "config" / "fees"

# Instrument types each registered venue must publish a schedule for.
_REQUIRED_INSTRUMENTS: Final[dict[str, frozenset[InstrumentType]]] = {
    "binance": frozenset({"spot", "perp"}),
    "bybit": frozenset({"spot", "perp"}),
    "hyperliquid": frozenset({"perp"}),
    "lighter": frozenset({"perp"}),
    "apex": frozenset({"perp"}),
    "uniswap_eth": frozenset({"amm_pool"}),
    "aerodrome_base": frozenset({"amm_pool"}),
    "pancakeswap_bsc": frozenset({"amm_pool"}),
    "humidifi": frozenset({"prop_amm"}),
    "tessera_solana": frozenset({"prop_amm"}),
    "tessera_base": frozenset({"prop_amm"}),
    "tessera_bsc": frozenset({"prop_amm"}),
    "bisonfi": frozenset({"prop_amm"}),
}


class _VenueFeeFile(BaseModel):
    """One ``config/fees/<slug>.yaml`` document."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    schedules: list[FeeSchedule] = Field(min_length=1)

    @field_validator("schedules", mode="before")
    @classmethod
    def _inject_venue(cls, value: object, info: Any) -> object:
        """Allow schedule rows to omit ``venue``; fill from the file-level field."""
        if not isinstance(value, list):
            return value
        venue = info.data.get("venue")
        out: list[object] = []
        for item in value:
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("venue", venue)
                out.append(row)
            else:
                out.append(item)
        return out


class FeeCatalog:
    """In-memory index of validated fee schedules."""

    def __init__(self, schedules: list[FeeSchedule]) -> None:
        index: dict[tuple[str, InstrumentType], FeeSchedule] = {}
        for sched in schedules:
            key = (sched.venue, sched.instrument_type)
            if key in index:
                raise ValueError(
                    f"duplicate fee schedule for venue={sched.venue!r} "
                    f"instrument_type={sched.instrument_type!r}"
                )
            index[key] = sched
        self._by_key = index
        self._all = list(schedules)

    def get(
        self,
        venue: str,
        instrument_type: InstrumentType,
        asset: str | None = None,
    ) -> FeeSchedule:
        """Return the schedule for ``(venue, instrument_type)``.

        Raises :class:`KeyError` when missing. When ``asset`` is set, returns a
        copy with ``asset`` filled (uppercased).
        """
        try:
            schedule = self._by_key[(venue, instrument_type)]
        except KeyError as exc:
            raise KeyError(
                f"no fee schedule for venue={venue!r} "
                f"instrument_type={instrument_type!r}"
            ) from exc
        if asset is None:
            return schedule
        return schedule.model_copy(update={"asset": asset.upper()})

    def all_schedules(self) -> list[FeeSchedule]:
        """All schedules in stable venue/instrument order."""
        return sorted(
            self._all,
            key=lambda s: (s.venue, s.instrument_type),
        )

    def venues(self) -> frozenset[str]:
        return frozenset(v for v, _ in self._by_key)


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"config {path} must be a YAML mapping, got {type(raw).__name__}"
        )
    return raw


def _validate_coverage(catalog: FeeCatalog) -> None:
    """Fail if any registered venue lacks its required instrument schedules."""
    missing: list[str] = []
    for slug in sorted(known_slugs()):
        required = _REQUIRED_INSTRUMENTS.get(slug)
        if required is None:
            # New venue in VENUES without a fee matrix entry — treat as error so
            # the catalog stays complete for every registered slug.
            missing.append(f"{slug}: no required-instrument matrix entry")
            continue
        for itype in sorted(required):
            try:
                sched = catalog.get(slug, itype)
            except KeyError:
                missing.append(f"{slug}/{itype}: schedule missing")
                continue
            if not sched.source_urls:
                missing.append(f"{slug}/{itype}: source_urls empty")
            if sched.updated_at is None:
                missing.append(f"{slug}/{itype}: updated_at missing")
            if sched.venue != slug:
                missing.append(
                    f"{slug}/{itype}: venue field {sched.venue!r} != file slug"
                )
    # Extra files for unknown venues are allowed only if not in VENUES — but
    # we still require every VENUES slug to be covered above.
    extra = catalog.venues() - known_slugs()
    if missing:
        raise ValueError(
            "fee catalog incomplete or invalid:\n  - " + "\n  - ".join(missing)
        )
    _ = extra  # scaffold-only adapters (mock) need no fee YAML


def load_fee_catalog(*, fees_dir: Path | None = None) -> FeeCatalog:
    """Parse all ``config/fees/*.yaml`` files and validate coverage.

    ``fees_dir`` overrides the default path (tests). Raises on schema mismatch
    or missing required venue × instrument schedules.
    """
    directory = fees_dir if fees_dir is not None else _FEES_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"fee config directory missing: {directory}")

    schedules: list[FeeSchedule] = []
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"no fee YAML files under {directory}")

    for path in paths:
        data = _read_yaml(path)
        try:
            parsed = _VenueFeeFile.model_validate(data)
        except ValidationError as exc:
            raise ValueError(f"invalid fee config {path}: {exc}") from exc
        expected_slug = path.stem
        if parsed.venue != expected_slug:
            raise ValueError(
                f"fee file {path.name}: venue={parsed.venue!r} does not match "
                f"filename stem {expected_slug!r}"
            )
        for sched in parsed.schedules:
            if sched.venue != parsed.venue:
                raise ValueError(
                    f"fee file {path.name}: schedule venue={sched.venue!r} "
                    f"!= file venue={parsed.venue!r}"
                )
            schedules.append(sched)

    catalog = FeeCatalog(schedules)
    _validate_coverage(catalog)
    return catalog


@lru_cache(maxsize=1)
def get_fee_catalog() -> FeeCatalog:
    """Process-wide fee catalog (loaded once; fail fast on bad config)."""
    return load_fee_catalog()


def get_fee_schedule(
    venue: str,
    instrument_type: InstrumentType,
    asset: str | None = None,
) -> FeeSchedule:
    """Lookup helper used by adapters' ``get_fees``."""
    return get_fee_catalog().get(venue, instrument_type, asset=asset)


def list_fee_schedules() -> list[FeeSchedule]:
    """All validated schedules (for ``GET /fees``)."""
    return get_fee_catalog().all_schedules()


def clear_fee_catalog_cache() -> None:
    """Drop cached catalog (tests that rewrite YAML or use a temp dir)."""
    get_fee_catalog.cache_clear()


# Re-export FeeTier for type convenience in tests.
__all__ = [
    "FeeCatalog",
    "FeeTier",
    "clear_fee_catalog_cache",
    "get_fee_catalog",
    "get_fee_schedule",
    "list_fee_schedules",
    "load_fee_catalog",
]
