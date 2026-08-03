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
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
)

from spread_compare.models import FeeSchedule, InstrumentType, VenueClass
from spread_compare.venues import VENUES

_REPO_ROOT = Path(__file__).resolve().parent.parent
_FEES_DIR: Final[Path] = _REPO_ROOT / "config" / "fees"

# Instrument types each venue_class must publish (CEX serves spot + perp on one slug).
_INSTRUMENTS_BY_CLASS: Final[dict[VenueClass, frozenset[InstrumentType]]] = {
    "cex": frozenset({"spot", "perp"}),
    "perp_dex": frozenset({"perp"}),
    "amm_dex": frozenset({"amm_pool"}),
    "prop_amm": frozenset({"prop_amm"}),
}


class _VenueFeeFile(BaseModel):
    """One ``config/fees/<slug>.yaml`` document."""

    model_config = ConfigDict(extra="forbid")

    venue: str
    schedules: list[FeeSchedule] = Field(min_length=1)

    @field_validator("schedules", mode="before")
    @classmethod
    def _inject_venue(cls, value: object, info: ValidationInfo) -> object:
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
        # Caller may already upper; normalize once here as the sole owner.
        return schedule.model_copy(update={"asset": asset.upper()})

    def all_schedules(self) -> list[FeeSchedule]:
        """All schedules in stable venue/instrument order."""
        return sorted(
            self._all,
            key=lambda s: (s.venue, s.instrument_type),
        )


def required_instruments(venue_class: VenueClass) -> frozenset[InstrumentType]:
    """Instrument types a venue of ``venue_class`` must publish schedules for."""
    return _INSTRUMENTS_BY_CLASS[venue_class]


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"config {path} must be a YAML mapping, got {type(raw).__name__}"
        )
    return raw


def _validate_schedule(sched: FeeSchedule) -> list[str]:
    """Cross-field checks beyond the pydantic shape."""
    errs: list[str] = []
    if not sched.source_urls:
        errs.append(f"{sched.venue}/{sched.instrument_type}: source_urls empty")
    if not sched.fee_embedded_in_quote and sched.taker_bps is None:
        errs.append(
            f"{sched.venue}/{sched.instrument_type}: taker_bps required when "
            "fee_embedded_in_quote is false"
        )
    if sched.tiers:
        names = {t.name for t in sched.tiers}
        if sched.default_tier not in names:
            errs.append(
                f"{sched.venue}/{sched.instrument_type}: default_tier="
                f"{sched.default_tier!r} not in tiers {sorted(names)}"
            )
        # Top-level maker/taker should match the default tier row when present.
        default_row = next(
            (t for t in sched.tiers if t.name == sched.default_tier), None
        )
        if default_row is not None:
            if (
                sched.taker_bps is not None
                and default_row.taker_bps != sched.taker_bps
            ):
                errs.append(
                    f"{sched.venue}/{sched.instrument_type}: taker_bps "
                    f"{sched.taker_bps} != tiers[{sched.default_tier}].taker_bps "
                    f"{default_row.taker_bps}"
                )
            if (
                sched.maker_bps is not None
                and default_row.maker_bps != sched.maker_bps
            ):
                errs.append(
                    f"{sched.venue}/{sched.instrument_type}: maker_bps "
                    f"{sched.maker_bps} != tiers[{sched.default_tier}].maker_bps "
                    f"{default_row.maker_bps}"
                )
    return errs


def _validate_coverage(catalog: FeeCatalog) -> None:
    """Fail if any registered venue lacks its required instrument schedules."""
    missing: list[str] = []
    for slug, info in sorted(VENUES.items()):
        for itype in sorted(required_instruments(info.venue_class)):
            try:
                sched = catalog.get(slug, itype)
            except KeyError:
                missing.append(f"{slug}/{itype}: schedule missing")
                continue
            if sched.venue != slug:
                missing.append(
                    f"{slug}/{itype}: venue field {sched.venue!r} != file slug"
                )
            missing.extend(_validate_schedule(sched))
    if missing:
        raise ValueError(
            "fee catalog incomplete or invalid:\n  - " + "\n  - ".join(missing)
        )


def load_fee_catalog(*, fees_dir: Path | None = None) -> FeeCatalog:
    """Parse all ``config/fees/*.yaml`` files and validate coverage.

    ``fees_dir`` overrides the default path (tests). Raises on schema mismatch
    or missing required venue × instrument schedules.
    """
    directory = fees_dir if fees_dir is not None else _FEES_DIR
    if not directory.is_dir():
        raise FileNotFoundError(f"fee config directory missing: {directory}")

    schedules: list[FeeSchedule] = []
    # Skip per-deployment overrides (*.local.yaml); fee schedules are
    # checked-in data, not tunables that need local overlays.
    paths = sorted(
        p for p in directory.glob("*.yaml") if not p.name.endswith(".local.yaml")
    )
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


__all__ = [
    "FeeCatalog",
    "clear_fee_catalog_cache",
    "get_fee_catalog",
    "get_fee_schedule",
    "list_fee_schedules",
    "load_fee_catalog",
    "required_instruments",
]
