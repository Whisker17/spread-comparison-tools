"""Venue slug registry matches WHI-799 §6.5."""

from spread_compare.venues import VENUES, get_venue, known_slugs


def test_canonical_slugs_present() -> None:
    expected = {
        "binance",
        "bybit",
        "hyperliquid",
        "lighter",
        "apex",
        "uniswap_eth",
        "aerodrome_base",
        "pancakeswap_bsc",
        "humidifi",
        "tessera_solana",
        "tessera_base",
        "tessera_bsc",
        "bisonfi",
    }
    assert known_slugs() == frozenset(expected)


def test_retired_tessera_slug_absent() -> None:
    assert "tessera" not in VENUES


def test_get_venue_display_and_class() -> None:
    info = get_venue("tessera_bsc")
    assert info.display_name == "Tessera (BSC)"
    assert info.venue_class == "prop_amm"
    assert info.chain == "bsc"


def test_venue_chain_for_amm() -> None:
    assert get_venue("uniswap_eth").chain == "ethereum"
    assert get_venue("binance").chain is None
    assert get_venue("hyperliquid").chain is None
