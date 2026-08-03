"""Fee catalog loader + coverage (WHI-812)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from spread_compare.adapters.registry import get as registry_get
from spread_compare.fees import (
    clear_fee_catalog_cache,
    get_fee_catalog,
    get_fee_schedule,
    list_fee_schedules,
    load_fee_catalog,
    required_instruments,
)
from spread_compare.venues import VENUES, known_slugs

# Derived from venue_class (same matrix as the loader coverage check).
_EXPECTED: dict[str, tuple[str, ...]] = {
    slug: tuple(sorted(required_instruments(info.venue_class)))
    for slug, info in VENUES.items()
}


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_fee_catalog_cache()
    yield
    clear_fee_catalog_cache()


def test_catalog_covers_every_registered_venue() -> None:
    catalog = get_fee_catalog()
    assert set(VENUES) == known_slugs()
    for slug, instruments in _EXPECTED.items():
        assert slug in VENUES
        for itype in instruments:
            sched = catalog.get(slug, itype)  # type: ignore[arg-type]
            assert sched.venue == slug
            assert sched.instrument_type == itype
            assert sched.source_urls, f"{slug}/{itype} needs source_urls"
            assert sched.updated_at is not None


def test_list_fee_schedules_sorted() -> None:
    rows = list_fee_schedules()
    assert len(rows) >= len(VENUES)
    keys = [(r.venue, r.instrument_type) for r in rows]
    assert keys == sorted(keys)


def test_cex_default_taker_rates() -> None:
    """Spot-check default_taker numbers against published schedules."""
    binance_spot = get_fee_schedule("binance", "spot")
    assert binance_spot.taker_bps == Decimal("10")
    assert binance_spot.maker_bps == Decimal("10")
    assert binance_spot.default_tier == "default_taker"
    assert binance_spot.funding_model == "none"

    binance_perp = get_fee_schedule("binance", "perp")
    assert binance_perp.taker_bps == Decimal("5")
    assert binance_perp.maker_bps == Decimal("2")
    assert binance_perp.funding_model == "perp_8h"

    bybit_perp = get_fee_schedule("bybit", "perp")
    assert bybit_perp.taker_bps == Decimal("5.5")
    assert bybit_perp.maker_bps == Decimal("2")


def test_perp_dex_rates_and_funding() -> None:
    hl = get_fee_schedule("hyperliquid", "perp")
    assert hl.taker_bps == Decimal("4.5")
    assert hl.maker_bps == Decimal("1.5")
    assert hl.funding_model == "perp_continuous"

    lighter = get_fee_schedule("lighter", "perp")
    assert lighter.taker_bps == Decimal("0")
    assert lighter.maker_bps == Decimal("0")

    apex = get_fee_schedule("apex", "perp")
    assert apex.taker_bps == Decimal("5")
    assert apex.maker_bps == Decimal("2")
    assert apex.funding_model == "perp_continuous"


def test_amm_lp_tiers_and_gas_fallback() -> None:
    uni = get_fee_schedule("uniswap_eth", "amm_pool")
    assert uni.fee_embedded_in_quote is True
    assert uni.lp_fee_tiers_bps == [
        Decimal("1"),
        Decimal("5"),
        Decimal("30"),
        Decimal("100"),
    ]
    assert uni.gas_estimate_usd == Decimal("8")

    pcs = get_fee_schedule("pancakeswap_bsc", "amm_pool")
    assert pcs.lp_fee_tiers_bps == [
        Decimal("1"),
        Decimal("5"),
        Decimal("25"),
        Decimal("100"),
    ]

    aero = get_fee_schedule("aerodrome_base", "amm_pool")
    assert aero.lp_fee_tiers_bps is None
    assert aero.fee_embedded_in_quote is True


def test_amm_config_lp_tiers_match_probe_constants() -> None:
    """Display lp_fee_tiers_bps must stay aligned with quoter probe fee units."""
    from spread_compare.adapters._amm_common import (
        PANCAKE_FEE_TIERS,
        UNISWAP_FEE_TIERS,
        fee_to_lp_bps,
    )

    uni = get_fee_schedule("uniswap_eth", "amm_pool")
    assert uni.lp_fee_tiers_bps == [fee_to_lp_bps(f) for f in UNISWAP_FEE_TIERS]
    pcs = get_fee_schedule("pancakeswap_bsc", "amm_pool")
    assert pcs.lp_fee_tiers_bps == [fee_to_lp_bps(f) for f in PANCAKE_FEE_TIERS]


def test_prop_amm_embedded() -> None:
    for slug in (
        "humidifi",
        "tessera_solana",
        "tessera_base",
        "tessera_bsc",
        "bisonfi",
    ):
        sched = get_fee_schedule(slug, "prop_amm")
        assert sched.fee_embedded_in_quote is True
        assert sched.taker_bps is None
        assert sched.maker_bps is None


def test_get_fee_schedule_stamps_asset() -> None:
    sched = get_fee_schedule("binance", "spot", asset="btc")
    assert sched.asset == "BTC"
    bare = get_fee_schedule("binance", "spot")
    assert bare.asset is None


def test_adapter_get_fees_is_config_backed() -> None:
    for slug, instruments in _EXPECTED.items():
        adapter = registry_get(slug)
        for itype in instruments:
            from_adapter = adapter.get_fees("BTC", instrument_type=itype)  # type: ignore[arg-type]
            from_config = get_fee_schedule(slug, itype, asset="BTC")  # type: ignore[arg-type]
            assert from_adapter == from_config


def test_bad_yaml_fails_fast(tmp_path: Path) -> None:
    bad = tmp_path / "binance.yaml"
    bad.write_text(
        yaml.dump(
            {
                "venue": "binance",
                "schedules": [
                    {
                        # invalid instrument_type fails pydantic validation
                        "instrument_type": "not_a_real_type",
                        "source_urls": ["https://example.com"],
                        "updated_at": "2026-08-03T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid fee config"):
        load_fee_catalog(fees_dir=tmp_path)


def test_missing_required_venue_fails(tmp_path: Path) -> None:
    """A directory missing a registered venue fails coverage validation."""
    only = tmp_path / "binance.yaml"
    only.write_text(
        (Path(__file__).resolve().parents[1] / "config" / "fees" / "binance.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fee catalog incomplete"):
        load_fee_catalog(fees_dir=tmp_path)


def test_venue_filename_mismatch_fails(tmp_path: Path) -> None:
    path = tmp_path / "binance.yaml"
    path.write_text(
        yaml.dump(
            {
                "venue": "bybit",
                "schedules": [
                    {
                        "instrument_type": "spot",
                        "maker_bps": "10",
                        "taker_bps": "10",
                        "source_urls": ["https://example.com"],
                        "updated_at": "2026-08-03T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match filename stem"):
        load_fee_catalog(fees_dir=tmp_path)
