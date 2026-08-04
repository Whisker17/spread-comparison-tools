"""Price-impact guard (WHI-845): capture, threshold, status reclassification."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from spread_compare.impact import (
    apply_impact_threshold,
    derive_price_impact_bps,
    fraction_to_impact_bps,
)
from spread_compare.models import FeeBreakdown, Quote
from spread_compare.settings import clear_settings_cache, load_impact_settings

_TS = datetime(2026, 8, 4, tzinfo=UTC)


def _ok_quote(*, impact: Decimal | None, total: Decimal = Decimal("10")) -> Quote:
    return Quote(
        snapshot_id="snap-1",
        venue="tessera_solana",
        asset="BTC",
        instrument_type="prop_amm",
        side="buy",
        notional_usd=Decimal("1000000"),
        mid=Decimal("63809.32"),
        mid_source="binance_usdm_index",
        mid_timestamp=_TS,
        timestamp=_TS,
        effective_price=Decimal("344641.67"),
        spread_bps=Decimal("44011.1805"),
        total_cost_bps=total,
        qty_base=Decimal("2.9016"),
        fee_breakdown=FeeBreakdown(
            embedded_in_price=True,
            platform_fee_bps=Decimal("0"),
            gas_unknown=False,
            explicit_fee_bps=Decimal("0"),
            gas_bps=Decimal("0"),
        ),
        status="ok",
        price_impact_bps=impact,
    )


def test_fraction_to_impact_bps_jupiter_fraction() -> None:
    # Jupiter priceImpactPct 0.81 → 8100 bps (the $1M tessera_solana case).
    assert fraction_to_impact_bps("0.81") == Decimal("8100")
    assert fraction_to_impact_bps("0.000083") == Decimal("0.83")


def test_derive_prefers_reported_then_adverse_spread() -> None:
    assert derive_price_impact_bps(Decimal("8100"), Decimal("12")) == Decimal("8100")
    assert derive_price_impact_bps(None, Decimal("12.5")) == Decimal("12.5")
    # Favorable (negative) mid deviation is not pool exhaustion — impact 0.
    assert derive_price_impact_bps(None, Decimal("-12.5")) == Decimal("0")


def test_load_impact_settings_defaults() -> None:
    clear_settings_cache()
    settings = load_impact_settings()
    assert settings.max_price_impact_bps == 500


def test_apply_threshold_leaves_low_impact_ok() -> None:
    clear_settings_cache()
    q = _ok_quote(impact=Decimal("12.5"), total=Decimal("12.5"))
    out = apply_impact_threshold(q)
    assert out.status == "ok"
    assert out.price_impact_bps == Decimal("12.5")
    assert out.error_code is None


def test_apply_threshold_flags_high_impact() -> None:
    clear_settings_cache()
    q = _ok_quote(impact=Decimal("8100"), total=Decimal("38283"))
    out = apply_impact_threshold(q)
    assert out.status == "excessive_impact"
    assert out.error_code == "excessive_impact"
    assert out.price_impact_bps == Decimal("8100")
    # Numbers remain readable (WHI-845 AC).
    assert out.effective_price == Decimal("344641.67")
    assert out.total_cost_bps == Decimal("38283")
    assert out.spread_bps is not None
    assert out.qty_base is not None


def test_apply_threshold_skips_missing_impact() -> None:
    clear_settings_cache()
    q = _ok_quote(impact=None, total=Decimal("5"))
    out = apply_impact_threshold(q)
    assert out.status == "ok"
    assert out.price_impact_bps is None


def test_excessive_impact_quote_invariant_requires_prices() -> None:
    with pytest.raises(ValidationError):
        Quote(
            snapshot_id="snap-1",
            venue="mock",
            asset="BTC",
            instrument_type="prop_amm",
            side="buy",
            notional_usd=Decimal("1000"),
            mid=Decimal("100"),
            mid_source="binance_usdm_index",
            mid_timestamp=_TS,
            timestamp=_TS,
            fee_breakdown=FeeBreakdown(embedded_in_price=True, gas_unknown=False),
            status="excessive_impact",
            price_impact_bps=Decimal("900"),
            # pricing fields left null → must fail
        )


def test_excessive_impact_requires_price_impact_bps() -> None:
    with pytest.raises(ValidationError, match="price_impact_bps"):
        Quote(
            snapshot_id="snap-1",
            venue="mock",
            asset="BTC",
            instrument_type="prop_amm",
            side="buy",
            notional_usd=Decimal("1000"),
            mid=Decimal("100"),
            mid_source="binance_usdm_index",
            mid_timestamp=_TS,
            timestamp=_TS,
            effective_price=Decimal("101"),
            spread_bps=Decimal("100"),
            total_cost_bps=Decimal("100"),
            qty_base=Decimal("1"),
            fee_breakdown=FeeBreakdown(
                embedded_in_price=True,
                gas_unknown=False,
                explicit_fee_bps=Decimal("0"),
                gas_bps=Decimal("0"),
            ),
            status="excessive_impact",
            price_impact_bps=None,
        )


def test_threshold_override_via_local_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local overlay can raise the threshold so a mid-impact quote stays ok."""
    import spread_compare.settings as settings_mod

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "impact.yaml").write_text(
        "max_price_impact_bps: 500\n", encoding="utf-8"
    )
    (config_dir / "impact.local.yaml").write_text(
        "max_price_impact_bps: 10000\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings_mod, "_CONFIG_DIR", config_dir)
    clear_settings_cache()
    assert load_impact_settings().max_price_impact_bps == 10000
    q = _ok_quote(impact=Decimal("8100"), total=Decimal("9000"))
    out = apply_impact_threshold(q)
    assert out.status == "ok"
    clear_settings_cache()
